"""Retrieval tests.

The claim Atlas makes is that answers are grounded in real passages from the user's own
library. These tests hold the parts of that claim that can be checked mechanically: search
finds relevant passages, it never crosses account boundaries, and every result carries a
locator that resolves.

They run with the deterministic hashing embedder, so no network and no API key.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.ai.local_embedder import HashingEmbeddingProvider
from atlas.models.paper import PaperChunk
from atlas.retrieval.context import build_context, compose_user_turn, markers_used
from atlas.retrieval.search import RRF_K, RetrievedChunk, fuse
from tests.support.pdf_builder import build_pdf

# Two documents with clearly different vocabulary, so a lexical embedder can separate them.
TRANSFORMERS_PDF = build_pdf(
    [
        [
            "Efficient Transformer Inference on Commodity Hardware",
            "Jane Researcher",
            "",
            "Abstract",
            "Transformer inference latency is dominated by attention over long sequences. We "
            "apply key-value cache quantisation and speculative decoding, reducing median "
            "latency by thirty-one percent on commodity graphics hardware without measurable "
            "loss of accuracy on the downstream benchmark suite.",
            "",
            "1 Introduction",
            "Quantisation reduces the memory bandwidth required per decoding step, which is "
            "the binding constraint for autoregressive generation on consumer devices.",
            "",
            "2 Results",
            "Speculative decoding contributed the larger share of the speedup, accounting for "
            "nineteen of the thirty-one percentage points we measured.",
        ]
    ]
)

PROTEINS_PDF = build_pdf(
    [
        [
            "Protein Structure Prediction from Sequence Alignments",
            "Alex Biologist",
            "",
            "Abstract",
            "We predict tertiary protein structure from multiple sequence alignments using "
            "evolutionary coupling analysis. Predicted contact maps agree with crystallographic "
            "structures at a median precision of eighty-four percent across the benchmark set "
            "of globular proteins.",
            "",
            "1 Method",
            "Coevolving residue pairs indicate spatial proximity in the folded protein, which "
            "constrains the space of plausible tertiary conformations.",
        ]
    ]
)


async def upload_and_index(client: AsyncClient, api: str, data: bytes, run_worker) -> str:  # type: ignore[no-untyped-def]
    response = await client.post(
        f"{api}/papers", files={"file": ("paper.pdf", data, "application/pdf")}
    )
    assert response.status_code == 202, response.text
    await run_worker()
    return response.json()["id"]


class TestHashingEmbedder:
    """The offline embedder must be a real embedding, not noise, or retrieval tests prove
    nothing."""

    async def test_is_deterministic(self) -> None:
        embedder = HashingEmbeddingProvider(dimensions=256)
        first = await embedder.embed_one("attention is all you need")
        second = await embedder.embed_one("attention is all you need")
        assert first == second

    async def test_produces_unit_vectors(self) -> None:
        """Cosine distance assumes normalised vectors."""
        embedder = HashingEmbeddingProvider(dimensions=256)
        vector = await embedder.embed_one("protein structure prediction")
        magnitude = sum(value * value for value in vector) ** 0.5
        assert magnitude == pytest.approx(1.0, abs=1e-6)

    async def test_related_text_scores_higher_than_unrelated(self) -> None:
        embedder = HashingEmbeddingProvider(dimensions=1024)
        query, related, unrelated = await embedder.embed(
            [
                "transformer inference latency",
                "reducing transformer inference latency on hardware",
                "protein folding from sequence alignments",
            ]
        )

        def similarity(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        assert similarity(query, related) > similarity(query, unrelated)

    async def test_handles_empty_text(self) -> None:
        """A stopword-only passage must not produce a zero vector, which cosine cannot rank."""
        embedder = HashingEmbeddingProvider(dimensions=64)
        vector = await embedder.embed_one("the of and")
        assert sum(abs(value) for value in vector) > 0


class TestFusion:
    def _chunk(self, ordinal: int) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=uuid.uuid4(),
            paper_id=uuid.UUID(int=1),
            paper_title="A Paper",
            content=f"passage {ordinal}",
            ordinal=ordinal,
            page_start=1,
            page_end=1,
            section_title=None,
        )

    def test_a_passage_found_by_both_outranks_one_found_by_either(self) -> None:
        """Agreement between two independent signals is evidence, and should win."""
        shared, vector_only, lexical_only = (self._chunk(i) for i in range(3))

        fused = fuse([vector_only, shared], [lexical_only, shared])

        assert fused[0].chunk_id == shared.chunk_id
        assert fused[0].found_by == "both"

    def test_scores_follow_reciprocal_rank(self) -> None:
        first, second = self._chunk(0), self._chunk(1)
        fused = fuse([first, second], [])

        assert fused[0].score == pytest.approx(1 / (RRF_K + 1))
        assert fused[1].score == pytest.approx(1 / (RRF_K + 2))

    def test_records_where_each_result_came_from(self) -> None:
        vector_only, lexical_only = self._chunk(0), self._chunk(1)
        by_id = {hit.chunk_id: hit for hit in fuse([vector_only], [lexical_only])}

        assert by_id[vector_only.chunk_id].found_by == "meaning"
        assert by_id[lexical_only.chunk_id].found_by == "keyword"

    def test_is_stable_for_identical_input(self) -> None:
        chunks = [self._chunk(i) for i in range(5)]
        assert [c.chunk_id for c in fuse(chunks, [])] == [c.chunk_id for c in fuse(chunks, [])]

    def test_handles_both_lists_empty(self) -> None:
        assert fuse([], []) == []


class TestContext:
    def _chunk(self, ordinal: int, content: str = "x" * 400) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=uuid.uuid4(),
            paper_id=uuid.UUID(int=1),
            paper_title="A Paper",
            content=content,
            ordinal=ordinal,
            page_start=ordinal + 1,
            page_end=ordinal + 1,
            section_title="Results",
        )

    def test_numbers_sources_from_one_in_relevance_order(self) -> None:
        context = build_context([self._chunk(0), self._chunk(1)])
        assert [source.marker for source in context.sources] == [1, 2]

    def test_includes_the_locator_in_each_source(self) -> None:
        """The model can only cite a location if it is shown one."""
        context = build_context([self._chunk(0)])
        assert "p. 1" in context.text
        assert "§Results" in context.text

    def test_stops_at_the_token_budget(self) -> None:
        context = build_context([self._chunk(i) for i in range(20)], token_budget=300)

        assert len(context.sources) < 20
        assert context.dropped > 0
        assert context.token_estimate <= 300 or len(context.sources) == 1

    def test_always_keeps_at_least_one_source(self) -> None:
        """A budget smaller than the first passage should still ground the answer."""
        context = build_context([self._chunk(0, "y" * 5000)], token_budget=10)
        assert len(context.sources) == 1

    def test_an_empty_context_instructs_the_model_to_say_so(self) -> None:
        context = build_context([])
        turn = compose_user_turn("What causes this?", context)

        assert context.is_empty
        assert "does not contain" in turn or "None" in turn
        assert "general knowledge" in turn

    def test_places_sources_before_the_question(self) -> None:
        context = build_context([self._chunk(0)])
        turn = compose_user_turn("Why?", context)
        assert turn.index("SOURCES") < turn.index("QUESTION")


class TestMarkerParsing:
    def test_finds_markers_the_answer_used(self) -> None:
        assert markers_used("As shown in [1] and again in [3].", available=4) == {1, 3}

    def test_discards_a_marker_with_no_source_behind_it(self) -> None:
        """The model occasionally writes [9] when five sources were supplied. Rendering that
        as a citation is exactly the fabrication Atlas exists to prevent."""
        assert markers_used("According to [9].", available=5) == set()

    def test_ignores_bracketed_text_that_is_not_a_citation(self) -> None:
        assert markers_used("The set [a, b] is unordered.", available=3) == set()


class TestSearch:
    async def test_finds_the_relevant_paper(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        transformers = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, PROTEINS_PDF, run_worker)

        response = await registered_client.get(
            f"{api}/assistant/search?q=reducing transformer inference latency"
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert results, "expected at least one passage"
        assert results[0]["paper_id"] == transformers

    async def test_every_result_can_be_cited(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """A passage that cannot say where it came from is not evidence."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        results = (await registered_client.get(f"{api}/assistant/search?q=quantisation")).json()[
            "results"
        ]

        assert results
        for result in results:
            assert result["chunk_id"]
            assert result["paper_id"]
            assert result["locator"]
            assert result["content"].strip()

    async def test_reports_how_each_result_was_found(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        results = (
            await registered_client.get(f"{api}/assistant/search?q=speculative decoding")
        ).json()["results"]

        assert results
        assert all(result["found_by"] in {"meaning", "keyword", "both"} for result in results)

    async def test_can_be_scoped_to_one_paper(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        proteins = await upload_and_index(registered_client, api, PROTEINS_PDF, run_worker)

        results = (
            await registered_client.get(f"{api}/assistant/search?q=latency&paper_id={proteins}")
        ).json()["results"]

        assert all(result["paper_id"] == proteins for result in results)

    async def test_returns_nothing_for_an_empty_library(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.get(f"{api}/assistant/search?q=anything at all")
        assert response.json()["results"] == []

    async def test_survives_punctuation_a_person_might_type(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """`websearch_to_tsquery` must absorb input that would make `to_tsquery` raise."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        for query in ['"speculative decoding"', "latency -protein", "what & why | how", "((("]:
            response = await registered_client.get(f"{api}/assistant/search", params={"q": query})
            assert response.status_code == 200, f"query {query!r} failed"

    async def test_never_returns_a_bibliography_entry(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """Reference lists are filtered at query time too, so papers indexed before that
        change stop surfacing them as evidence."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        results = (
            await registered_client.get(f"{api}/assistant/search?q=transformer attention")
        ).json()["results"]

        assert not any(
            (result["section_title"] or "").lower().startswith(("references", "bibliography"))
            for result in results
        )

    async def test_never_returns_another_users_passages(
        self,
        registered_client: AsyncClient,
        other_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """The strongest privacy guarantee in the product: one library, one account."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        results = (
            await other_client.get(f"{api}/assistant/search?q=transformer inference latency")
        ).json()["results"]

        assert results == []


class TestIndexing:
    async def test_ingestion_embeds_every_chunk(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        unindexed = await db.scalar(
            select(func.count()).select_from(PaperChunk).where(PaperChunk.embedding.is_(None))
        )
        assert unindexed == 0

    async def test_reports_index_coverage(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        status = (await registered_client.get(f"{api}/assistant/status")).json()

        assert status["embeddings_available"] is True
        assert status["total_chunks"] > 0
        assert status["indexed_chunks"] == status["total_chunks"]

    async def test_reindexing_does_not_duplicate_work(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        before = await db.scalar(select(func.count()).select_from(PaperChunk))

        await registered_client.post(f"{api}/papers/{paper_id}/reprocess")
        await run_worker()

        assert await db.scalar(select(func.count()).select_from(PaperChunk)) == before
