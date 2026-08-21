"""Finding the passages that answer a question.

Retrieval runs two searches and fuses their rankings:

* **Vector** finds passages that mean something similar, catching paraphrase.
* **Lexical** finds passages containing the exact terms — a gene name, an author, an equation
  label, a dataset. Scientific vocabulary is precisely where embeddings are weakest, so
  dropping this half would make Turex worse at the literature it exists to read.

Their scores are not comparable (cosine distance versus `ts_rank_cd`), so they are combined by
**reciprocal rank fusion**, which uses only each result's position in its own list. That needs
no score normalisation and no tuning per corpus.

Every result carries the identifiers and locators needed to cite it. A passage that cannot say
where it came from is not evidence, and this module never returns one.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from turex.ai.base import EmbeddingProvider
from turex.core.logging import get_logger
from turex.models.paper import ProcessingStatus
from turex.retrieval.reranking import CANDIDATE_MULTIPLIER, rerank

logger = get_logger(__name__)

RRF_K = 60
"""Reciprocal-rank-fusion damping. The standard value: large enough that the top few ranks are
not overwhelmingly dominant, small enough that deep results contribute little."""

CANDIDATES_PER_STRATEGY = 40
"""How deep each search goes before fusion. Wider than the final result count, so a passage
ranked poorly by one strategy can still be rescued by the other."""


@dataclass(slots=True)
class RetrievedChunk:
    """A passage, with everything needed to cite it."""

    chunk_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    content: str
    ordinal: int
    page_start: int | None
    page_end: int | None
    section_title: str | None
    authors: list[str] = field(default_factory=list)
    publication_year: int | None = None

    score: float = 0.0
    vector_rank: int | None = None
    lexical_rank: int | None = None

    @property
    def locator(self) -> str:
        """A human-readable position, as it appears in a citation."""
        parts: list[str] = []
        if self.page_start:
            pages = (
                f"pp. {self.page_start}–{self.page_end}"
                if self.page_end and self.page_end != self.page_start
                else f"p. {self.page_start}"
            )
            parts.append(pages)
        if self.section_title:
            parts.append(f"§{self.section_title}")
        return " · ".join(parts) or f"passage {self.ordinal + 1}"

    @property
    def found_by(self) -> str:
        if self.vector_rank is not None and self.lexical_rank is not None:
            return "both"
        return "meaning" if self.vector_rank is not None else "keyword"


# Both searches select the same columns so one row mapper serves them.
_COLUMNS = """
    c.id                AS chunk_id,
    c.paper_id          AS paper_id,
    c.content           AS content,
    c.ordinal           AS ordinal,
    c.page_start        AS page_start,
    c.page_end          AS page_end,
    s.title             AS section_title,
    p.title             AS paper_title,
    p.original_filename AS original_filename,
    p.authors           AS authors,
    p.publication_year  AS publication_year
"""

# Ownership and readiness are enforced in the query itself, not filtered afterwards: a
# retrieval path that forgot the owner filter would leak another user's private research
# into an answer.
_JOINS = """
    FROM paper_chunks c
    JOIN papers p ON p.id = c.paper_id
    LEFT JOIN paper_sections s ON s.id = c.section_id
    WHERE p.owner_id = :owner_id
      AND p.status = :ready
      AND (s.title IS NULL OR s.title !~* :non_content_sections)
"""

NON_CONTENT_SECTION_PATTERN = (
    r"^\s*([0-9]+(\.[0-9]+)*\.?\s+)?(references|bibliography|works cited|acknowledge?ments?)\b"
)
"""Bibliographies match strongly on vocabulary and assert nothing, so they are never useful
evidence. Filtered here as well as at chunking time, because papers ingested before that
change still have reference chunks in the index."""

_VECTOR_SQL = """
    SELECT {columns}, (c.embedding <=> CAST(:query_vector AS vector)) AS distance
    {joins}
      AND c.embedding IS NOT NULL
      {scope}
    ORDER BY c.embedding <=> CAST(:query_vector AS vector)
    LIMIT :limit
"""

_LEXICAL_SQL = """
    SELECT {columns},
           ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', :query)) AS rank
    {joins}
      AND c.content_tsv @@ websearch_to_tsquery('english', :query)
      {scope}
    ORDER BY rank DESC
    LIMIT :limit
