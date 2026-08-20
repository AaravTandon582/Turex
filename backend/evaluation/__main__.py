"""Run the benchmark against a throwaway account in the configured database.

    python -m evaluation

Prints the report and exits non-zero if retrieval falls below the thresholds the test suite
enforces, so the same numbers can be checked by hand and in CI without two implementations.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import delete

from atlas.ai.registry import get_registry
from atlas.core.config import get_settings
from atlas.db.session import dispose_engine, init_engine, session_scope
from atlas.models.user import User
from atlas.retrieval.search import RetrievalService
from evaluation.runner import ingest_corpus, run
from evaluation.thresholds import MINIMUM_MRR, MINIMUM_RECALL_AT_3

BENCHMARK_EMAIL = "benchmark@atlas.local"
"""A throwaway account. Deleted before and after every run, so a crashed run cannot poison
the next one."""


async def main() -> int:
    settings = get_settings()
    init_engine(settings)
    registry = get_registry(settings)

    try:
        async with session_scope() as db:
            # Remove anything a previous run left behind. Ingestion commits, so the rollback
            # at the end of this block never undid it — every run used to leave a user and a
            # corpus in the database, and the second run failed on the unique email.
            await db.execute(delete(User).where(User.email == BENCHMARK_EMAIL))
            await db.flush()

            owner = User(
                email=BENCHMARK_EMAIL,
                full_name="Benchmark",
                password_hash="not-a-usable-hash",
            )
            db.add(owner)
            await db.flush()

            embedder = registry.embedder()
            await ingest_corpus(db, owner, embedder)
            report = await run(db, owner.id, RetrievalService(db, embedder))

            print(report.render())
            print(f"\n  {report.chunks_indexed} chunks indexed")

            # Delete rather than roll back. Ingestion commits as it goes — it uses the real
            # pipeline on purpose — so a rollback here would undo nothing. The cascade takes
            # the papers, chunks, and sections with the account.
            await db.execute(delete(User).where(User.email == BENCHMARK_EMAIL))
    finally:
        await dispose_engine()

    failures = []
    if report.scores.recall_at_3 < MINIMUM_RECALL_AT_3:
        failures.append(f"recall@3 {report.scores.recall_at_3:.0%} < {MINIMUM_RECALL_AT_3:.0%}")
    if report.scores.mean_reciprocal_rank < MINIMUM_MRR:
        failures.append(f"MRR {report.scores.mean_reciprocal_rank:.3f} < {MINIMUM_MRR}")

    if failures:
        print("\nBELOW THRESHOLD: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
