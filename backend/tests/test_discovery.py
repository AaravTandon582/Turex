"""Recommendation and knowledge-graph tests.

Both features exist to surface connections the user has not noticed. The rule they must not
break is that a surfaced connection has to be real: a recommendation states the concrete
reason it was made, and a graph edge means two papers genuinely share a term.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.support.pdf_builder import build_pdf
from tests.test_retrieval import PROTEINS_PDF, TRANSFORMERS_PDF, upload_and_index

# A third paper sharing vocabulary with the transformers one, so concept edges have something
# to connect.
QUANTISATION_PDF = build_pdf(
    [
        [
            "Post-Training Quantisation for Transformer Inference",
            "Sam Engineer",
            "",
            "Abstract",
            "We study post-training quantisation of transformer weights and activations. "
            "Quantisation reduces memory bandwidth per decoding step, which is the binding "
            "constraint for transformer inference latency on commodity hardware.",
            "",
            "1 Method",
            "We quantise transformer attention projections to eight bits and measure inference "
            "latency against a full-precision baseline on commodity hardware.",
        ]
    ]
)


class TestRecommendations:
    async def test_says_nothing_about_an_empty_library(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Recommending from nothing would be inventing, not suggesting."""
        assert (await registered_client.get(f"{api}/recommendations")).json() == []

    async def test_says_nothing_when_there_is_nothing_to_compare(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        assert (await registered_client.get(f"{api}/recommendations")).json() == []

    async def test_every_recommendation_explains_itself(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """A suggestion the reader cannot evaluate is one they learn to ignore."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, QUANTISATION_PDF, run_worker)

        results = (await registered_client.get(f"{api}/recommendations")).json()

        assert results
        for entry in results:
            assert entry["reason"].strip()
            assert entry["title"]

    async def test_relates_an_unread_paper_to_what_is_being_read(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        being_read = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, QUANTISATION_PDF, run_worker)
        await registered_client.patch(
            f"{api}/papers/{being_read}", json={"reading_status": "reading"}
        )

        results = (await registered_client.get(f"{api}/recommendations")).json()

        related = [entry for entry in results if entry["related_to_id"] == being_read]
        assert related, "expected the unread paper to be linked to the one being read"
        assert "reading" in related[0]["reason"]

    async def test_never_recommends_a_paper_already_read(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        first = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, PROTEINS_PDF, run_worker)
        await registered_client.patch(f"{api}/papers/{first}", json={"reading_status": "read"})

        results = (await registered_client.get(f"{api}/recommendations")).json()

        assert all(entry["paper_id"] != first for entry in results)

    async def test_never_recommends_another_users_paper(
        self,
        registered_client: AsyncClient,
        other_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, QUANTISATION_PDF, run_worker)

        assert (await other_client.get(f"{api}/recommendations")).json() == []


class TestKnowledgeGraph:
    async def test_is_empty_without_papers(self, registered_client: AsyncClient, api: str) -> None:
        body = (await registered_client.get(f"{api}/graph")).json()
        assert body["nodes"] == []
        assert body["edges"] == []

    async def test_places_every_paper(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, PROTEINS_PDF, run_worker)

        body = (await registered_client.get(f"{api}/graph")).json()

        papers = [node for node in body["nodes"] if node["kind"] == "paper"]
        assert len(papers) == 2
        assert all(node["label"] and node["entity_id"] for node in papers)

    async def test_a_concept_edge_means_a_shared_term(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """Concepts come from term overlap, so an edge is a fact about the text — not an
        inference something made up."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, QUANTISATION_PDF, run_worker)

        body = (await registered_client.get(f"{api}/graph")).json()
        concepts = {node["id"]: node for node in body["nodes"] if node["kind"] == "concept"}

        assert concepts, "two papers on the same subject should share at least one concept"
        # The shared terms should be about the subject, not about measurement.
        labels = {node["label"] for node in concepts.values()}
        assert any("inference" in label or "attention" in label for label in labels), labels

        for node in concepts.values():
            # Every concept joins at least two papers, or it is not a connection.
            linked = [
                edge
                for edge in body["edges"]
                if edge["target"] == node["id"] and edge["kind"] == "mentions"
            ]
            assert len(linked) >= 2

    async def test_unrelated_papers_share_no_concepts(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """Transformers and protein folding have nothing in common.

        Linking them on incidental shared vocabulary — "percent", "median" — is what turns a
        knowledge graph into decoration, so a term has to actually recur to count.
        """
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, PROTEINS_PDF, run_worker)

        body = (await registered_client.get(f"{api}/graph")).json()
        concepts = [node["label"] for node in body["nodes"] if node["kind"] == "concept"]

        assert concepts == [], f"unexpected shared concepts: {concepts}"

    async def test_includes_projects_and_open_questions(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        project_id = (
            await registered_client.post(f"{api}/projects", json={"name": "Efficient inference"})
        ).json()["id"]
        await registered_client.put(
            f"{api}/projects/{project_id}/papers", json={"paper_id": paper_id}
        )
        await registered_client.post(
            f"{api}/hypotheses",
            json={"statement": "Quantisation dominates the speedup.", "project_id": project_id},
        )

        body = (await registered_client.get(f"{api}/graph")).json()
        kinds = {node["kind"] for node in body["nodes"]}
        edge_kinds = {edge["kind"] for edge in body["edges"]}

        assert {"paper", "project", "question"} <= kinds
        assert {"gathered_in", "asks"} <= edge_kinds

    async def test_every_edge_connects_real_nodes(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """A dangling edge would render as a line to nowhere."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await upload_and_index(registered_client, api, QUANTISATION_PDF, run_worker)

        body = (await registered_client.get(f"{api}/graph")).json()
        node_ids = {node["id"] for node in body["nodes"]}

        for edge in body["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids

    async def test_never_shows_another_users_library(
        self,
        registered_client: AsyncClient,
        other_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        assert (await other_client.get(f"{api}/graph")).json()["nodes"] == []
