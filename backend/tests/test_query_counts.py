"""Guards against N+1 queries on the endpoints that grow with the library.

A page that issues one query per row is fast with four papers and unusable with four hundred,
and the difference does not show up in a timing test on a development machine with a warm
cache. So these assert the *shape* of the work instead: the query count must not grow with the
number of rows.

Each test loads a library of one size, records the count, loads a larger one, and requires the
count to be unchanged. The absolute number is deliberately not asserted — it changes whenever
a feature legitimately needs another query, and a test that fails on every such change gets
deleted rather than read.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from atlas.db import session as session_module
from tests.support.pdf_builder import build_pdf
from tests.test_retrieval import upload_and_index


@contextmanager
def count_queries() -> Iterator[list[str]]:
    """Record every statement the engine executes inside the block."""
    engine = session_module._engine
    assert engine is not None, "engine not initialised"
    statements: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    # The sync engine underneath is what emits the event; the async wrapper delegates to it.
    event.listen(engine.sync_engine, "before_cursor_execute", before_execute)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_execute)


def paper_pdf(index: int) -> bytes:
    """A small but genuinely distinct paper, so chunks and embeddings differ between them."""
    return build_pdf(
        [
            [
                f"Sparse Attention Variant {index}",
                f"Author {index} Surname",
                "",
                "Abstract",
                f"We evaluate sparse attention pattern {index} on long-context retrieval, "
                f"reducing memory by {index * 3} percent while holding accuracy within one "
                "point of the dense baseline across the evaluation suite.",
                "",
                "1 Introduction",
                f"Long-context inference is bounded by attention memory. Variant {index} "
                "restricts each query to a strided neighbourhood, which lowers the quadratic "
                "term without changing the model's parameter count or its training recipe.",
            ]
        ]
    )


async def upload_papers(client: AsyncClient, api: str, run_worker, count: int, start: int) -> None:  # type: ignore[no-untyped-def]
    for index in range(start, start + count):
        await upload_and_index(client, api, paper_pdf(index), run_worker)


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/papers?limit=50", "library list"),
        ("/papers/stats", "library counters"),
        ("/projects", "project list"),
        ("/study/progress", "study progress"),
    ],
)
async def test_query_count_does_not_grow_with_the_library(
    registered_client: AsyncClient, api: str, run_worker, path: str, label: str
) -> None:
    await upload_papers(registered_client, api, run_worker, count=2, start=1)
    with count_queries() as first:
        response = await registered_client.get(f"{api}{path}")
    assert response.status_code == 200, response.text

    await upload_papers(registered_client, api, run_worker, count=4, start=3)
    with count_queries() as second:
        response = await registered_client.get(f"{api}{path}")
    assert response.status_code == 200, response.text

    assert len(second) == len(first), (
        f"{label} issued {len(first)} queries for 2 papers and {len(second)} for 6 — "
        "the count grows with the data, which is an N+1"
    )


async def test_graph_query_count_does_not_grow_with_the_library(
    registered_client: AsyncClient, api: str, run_worker
) -> None:
    """Split out because the graph reads chunk text, so it is the likeliest place to regress."""
    await upload_papers(registered_client, api, run_worker, count=2, start=10)
    with count_queries() as first:
        assert (await registered_client.get(f"{api}/graph")).status_code == 200

    await upload_papers(registered_client, api, run_worker, count=4, start=12)
    with count_queries() as second:
        assert (await registered_client.get(f"{api}/graph")).status_code == 200

    assert len(second) == len(first), (
        f"the knowledge graph issued {len(first)} queries for 2 papers and {len(second)} "
        "for 6 — the count grows with the data"
    )


async def test_recommendations_do_not_query_per_candidate(
    registered_client: AsyncClient, api: str, run_worker
) -> None:
    """The document-vector cache exists for this. Without it the cost is quadratic."""
    await upload_papers(registered_client, api, run_worker, count=3, start=20)
    with count_queries() as first:
        assert (await registered_client.get(f"{api}/recommendations?limit=6")).status_code == 200

    await upload_papers(registered_client, api, run_worker, count=3, start=23)
    with count_queries() as second:
        assert (await registered_client.get(f"{api}/recommendations?limit=6")).status_code == 200

    assert len(second) == len(first), (
        f"recommendations issued {len(first)} queries for 3 papers and {len(second)} for 6"
    )


async def test_every_foreign_key_is_indexed(db) -> None:  # type: ignore[no-untyped-def]
    """A foreign key without an index makes every cascading delete a table scan.

    Ten of them were missing when this was written: deleting one paper sequentially scanned
    flashcards, quizzes, message_citations, and evidence. It costs nothing at five papers and
    is a scan per delete at any real size.

    Composite indexes do not count. An index on (owner_id, paper_id) cannot serve a lookup on
    paper_id alone, because paper_id is not the leading column — which is exactly the trap
    that hid these.
    """
    from sqlalchemy import text

    unindexed = list(
        await db.scalars(
            text(
                """
                SELECT c.conrelid::regclass || '.' || a.attname
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'f'
                  AND NOT EXISTS (
                    SELECT 1 FROM pg_index i
                    WHERE i.indrelid = c.conrelid AND a.attnum = i.indkey[0]
                  )
                ORDER BY 1
                """
            )
        )
    )
    assert not unindexed, f"foreign keys with no index: {unindexed}"


async def test_equations_and_references_are_one_query_each(
    registered_client: AsyncClient, api: str, run_worker, db
) -> None:
    """Both are per-paper lists, so their cost must not scale with how many rows they return.

    A loop that loaded each row's paper, or resolved each reference's identifier, would be
    invisible on a short bibliography and painful on a long one.
    """
    paper_id = await upload_and_index(registered_client, api, paper_pdf(1), run_worker)

    with count_queries() as equations:
        assert (
            await registered_client.get(f"{api}/papers/{paper_id}/equations")
        ).status_code == 200
    with count_queries() as references:
        assert (
            await registered_client.get(f"{api}/papers/{paper_id}/references")
        ).status_code == 200

    # Session lookup, ownership check, and the list itself. The exact number is not the point;
    # that it is small and fixed is.
    assert len(equations) <= 4, [statement[:60] for statement in equations]
    assert len(references) <= 4, [statement[:60] for statement in references]
