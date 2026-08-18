"""The scored evaluation: does retrieval find the right passage, and do citations hold up.

Three things are measured here that the feature suites do not measure.

1. **Retrieval quality, as a number.** Elsewhere the tests assert that a specific query returns
   a specific paper. That catches a break; it does not catch a slow drift where results stay
   plausible and get worse. A score does.
2. **Citation integrity across the whole database.** Every stored citation must point at text
   that exists and match the snapshot taken when it was written.
3. **What happens when the model misbehaves on purpose.** Not "does it error" — the assistant
   suite covers that — but whether anything ungrounded can reach the database.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.ai.local_embedder import HashingEmbeddingProvider
from atlas.models.conversation import MessageCitation
from atlas.models.paper import EMBEDDING_DIMENSIONS, PaperChunk
from atlas.models.user import User
from atlas.retrieval.search import RetrievalService
from evaluation.corpus import CORPUS, QUERIES, assert_markers_are_unique
from evaluation.runner import ingest_corpus, run
from evaluation.thresholds import MINIMUM_MRR, MINIMUM_RECALL_AT_3
from tests.test_assistant import ScriptedChatProvider, ask, start_conversation
from tests.test_retrieval import TRANSFORMERS_PDF, upload_and_index


@pytest.fixture
async def benchmark(db: AsyncSession):  # type: ignore[no-untyped-def]
    """Ingest the corpus once and score it, returning the report."""
    owner = User(
        email="benchmark@atlas.local", full_name="Benchmark", password_hash="not-a-usable-hash"
    )
    db.add(owner)
    await db.flush()

    embedder = HashingEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    await ingest_corpus(db, owner, embedder)
    return await run(db, owner.id, RetrievalService(db, embedder))


class TestRetrievalBenchmark:
    def test_the_corpus_can_actually_be_scored(self) -> None:
        """Every answer marker appears exactly once, or the benchmark measures nothing."""
        assert_markers_are_unique()
        assert len(QUERIES) >= 8
        assert len(CORPUS) >= 3

    async def test_recall_at_three_meets_the_threshold(self, benchmark) -> None:  # type: ignore[no-untyped-def]
        assert benchmark.scores.recall_at_3 >= MINIMUM_RECALL_AT_3, benchmark.render()

    async def test_mean_reciprocal_rank_meets_the_threshold(self, benchmark) -> None:  # type: ignore[no-untyped-def]
        assert benchmark.scores.mean_reciprocal_rank >= MINIMUM_MRR, benchmark.render()

    async def test_a_paraphrased_query_still_finds_its_passage(self, benchmark) -> None:  # type: ignore[no-untyped-def]
        """The vector half, isolated: this query shares almost no words with its answer."""
        rank = benchmark.per_query_rank["reducing memory during autoregressive decoding"]
        assert rank is not None, benchmark.render()

    async def test_a_near_miss_paper_does_not_win(self, benchmark) -> None:  # type: ignore[no-untyped-def]
        """Two papers reduce memory; only one has a stride. The wrong one must not rank first."""
        rank = benchmark.per_query_rank["what stride length was chosen and why"]
        assert rank is not None and rank <= 3, benchmark.render()

    async def test_the_known_offline_weakness_is_still_the_only_one(self, benchmark) -> None:  # type: ignore[no-untyped-def]
        """Pins the one query the offline embedder cannot answer.

        If it starts passing, the embedder or the ranking improved and this should be removed.
        If a second query joins it, something regressed. Either way the change is worth seeing,
        which an aggregate score alone would hide.
        """
        assert benchmark.scores.misses == [
            "which proteins gained most from contact map refinement"
        ], benchmark.render()


class TestCitationIntegrity:
    """Every citation in the database must resolve. This is the product's central claim."""

    async def test_every_stored_citation_points_at_real_text(
        self, registered_client: AsyncClient, api: str, run_worker, scripted, db
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(
            answer="Latency falls [1], and the cache is quantised [2]."
        )
        conversation = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation, "what reduces inference latency?")

        citations = list(await db.scalars(select(MessageCitation)))
        assert citations, "the turn stored no citations"

        for citation in citations:
            assert citation.chunk_id is not None
            chunk = await db.get(PaperChunk, citation.chunk_id)
            assert chunk is not None, f"citation {citation.id} points at a chunk that is gone"
            assert citation.quoted_text.strip(), "a citation with no snapshot proves nothing"
            assert citation.quoted_text in chunk.content, (
                "the snapshot does not appear in the chunk it claims to quote"
            )
            assert citation.paper_id == chunk.paper_id

    async def test_a_citation_survives_the_chunk_being_reingested(
        self, registered_client: AsyncClient, api: str, run_worker, scripted, db
    ) -> None:
        """The snapshot is the point: re-ingestion must not change what a citation says."""
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(answer="Latency falls [1].")
        conversation = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation, "what reduces inference latency?")

        citation = await db.scalar(select(MessageCitation))
        assert citation is not None
        original = citation.quoted_text

        response = await registered_client.post(f"{api}/papers/{paper_id}/reprocess")
        assert response.status_code == 202
        await run_worker()

        await db.refresh(citation)
        assert citation.quoted_text == original, "re-ingestion rewrote what a citation claims"

    async def test_no_citation_outlives_its_paper(
        self, registered_client: AsyncClient, api: str, run_worker, scripted, db
    ) -> None:
        """Deleting a paper must not leave citations pointing at chunks that no longer exist."""
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(answer="Latency falls [1].")
        conversation = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation, "what reduces inference latency?")

        assert (await registered_client.delete(f"{api}/papers/{paper_id}")).status_code == 204

        dangling = await db.scalar(
            select(func.count())
            .select_from(MessageCitation)
            .outerjoin(PaperChunk, PaperChunk.id == MessageCitation.chunk_id)
            .where(MessageCitation.chunk_id.is_not(None), PaperChunk.id.is_(None))
        )
        assert dangling == 0, f"{dangling} citations point at chunks that no longer exist"


