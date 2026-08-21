"""Claiming and completing ingestion jobs.

The queue is a table. Claiming uses `FOR UPDATE SKIP LOCKED`, which lets several workers pull
from the same table concurrently without any of them blocking on a row another already holds.

A claim is a *lease*, not a lock: it carries an expiry. A worker that crashes mid-job leaves a
row whose lease runs out, and the job is reclaimed rather than stranded in `running` forever.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from turex.core.logging import get_logger
from turex.models.job import IngestionJob, IngestionStage, JobStatus
from turex.models.paper import Paper, ProcessingStatus

logger = get_logger(__name__)

LEASE_SECONDS = 600
"""How long a worker may hold a job before another may take it. Comfortably longer than the
slowest realistic parse, so a healthy worker is never overtaken mid-document."""

RETRY_BACKOFF_SECONDS = (30, 120, 600)


class JobQueue:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def enqueue(self, paper_id: uuid.UUID, *, max_attempts: int = 3) -> IngestionJob:
        """Create a job. Committed by the caller alongside the paper it belongs to."""
        job = IngestionJob(paper_id=paper_id, max_attempts=max_attempts)
        self._db.add(job)
        await self._db.flush()
        return job

    async def claim(self, *, worker_id: str) -> IngestionJob | None:
        """Take the oldest due job, or return None.

        `SKIP LOCKED` is what makes this safe under concurrency: a row another worker has
        already locked is passed over instead of blocking this transaction.
        """
        now = datetime.now(UTC)

        job = await self._db.scalar(
            select(IngestionJob)
            .where(
                or_(
                    # Never started, and due.
                    (IngestionJob.status == JobStatus.queued) & (IngestionJob.scheduled_at <= now),
                    # Claimed by a worker that has since died.
                    (IngestionJob.status == JobStatus.running) & (IngestionJob.locked_until < now),
                )
            )
            .order_by(IngestionJob.scheduled_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        if job is None:
            return None

        if job.status == JobStatus.running:
            logger.warning(
                "reclaiming a job whose lease expired",
                extra={"job_id": str(job.id), "previous_worker": job.locked_by},
            )

        job.status = JobStatus.running
        job.attempts += 1
        job.started_at = job.started_at or now
        job.locked_by = worker_id
        job.locked_until = now + timedelta(seconds=LEASE_SECONDS)
        job.error_message = None

        await self._db.execute(
            update(Paper).where(Paper.id == job.paper_id).values(status=ProcessingStatus.processing)
        )
        await self._db.commit()
        return job

    async def report_progress(
        self, job: IngestionJob, *, stage: IngestionStage, progress: int
    ) -> None:
        """Publish a stage change.

        Committed immediately: the point of tracking progress is that someone watching the
        upload can see it, and an uncommitted row is invisible to their next request.
        """
        job.stage = stage
        job.progress = max(0, min(100, progress))
        job.locked_until = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
        await self._db.commit()

    async def succeed(self, job: IngestionJob) -> None:
        now = datetime.now(UTC)
        job.status = JobStatus.succeeded
        job.stage = IngestionStage.complete
        job.progress = 100
        job.finished_at = now
        job.locked_by = None
        job.locked_until = None
        await self._db.commit()

    async def fail(self, job: IngestionJob, *, message: str, retryable: bool) -> None:
        """Record a failure, scheduling a retry when one could plausibly help.

        A corrupt PDF fails identically every time, so retrying it only delays telling the
        user. Transient faults — a provider timeout, a lost connection — are worth another
        attempt with a backoff.
        """
        now = datetime.now(UTC)
        job.error_message = message
        job.locked_by = None
        job.locked_until = None

        exhausted = job.attempts >= job.max_attempts
        if retryable and not exhausted:
            delay = RETRY_BACKOFF_SECONDS[min(job.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            job.status = JobStatus.queued
            job.scheduled_at = now + timedelta(seconds=delay)
            logger.warning(
                "ingestion failed; retry scheduled",
                extra={
                    "job_id": str(job.id),
                    "attempt": job.attempts,
                    "retry_in_seconds": delay,
                },
            )
        else:
            job.status = JobStatus.failed
            job.finished_at = now
            await self._db.execute(
                update(Paper)
                .where(Paper.id == job.paper_id)
                .values(status=ProcessingStatus.failed, failure_reason=message)
            )
            logger.error(
                "ingestion failed permanently",
                extra={"job_id": str(job.id), "attempts": job.attempts, "reason": message},
            )

        await self._db.commit()
