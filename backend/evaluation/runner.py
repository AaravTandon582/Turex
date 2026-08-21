"""Ingest the benchmark corpus, run every query through real retrieval, and score the result.

"Real" is the point. The corpus goes through the same PDF parser, the same chunker, the same
embedder, and the same hybrid search the product uses. A benchmark that called the ranking
function directly would score the ranking function, and every bug found so far in retrieval
has been somewhere else — in how pages were unwrapped, in which sections were skipped, in what
the section filter matched.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from evaluation.corpus import CORPUS, QUERIES, Document, assert_markers_are_unique
from evaluation.metrics import Scores, score
from turex.ai.base import EmbeddingProvider
from turex.ingestion.chunking import chunk_document
from turex.ingestion.pdf import parse_pdf
from turex.models.paper import Paper, PaperChunk, PaperSection, ProcessingStatus
from turex.models.user import User
from turex.retrieval.search import RetrievalService

RESULTS_PER_QUERY = 5
"""How deep the benchmark looks. Beyond five, a result is not one a reader would read."""


@dataclass(frozen=True, slots=True)
class Report:
    scores: Scores
    chunks_indexed: int
    per_query_rank: dict[str, int | None]
    """Where the answer came back, one-based, or None if it never did."""

    def render(self) -> str:
        lines = ["Retrieval benchmark", "", self.scores.as_table(), "", "  per query:"]
        for query in QUERIES:
            rank = self.per_query_rank[query.text]
            position = f"#{rank}" if rank else "not found"
            lines.append(f"    {position:<11} {query.text}")
        if self.scores.misses:
            lines += ["", "  missed entirely:"]
            lines += [f"    {query}" for query in self.scores.misses]
        return "\n".join(lines)


async def ingest_corpus(
    db: AsyncSession, owner: User, embedder: EmbeddingProvider, corpus: Sequence[Document] = CORPUS
) -> int:
    """Put the corpus through the real ingestion path and return the chunk count.

    Writes directly rather than going through the upload endpoint and the job queue: the
    benchmark measures retrieval, and waiting on a worker would make it slow and flaky without
    exercising anything retrieval depends on.
    """
    from tests.support.pdf_builder import build_pdf  # test-only helper; not shipped in `turex`

    total = 0
    for document in corpus:
        parsed = parse_pdf(_as_stream(build_pdf(document.pages)))
        paper = Paper(
            owner_id=owner.id,
            title=document.title,
            original_filename=f"{document.slug}.pdf",
            content_hash=f"benchmark-{document.slug}",
            storage_key=f"benchmark/{document.slug}.pdf",
            file_size_bytes=0,
            page_count=len(document.pages),
            status=ProcessingStatus.ready,
        )
        db.add(paper)
        await db.flush()

        sections: dict[int, PaperSection] = {}
        for detected in parsed.sections:
            section = PaperSection(
                paper_id=paper.id,
                ordinal=detected.ordinal,
                title=detected.title,
                level=detected.level,
                page_start=detected.page_start,
                page_end=detected.page_end,
            )
            db.add(section)
            sections[detected.ordinal] = section
        await db.flush()

        chunks = chunk_document(parsed)
        vectors = await embedder.embed([chunk.content for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            owning = (
                sections.get(chunk.section_ordinal) if chunk.section_ordinal is not None else None
            )
            db.add(
                PaperChunk(
                    paper_id=paper.id,
                    section_id=owning.id if owning else None,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    token_estimate=chunk.token_estimate,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    embedding=vector,
                )
            )
            total += 1

    await db.commit()
    return total


def _as_stream(data: bytes):  # type: ignore[no-untyped-def]
    import io

    return io.BytesIO(data)


async def run(db: AsyncSession, owner_id: uuid.UUID, retrieval: RetrievalService) -> Report:
    """Score every benchmark query against what retrieval actually returns."""
    assert_markers_are_unique()

    judgements: dict[str, list[bool]] = {}
    ranks: dict[str, int | None] = {}

    for query in QUERIES:
        results = await retrieval.search(
            owner_id=owner_id, query=query.text, limit=RESULTS_PER_QUERY
        )
        hits = [query.answer_marker in result.content for result in results]
        judgements[query.text] = hits
        ranks[query.text] = next((i for i, hit in enumerate(hits, start=1) if hit), None)

    chunk_count = (
        await db.scalar(
            select(func.count())
            .select_from(PaperChunk)
            .join(Paper, Paper.id == PaperChunk.paper_id)
            .where(Paper.owner_id == owner_id)
        )
        or 0
    )

    return Report(scores=score(judgements), chunks_indexed=chunk_count, per_query_rank=ranks)
