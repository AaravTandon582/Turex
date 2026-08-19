"""Turning an uploaded file into a searchable paper.

The pipeline is a sequence of named stages, each of which reports progress before it starts.
Stages are ordered so the paper becomes useful as early as possible: metadata lands before
chunking, so the library shows a real title while indexing is still running.

Failures are classified. A corrupt PDF is permanent and the user is told immediately; a
transient fault is retried with a backoff.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.ai.base import EmbeddingProvider
from atlas.core.errors import ProcessingFailedError
from atlas.core.logging import get_logger
from atlas.ingestion.chunking import chunk_document
from atlas.ingestion.equations import detect_equations
from atlas.ingestion.pdf import ParsedDocument, parse_pdf
from atlas.ingestion.references import parse_references
from atlas.models.job import IngestionJob, IngestionStage
from atlas.models.paper import (
    Paper,
    PaperChunk,
    PaperEquation,
    PaperReference,
    PaperSection,
    ProcessingStatus,
)
from atlas.retrieval.indexer import ChunkIndexer
from atlas.storage.base import DocumentStore
from atlas.workers.queue import JobQueue

logger = get_logger(__name__)

_REFERENCES_HEADING = re.compile(r"\b(references?|bibliography|works cited)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    paper_id: uuid.UUID
    section_count: int
    chunk_count: int
    indexed_count: int = 0


class IngestionPipeline:
    def __init__(
        self,
        db: AsyncSession,
        store: DocumentStore,
        queue: JobQueue,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._db = db
        self._store = store
        self._queue = queue
        self._embedder = embedder
        """When absent, chunks are stored without vectors. The paper is still readable and
        still lexically searchable; a backfill adds the vectors once a provider exists."""

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
        equation_count = await self._store_equations(paper, document)
        reference_count = await self._store_references(paper, document)
        await self._db.commit()

        indexed = 0
        if self._embedder is not None:
            await self._queue.report_progress(job, stage=IngestionStage.embedding, progress=85)
            indexed = await ChunkIndexer(self._db, self._embedder).index_paper(paper.id)

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
                "equations": equation_count,
                "references": reference_count,
                "indexed": indexed,
            },
        )
        return IngestionResult(
            paper_id=paper.id,
            section_count=len(sections),
            chunk_count=chunk_count,
            indexed_count=indexed,
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

    async def _store_equations(self, paper: Paper, document: ParsedDocument) -> int:
        """Replace this paper's equations with what the current parse found."""
        await self._db.execute(delete(PaperEquation).where(PaperEquation.paper_id == paper.id))

        found = detect_equations(document)
        for ordinal, equation in enumerate(found):
            self._db.add(
                PaperEquation(
                    paper_id=paper.id,
                    ordinal=ordinal,
                    content=equation.content,
                    label=equation.label,
                    page_number=equation.page_number,
                )
            )
        await self._db.flush()
        return len(found)

    async def _store_references(self, paper: Paper, document: ParsedDocument) -> int:
        """Replace this paper's bibliography entries with what the current parse found."""
        await self._db.execute(delete(PaperReference).where(PaperReference.paper_id == paper.id))

        section = next(
            (
                candidate
                for candidate in document.sections
                if _REFERENCES_HEADING.search(candidate.title)
            ),
            None,
        )
        if section is None:
            return 0

        found = parse_references(section.text)
        for ordinal, reference in enumerate(found):
            self._db.add(
                PaperReference(
                    paper_id=paper.id,
                    ordinal=ordinal,
                    marker=reference.marker,
                    text=reference.text[:4000],
                    arxiv_id=reference.arxiv_id,
                    doi=reference.doi[:255] if reference.doi else None,
                    year=reference.year,
                )
            )
        await self._db.flush()
        return len(found)

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
