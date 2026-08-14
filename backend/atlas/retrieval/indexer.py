"""Embedding stored chunks so they can be found by meaning.

Runs as the last ingestion stage, and separately as a backfill for papers that were ingested
before an embedding provider was configured. Keeping it separable matters: switching embedding
model means re-indexing an existing library, not re-parsing it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.ai.base import EmbeddingProvider
from atlas.core.errors import ProviderUnavailableError
from atlas.core.logging import get_logger
from atlas.models.paper import Paper, PaperChunk

logger = get_logger(__name__)

WRITE_BATCH_SIZE = 96
"""Chunks embedded and written per round trip. Matches the provider batch size, so one
embedding call maps to one write."""


class ChunkIndexer:
    def __init__(self, db: AsyncSession, embedder: EmbeddingProvider) -> None:
        self._db = db
        self._embedder = embedder

    async def index_paper(self, paper_id: uuid.UUID) -> int:
        """Embed every unindexed chunk of a paper. Returns how many were written.

        Safe to run repeatedly: only chunks whose embedding is null are considered, so a run
        interrupted halfway resumes rather than paying for the work twice.
        """
        pending = list(
            await self._db.scalars(
                select(PaperChunk)
                .where(PaperChunk.paper_id == paper_id, PaperChunk.embedding.is_(None))
                .order_by(PaperChunk.ordinal)
            )
        )
        if not pending:
            return 0

        written = 0
        for start in range(0, len(pending), WRITE_BATCH_SIZE):
            batch = pending[start : start + WRITE_BATCH_SIZE]
            vectors = await self._embedder.embed([chunk.content for chunk in batch])

            if len(vectors) != len(batch):
                # A mismatch would silently pair passages with the wrong vectors, which is
                # worse than failing: retrieval would confidently cite the wrong page.
                raise ProviderUnavailableError(
                    "Atlas couldn't finish indexing that document.",
                    detail=f"embedder returned {len(vectors)} vectors for {len(batch)} chunks",
                )

            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector

            await self._db.flush()
            written += len(batch)

        logger.info("indexed chunks", extra={"paper_id": str(paper_id), "chunks": written})
        return written

    async def unindexed_paper_ids(self, *, limit: int = 50) -> list[uuid.UUID]:
        """Papers holding at least one chunk without an embedding."""
        rows = await self._db.scalars(
            select(PaperChunk.paper_id)
            .where(PaperChunk.embedding.is_(None))
            .group_by(PaperChunk.paper_id)
            .limit(limit)
        )
        return list(rows)

    async def clear_paper(self, paper_id: uuid.UUID) -> None:
        """Drop a paper's embeddings, so the next index run rebuilds them.

        Used when the embedding model changes: vectors from two different models are not
        comparable, and mixing them makes ranking meaningless.
        """
        await self._db.execute(
            update(PaperChunk).where(PaperChunk.paper_id == paper_id).values(embedding=None)
        )


async def index_coverage(db: AsyncSession, owner_id: uuid.UUID) -> tuple[int, int]:
    """How much of a library is searchable by meaning: (indexed chunks, total chunks)."""
    row = (
        await db.execute(
            select(
                func.count().filter(PaperChunk.embedding.is_not(None)),
                func.count(),
            )
            .select_from(PaperChunk)
            .join(Paper, Paper.id == PaperChunk.paper_id)
            .where(Paper.owner_id == owner_id)
        )
    ).one()
    return int(row[0]), int(row[1])
