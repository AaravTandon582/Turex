"""The ingestion worker loop.

Runs as background tasks inside the API process (see `docs/decisions.md` D2). Each task owns
its own database session, because a session is not safe to share across concurrent tasks.

The loop polls rather than listens. Polling costs one indexed query per interval and needs no
second system; at Turex's scale that is the right trade. Moving to `LISTEN`/`NOTIFY`, or to a
separate worker process, is a change to this file alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from turex.ai.registry import get_registry
from turex.core.config import Settings
from turex.core.errors import AppError, ProcessingFailedError
from turex.core.logging import bind_request_context, clear_request_context, get_logger
from turex.db.session import get_session_factory
from turex.ingestion.pipeline import IngestionPipeline
from turex.models.job import IngestionJob
from turex.storage.base import DocumentStore
from turex.workers.queue import JobQueue

logger = get_logger(__name__)

IDLE_BACKOFF_MULTIPLIER = 3
"""When the queue is empty, poll less often. Uploads are bursty; an idle instance should not
query the database three times a second all night."""


def worker_identity(index: int) -> str:
    """Identifies which process and task holds a lease, for debugging a stuck job."""
    return f"{socket.gethostname()}:{os.getpid()}:{index}"


class IngestionWorker:
    def __init__(self, settings: Settings, store: DocumentStore, *, index: int = 0) -> None:
        self._settings = settings
        self._store = store
        self._identity = worker_identity(index)
        self._idle_rounds = 0

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("ingestion worker started", extra={"worker": self._identity})
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                # The loop must survive anything a single job can do to it.
                logger.exception("ingestion worker loop error", extra={"worker": self._identity})
                processed = False

            self._idle_rounds = 0 if processed else min(self._idle_rounds + 1, 10)
            delay = self._settings.worker_poll_seconds * (
                IDLE_BACKOFF_MULTIPLIER if self._idle_rounds > 3 else 1
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)

        logger.info("ingestion worker stopped", extra={"worker": self._identity})

    async def run_once(self) -> bool:
        """Process one job. Returns False when the queue was empty."""
        async with get_session_factory()() as db:
            queue = JobQueue(db)
            job = await queue.claim(worker_id=self._identity)
            if job is None:
                return False

            bind_request_context(job_id=str(job.id), paper_id=str(job.paper_id))
            job_id = job.id
            try:
                registry = get_registry(self._settings)
                embedder = registry.embedder() if registry.embeddings_available else None
                pipeline = IngestionPipeline(db, self._store, queue, embedder)
                await pipeline.run(job)
                await queue.succeed(job)
            except ProcessingFailedError as exc:
                # The document itself is the problem: the same input will fail identically,
                # so retrying only delays telling the user.
                logger.info("document rejected during ingestion", extra={"detail": exc.detail})
                await self._fail(db, queue, job_id, message=exc.message, retryable=False)
            except AppError as exc:
                logger.warning("ingestion error", extra={"detail": exc.detail})
                await self._fail(
                    db, queue, job_id, message=exc.message, retryable=exc.status_code >= 500
                )
            except Exception as exc:
                # Unexpected: could be a transient fault, so allow the retry budget to decide.
                logger.exception("unexpected ingestion failure", exc_info=exc)
                await self._fail(
                    db,
                    queue,
                    job_id,
                    message="Turex couldn't process that document. It will try again shortly.",
                    retryable=True,
                )
            finally:
                clear_request_context()

            return True

    async def _fail(
        self,
        db: AsyncSession,
        queue: JobQueue,
        job_id: uuid.UUID,
        *,
        message: str,
        retryable: bool,
    ) -> None:
        await db.rollback()
        # Rollback expires ORM attributes even with expire_on_commit=False. Reload explicitly
        # before reading attempts or paper_id, otherwise failure handling itself raises.
        job = await db.get(IngestionJob, job_id, populate_existing=True)
        if job is not None:  # Deleting the paper also deletes its pending job.
            await queue.fail(job, message=message, retryable=retryable)


class WorkerPool:
    """Owns the worker tasks for the lifetime of the application."""

    def __init__(self, settings: Settings, store: DocumentStore) -> None:
        self._settings = settings
        self._store = store
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if not self._settings.worker_enabled:
            logger.info("ingestion workers disabled by configuration")
            return
        for index in range(max(1, self._settings.worker_concurrency)):
            worker = IngestionWorker(self._settings, self._store, index=index)
            self._tasks.append(
                asyncio.create_task(worker.run_forever(self._stop), name=f"turex-ingestion-{index}")
            )

    async def stop(self) -> None:
        """Signal the workers and wait for the current job to finish.

        Waiting matters: cancelling mid-parse would leave a claimed job to sit until its lease
        expires, delaying the retry by ten minutes for no reason.
        """
        self._stop.set()
        if not self._tasks:
            return
        done, pending = await asyncio.wait(self._tasks, timeout=30)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                task.result()
        self._tasks.clear()