"""

_SCOPE_CLAUSE = "AND c.paper_id IN :paper_ids"


def _statement(template: str, *, scoped: bool) -> TextClause:
    """Build a search statement, adding the paper filter only when one was asked for.

    Composed rather than written with an `IS NULL OR ...` guard: that form defeats index use
    on the filtered path and needs an array type binding for a parameter that is usually
    absent.
    """
    statement = text(
        template.format(
            columns=_COLUMNS,
            joins=_JOINS,
            scope=_SCOPE_CLAUSE if scoped else "",
        )
    )
    if scoped:
        statement = statement.bindparams(bindparam("paper_ids", expanding=True))
    return statement


def _to_pgvector(values: Sequence[float]) -> str:
    """pgvector accepts its literal text form, which avoids registering a bind processor
    for a raw-SQL parameter."""
    return "[" + ",".join(f"{value:.7g}" for value in values) + "]"


def _row_to_chunk(row: Row[Any]) -> RetrievedChunk:
    authors = [author.get("name", "") for author in (row.authors or [])]
    return RetrievedChunk(
        chunk_id=row.chunk_id,
        paper_id=row.paper_id,
        # Falls back to the filename: a paper can be cited before extraction found a title.
        paper_title=row.paper_title or row.original_filename,
        content=row.content,
        ordinal=row.ordinal,
        page_start=row.page_start,
        page_end=row.page_end,
        section_title=row.section_title,
        authors=[name for name in authors if name],
        publication_year=row.publication_year,
    )


class RetrievalService:
    def __init__(
        self, db: AsyncSession, embedder: EmbeddingProvider, *, rerank: bool = True
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._rerank = rerank
        """Off only for measurement. Reranking is worth 12 points of recall@3 with a real
        embedding model, and the benchmark has to be able to run both ways to show that."""

    async def search(
        self,
        *,
        owner_id: uuid.UUID,
        query: str,
        limit: int = 8,
        paper_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve the passages most likely to answer `query`.

        `paper_ids` narrows the search to specific papers — what "ask about this paper"
        does, as opposed to asking the whole library.
        """
        cleaned = query.strip()
        if not cleaned:
            return []

        scoped = list(paper_ids) if paper_ids else None

        vector_hits = await self._vector_search(owner_id, cleaned, scoped)
        lexical_hits = await self._lexical_search(owner_id, cleaned, scoped)

        # Fusion ranks by position alone — it never looks at the passages. Reranking a wider
        # pool than the caller asked for is what gives it something to reorder; reranking
        # exactly `limit` results could only shuffle them.
        pool = fuse(vector_hits, lexical_hits)[: limit * CANDIDATE_MULTIPLIER]
        fused = (rerank(cleaned, pool) if self._rerank else pool)[:limit]

        logger.info(
            "retrieved passages",
            extra={
                "query_length": len(cleaned),
                "vector_hits": len(vector_hits),
                "lexical_hits": len(lexical_hits),
                "returned": len(fused),
            },
        )
        return fused

    async def _vector_search(
        self, owner_id: uuid.UUID, query: str, paper_ids: list[uuid.UUID] | None
    ) -> list[RetrievedChunk]:
        embedding = await self._embedder.embed_one(query)
        parameters: dict[str, Any] = {
            "owner_id": owner_id,
            "ready": ProcessingStatus.ready.value,
            "non_content_sections": NON_CONTENT_SECTION_PATTERN,
            "query_vector": _to_pgvector(embedding),
            "limit": CANDIDATES_PER_STRATEGY,
        }
        if paper_ids:
            parameters["paper_ids"] = paper_ids

        rows = await self._db.execute(_statement(_VECTOR_SQL, scoped=bool(paper_ids)), parameters)
        return [_row_to_chunk(row) for row in rows]

    async def _lexical_search(
        self, owner_id: uuid.UUID, query: str, paper_ids: list[uuid.UUID] | None
    ) -> list[RetrievedChunk]:
        parameters: dict[str, Any] = {
            "owner_id": owner_id,
            "ready": ProcessingStatus.ready.value,
            "non_content_sections": NON_CONTENT_SECTION_PATTERN,
            # `websearch_to_tsquery` accepts what a person actually types — quoted phrases,
            # OR, a leading minus — and never raises on malformed input, unlike to_tsquery.
            "query": query,
            "limit": CANDIDATES_PER_STRATEGY,
        }
        if paper_ids:
            parameters["paper_ids"] = paper_ids

        rows = await self._db.execute(_statement(_LEXICAL_SQL, scoped=bool(paper_ids)), parameters)
        return [_row_to_chunk(row) for row in rows]


def fuse(
    vector_hits: Sequence[RetrievedChunk], lexical_hits: Sequence[RetrievedChunk]
) -> list[RetrievedChunk]:
    """Combine two rankings by reciprocal rank fusion.

    `score = Σ 1 / (K + rank)` over the lists a passage appears in. A passage found by both
    strategies outranks one found by either alone, which is the behaviour we want: agreement
    between independent signals is evidence.
    """
    merged: dict[uuid.UUID, RetrievedChunk] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        entry = merged.setdefault(hit.chunk_id, hit)
        entry.vector_rank = rank
        entry.score += 1.0 / (RRF_K + rank)

    for rank, hit in enumerate(lexical_hits, start=1):
        entry = merged.setdefault(hit.chunk_id, hit)
        entry.lexical_rank = rank
        entry.score += 1.0 / (RRF_K + rank)

    # Ties broken by document order, so repeated identical queries return a stable ordering.
    return sorted(
        merged.values(), key=lambda chunk: (-chunk.score, chunk.paper_id.hex, chunk.ordinal)
    )