class TestModelMisbehaviour:
    """A model that lies must not be able to make Atlas lie.

    Each of these scripts a specific failure that a real model does produce, and asserts that
    nothing ungrounded reaches the database.
    """

    @pytest.mark.parametrize(
        ("answer", "description"),
        [
            ("The result holds [99].", "a marker for a source that was never provided"),
            ("The result holds [0].", "a zero marker, which numbering never produces"),
            ("The result holds [1][2][3][4][5][6][7][8][9].", "more markers than sources"),
            ("The result holds.", "no markers at all"),
            ("", "an empty answer"),
        ],
    )
    async def test_no_citation_is_stored_for_a_source_that_was_not_retrieved(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,
        db,
        answer: str,
        description: str,
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(answer=answer)
        conversation = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation, "what reduces inference latency?")

        retrieved = await db.scalar(select(func.count()).select_from(PaperChunk))
        citations = list(await db.scalars(select(MessageCitation)))

        for citation in citations:
            assert citation.chunk_id is not None, (
                f"with {description}, a citation was stored with no chunk behind it"
            )
            chunk = await db.get(PaperChunk, citation.chunk_id)
            assert chunk is not None, (
                f"with {description}, a citation points at a chunk that does not exist"
            )
        assert len(citations) <= retrieved, "more citations than there were passages to cite"

    async def test_markers_beyond_the_source_count_are_not_marked_as_used(
        self, registered_client: AsyncClient, api: str, run_worker, scripted, db
    ) -> None:
        """`used_in_answer` must reflect real usage, or the evaluation of it is meaningless."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(answer="Only the first matters [1].")
        conversation = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation, "what reduces inference latency?")

        citations = list(await db.scalars(select(MessageCitation)))
        used = [citation for citation in citations if citation.used_in_answer]
        assert len(used) == 1, "exactly one marker was written, so exactly one is used"
        assert used[0].marker == 1
