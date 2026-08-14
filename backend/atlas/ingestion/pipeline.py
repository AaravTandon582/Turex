"""Turning an uploaded file into a searchable paper.

The pipeline is a sequence of named stages, each of which reports progress before it starts.
Stages are ordered so the paper becomes useful as early as possible: metadata lands before
chunking, so the library shows a real title while indexing is still running.

Failures are classified. A corrupt PDF is permanent and the user is told immediately; a
transient fault is retried with a backoff.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.core.errors import ProcessingFailedError
from atlas.core.logging import get_logger
from atlas.ingestion.chunking import chunk_document
from atlas.ingestion.pdf import ParsedDocument, parse_pdf
from atlas.models.job import IngestionJob, IngestionStage
from atlas.models.paper import Paper, PaperChunk, PaperSection, ProcessingStatus
from atlas.storage.base import DocumentStore
from atlas.workers.queue import JobQueue

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    paper_id: uuid.UUID
    section_count: int
    chunk_count: int


class IngestionPipeline:
    def __init__(self, db: AsyncSession, store: DocumentStore, queue: JobQueue) -> None:
        self._db = db
        self._store = store
        self._queue = queue

    async def run(self, job: IngestionJob) -> IngestionResult:
        paper = await self._db.get(Paper, job.paper_id)
        if paper is None:
            # The user deleted the paper while it was queued. Not an error.
            raise ProcessingFailedError(
                "That paper no longer exists.", detail=f"paper {job.paper_id} missing"
            )

        await self._queue.report_progress(job, stage=IngestionStage.extracting_text, progress=10)
        document = await self._parse(paper)

        await self._queue.report_progress(job, stage=IngestionStage.reading_structure, progress=35)
        sections = await self._store_sections(paper, document)

        await self._queue.report_progress(
            job, stage=IngestionStage.extracting_metadata, progress=55
        )
        self._apply_metadata(paper, document)
        await self._db.commit()

        await self._queue.report_progress(job, stage=IngestionStage.building_chunks, progress=70)
        chunk_count = await self._store_chunks(paper, document, sections)

        paper.status = ProcessingStatus.ready
        paper.failure_reason = None
        await self._db.commit()

        logger.info(
            "paper ingested",
            extra={
                "paper_id": str(paper.id),
                "pages": paper.page_count,
                "sections": len(sections),
                "chunks": chunk_count,
            },
        )
        return IngestionResult(
            paper_id=paper.id, section_count=len(sections), chunk_count=chunk_count
        )

    # -- stages -------------------------------------------------------------------

    async def _parse(self, paper: Paper) -> ParsedDocument:
        path = await self._store.open_path(paper.storage_key)
        # Parsing is CPU-bound and synchronous. Running it on a thread keeps the event loop
        # free to serve requests while a long document is being read.
        return await asyncio.to_thread(parse_pdf, path)

    async def _store_sections(
        self, paper: Paper, document: ParsedDocument
    ) -> dict[int, PaperSection]:
        # Re-ingestion replaces prior structure rather than appending to it.
        await self._db.execute(delete(PaperSection).where(PaperSection.paper_id == paper.id))

        sections: dict[int, PaperSection] = {}
        for parsed in document.sections:
            section = PaperSection(
                paper_id=paper.id,
                ordinal=parsed.ordinal,
                title=parsed.title[:500],
                level=parsed.level,
                page_start=parsed.page_start,
                page_end=parsed.page_end,
            )
            self._db.add(section)
            sections[parsed.ordinal] = section

        await self._db.flush()
        return sections

    def _apply_metadata(self, paper: Paper, document: ParsedDocument) -> None:
        """Fill in what extraction found, without overwriting what the user has corrected.

        Extraction is heuristic, so a user is expected to fix a wrong title occasionally. Once
        they have, re-ingesting the paper must not silently undo their correction — hence the
        `is None` guards rather than plain assignment.
        """
        metadata = document.metadata
        paper.page_count = document.page_count

        if paper.title is None and metadata.title:
            paper.title = metadata.title[:1000]
        if not paper.authors and metadata.authors:
            paper.authors = [{"name": name} for name in metadata.authors]
        if paper.abstract is None and metadata.abstract:
            paper.abstract = metadata.abstract
        if paper.publication_year is None and metadata.publication_year:
            paper.publication_year = metadata.publication_year
        if paper.doi is None and metadata.doi:
            paper.doi = metadata.doi[:255]
        if paper.arxiv_id is None and metadata.arxiv_id:
            paper.arxiv_id = metadata.arxiv_id[:64]

    async def _store_chunks(
        self,
        paper: Paper,
        document: ParsedDocument,
        sections: dict[int, PaperSection],
    ) -> int:
        await self._db.execute(delete(PaperChunk).where(PaperChunk.paper_id == paper.id))

        chunks = chunk_document(document)
        for chunk in chunks:
            section = (
                sections.get(chunk.section_ordinal) if chunk.section_ordinal is not None else None
            )
            self._db.add(
                PaperChunk(
                    paper_id=paper.id,
                    section_id=section.id if section else None,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    token_estimate=chunk.token_estimate,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    # Embeddings are added by the indexing stage in Milestone 3. A paper is
                    # readable and lexically searchable before then.
                    embedding=None,
                )
            )

        await self._db.flush()
        return len(chunks)


async def count_chunks(db: AsyncSession, paper_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(PaperChunk).where(PaperChunk.paper_id == paper_id)
        )
    ) or 0
