"""Research workspace tests: projects, hypotheses, evidence, experiments, notes, tasks.

The evidence tests carry the most weight. "Three passages support this hypothesis" is only
worth showing if each of those passages is a real one from a real paper — so the server reads
the passage itself rather than trusting anything the client sends.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_retrieval import TRANSFORMERS_PDF, upload_and_index
from turex.models.paper import PaperChunk
from turex.models.workspace import Evidence, Hypothesis, Note, Project


async def make_project(client: AsyncClient, api: str, **payload: object) -> str:
    response = await client.post(
        f"{api}/projects",
        json={"name": "Small model reasoning", **payload},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def make_hypothesis(client: AsyncClient, api: str, **payload: object) -> str:
    response = await client.post(
        f"{api}/hypotheses",
        json={
            "statement": "Structured retrieval improves reasoning accuracy more than scale alone.",
            **payload,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestProjects:
    async def test_creates_with_a_research_question(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.post(
            f"{api}/projects",
            json={
                "name": "Small model reasoning",
                "research_question": "Can structured retrieval improve reasoning accuracy?",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["research_question"] == "Can structured retrieval improve reasoning accuracy?"
        assert body["status"] == "active"

    async def test_rejects_a_blank_name(self, registered_client: AsyncClient, api: str) -> None:
        response = await registered_client.post(f"{api}/projects", json={"name": "   "})
        assert response.status_code == 422

    async def test_reports_counts_of_everything_inside(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """The project header answers 'what is in here' without five extra requests."""
        project_id = await make_project(registered_client, api)
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        await registered_client.put(
            f"{api}/projects/{project_id}/papers", json={"paper_id": paper_id}
        )
        await make_hypothesis(registered_client, api, project_id=project_id)
        await registered_client.post(
            f"{api}/experiments", json={"title": "Ablate the retriever", "project_id": project_id}
        )
        await registered_client.post(
            f"{api}/notes", json={"content": "Worth checking", "project_id": project_id}
        )
        await registered_client.post(f"{api}/projects/{project_id}/tasks", json={"title": "Read"})

        body = (await registered_client.get(f"{api}/projects/{project_id}")).json()

        assert body["paper_count"] == 1
        assert body["hypothesis_count"] == 1
        assert body["experiment_count"] == 1
        assert body["note_count"] == 1
        assert body["open_task_count"] == 1

    async def test_attaching_a_paper_is_idempotent(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        project_id = await make_project(registered_client, api)
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        for _ in range(2):
            response = await registered_client.put(
                f"{api}/projects/{project_id}/papers",
                json={"paper_id": paper_id, "relevance_note": "The baseline we build on"},
            )
            assert response.status_code == 204

        papers = (await registered_client.get(f"{api}/projects/{project_id}/papers")).json()
        assert len(papers) == 1
        assert papers[0]["relevance_note"] == "The baseline we build on"

    async def test_deleting_a_project_keeps_the_papers(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        """A project is a view onto the library, not a container that owns it."""
        project_id = await make_project(registered_client, api)
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        await registered_client.put(
            f"{api}/projects/{project_id}/papers", json={"paper_id": paper_id}
        )

        await registered_client.delete(f"{api}/projects/{project_id}")

        assert (await registered_client.get(f"{api}/papers/{paper_id}")).status_code == 200

    async def test_deleting_a_project_removes_its_hypotheses(
        self, registered_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        project_id = await make_project(registered_client, api)
        await make_hypothesis(registered_client, api, project_id=project_id)

        await registered_client.delete(f"{api}/projects/{project_id}")

        assert list(await db.scalars(select(Hypothesis))) == []

    async def test_another_user_cannot_reach_a_project(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        project_id = await make_project(registered_client, api)

        assert (await other_client.get(f"{api}/projects/{project_id}")).status_code == 404
        assert (await other_client.delete(f"{api}/projects/{project_id}")).status_code == 404


class TestHypotheses:
    async def test_starts_as_proposed(self, registered_client: AsyncClient, api: str) -> None:
        hypothesis_id = await make_hypothesis(registered_client, api)
        body = (await registered_client.get(f"{api}/hypotheses/{hypothesis_id}")).json()

        assert body["status"] == "proposed"
        assert body["supporting_count"] == 0
        assert body["contradicting_count"] == 0

    @pytest.mark.parametrize(
        "status", ["testing", "supported", "weakly_supported", "contradicted", "abandoned"]
    )
    async def test_moves_through_its_states(
        self, registered_client: AsyncClient, api: str, status: str
    ) -> None:
        hypothesis_id = await make_hypothesis(registered_client, api)

        response = await registered_client.patch(
            f"{api}/hypotheses/{hypothesis_id}", json={"status": status}
        )

        assert response.status_code == 200
        assert response.json()["status"] == status

    async def test_records_assumptions(self, registered_client: AsyncClient, api: str) -> None:
        """Recording assumptions is what makes a later failure interpretable."""
        hypothesis_id = await make_hypothesis(
            registered_client, api, assumptions="Retrieval quality is held constant."
        )
        body = (await registered_client.get(f"{api}/hypotheses/{hypothesis_id}")).json()
        assert body["assumptions"] == "Retrieval quality is held constant."

    async def test_can_exist_outside_a_project(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Ideas arrive before they are filed. Forcing a project first loses them."""
        hypothesis_id = await make_hypothesis(registered_client, api)
        assert (await registered_client.get(f"{api}/hypotheses/{hypothesis_id}")).json()[
            "project_id"
        ] is None

    async def test_rejects_a_blank_statement(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.post(f"{api}/hypotheses", json={"statement": "  "})
        assert response.status_code == 422


class TestEvidence:
    async def _chunk_id(self, db: AsyncSession) -> str:
        chunk = await db.scalar(select(PaperChunk).order_by(PaperChunk.ordinal))
        assert chunk is not None
        return str(chunk.id)

    async def test_snapshots_the_passage_from_the_database(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        """The client sends only a chunk id. Everything shown comes from the paper itself."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        hypothesis_id = await make_hypothesis(registered_client, api)
        chunk_id = await self._chunk_id(db)

        response = await registered_client.post(
            f"{api}/hypotheses/{hypothesis_id}/evidence",
            json={"chunk_id": chunk_id, "stance": "supports", "reasoning": "Directly measured"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["chunk_id"] == chunk_id
        assert body["paper_title"]
        assert body["locator"]
        assert body["quoted_text"].strip()

        stored = await db.scalar(select(PaperChunk).where(PaperChunk.id == chunk_id))
        assert stored is not None
        assert body["quoted_text"] == stored.content

    async def test_counts_both_sides(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        hypothesis_id = await make_hypothesis(registered_client, api)

        chunks = list(await db.scalars(select(PaperChunk).order_by(PaperChunk.ordinal).limit(3)))
        stances = ["supports", "supports", "contradicts"]
        for chunk, stance in zip(chunks, stances, strict=True):
            await registered_client.post(
                f"{api}/hypotheses/{hypothesis_id}/evidence",
                json={"chunk_id": str(chunk.id), "stance": stance},
            )

        body = (await registered_client.get(f"{api}/hypotheses/{hypothesis_id}")).json()
        assert body["supporting_count"] == 2
        assert body["contradicting_count"] == 1

    async def test_reattaching_a_passage_flips_its_stance(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        """Changing your mind about what a passage shows is normal; duplicating it is not."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        hypothesis_id = await make_hypothesis(registered_client, api)
        chunk_id = await self._chunk_id(db)

        await registered_client.post(
            f"{api}/hypotheses/{hypothesis_id}/evidence",
            json={"chunk_id": chunk_id, "stance": "supports"},
        )
        await registered_client.post(
            f"{api}/hypotheses/{hypothesis_id}/evidence",
            json={"chunk_id": chunk_id, "stance": "contradicts"},
        )

        body = (await registered_client.get(f"{api}/hypotheses/{hypothesis_id}")).json()
        assert len(body["evidence"]) == 1
        assert body["evidence"][0]["stance"] == "contradicts"

    async def test_rejects_a_passage_from_another_users_paper(
        self,
        registered_client: AsyncClient,
        other_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
        db: AsyncSession,
    ) -> None:
        """Otherwise a hypothesis could quote a paper the user has never seen."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        chunk_id = await self._chunk_id(db)

        their_hypothesis = await make_hypothesis(other_client, api)
        response = await other_client.post(
            f"{api}/hypotheses/{their_hypothesis}/evidence",
            json={"chunk_id": chunk_id, "stance": "supports"},
        )

        assert response.status_code == 404
        assert list(await db.scalars(select(Evidence))) == []

    async def test_detaches(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        hypothesis_id = await make_hypothesis(registered_client, api)
        chunk_id = await self._chunk_id(db)
        evidence_id = (
            await registered_client.post(
                f"{api}/hypotheses/{hypothesis_id}/evidence",
                json={"chunk_id": chunk_id, "stance": "supports"},
            )
        ).json()["id"]

        assert (await registered_client.delete(f"{api}/evidence/{evidence_id}")).status_code == 204
        assert (await registered_client.get(f"{api}/hypotheses/{hypothesis_id}")).json()[
            "evidence"
        ] == []


class TestExperiments:
    async def test_keeps_the_expected_result_separate_from_the_actual_one(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Keeping both is the difference between an experiment and a story told afterwards."""
        experiment_id = (
            await registered_client.post(
                f"{api}/experiments",
                json={
                    "title": "Ablate the retriever",
                    "expected_result": "Accuracy drops by roughly ten points.",
                },
            )
        ).json()["id"]

        await registered_client.patch(
            f"{api}/experiments/{experiment_id}",
            json={
                "actual_result": "Accuracy dropped by three points.",
                "interpretation": "Retrieval matters less than assumed at this model size.",
                "status": "complete",
            },
        )

        body = (await registered_client.get(f"{api}/experiments/{experiment_id}")).json()
        assert body["expected_result"] == "Accuracy drops by roughly ten points."
        assert body["actual_result"] == "Accuracy dropped by three points."
        assert body["status"] == "complete"

    async def test_records_the_design(self, registered_client: AsyncClient, api: str) -> None:
        response = await registered_client.post(
            f"{api}/experiments",
            json={
                "title": "Retriever ablation",
                "independent_variables": "Retrieval on or off",
                "dependent_variables": "Exact-match accuracy",
                "controls": "Same prompts, same seeds",
                "confounders": "Retrieved passages may leak answers",
                "metrics": "Exact match, F1",
            },
        )

        body = response.json()
        assert body["confounders"] == "Retrieved passages may leak answers"
        assert body["controls"] == "Same prompts, same seeds"

    async def test_links_to_a_hypothesis(self, registered_client: AsyncClient, api: str) -> None:
        hypothesis_id = await make_hypothesis(registered_client, api)
        body = (
            await registered_client.post(
                f"{api}/experiments",
                json={"title": "A test", "hypothesis_id": hypothesis_id},
            )
        ).json()

        assert body["hypothesis_id"] == hypothesis_id

    async def test_rejects_another_users_hypothesis(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        hypothesis_id = await make_hypothesis(registered_client, api)

        response = await other_client.post(
            f"{api}/experiments", json={"title": "Borrowed", "hypothesis_id": hypothesis_id}
        )
        assert response.status_code == 404


class TestNotes:
    async def test_creates_an_unfiled_note(self, registered_client: AsyncClient, api: str) -> None:
        """A thought arrives before it is clear what it belongs to."""
        response = await registered_client.post(
            f"{api}/notes", json={"content": "The ablation in §4 doesn't control for length."}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["project_id"] is None
        assert body["paper_id"] is None

    async def test_links_to_a_paper_and_project(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        project_id = await make_project(registered_client, api)
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)

        body = (
            await registered_client.post(
                f"{api}/notes",
                json={"content": "Relevant", "project_id": project_id, "paper_id": paper_id},
            )
        ).json()

        assert body["project_id"] == project_id
        assert body["paper_id"] == paper_id

    async def test_filters_by_project(self, registered_client: AsyncClient, api: str) -> None:
        project_id = await make_project(registered_client, api)
        await registered_client.post(
            f"{api}/notes", json={"content": "In project", "project_id": project_id}
        )
        await registered_client.post(f"{api}/notes", json={"content": "Loose thought"})

        filtered = (await registered_client.get(f"{api}/notes?project_id={project_id}")).json()
        assert [note["content"] for note in filtered] == ["In project"]

    async def test_searches_title_and_body(self, registered_client: AsyncClient, api: str) -> None:
        await registered_client.post(
            f"{api}/notes", json={"title": "Ablation", "content": "Length is a confound."}
        )
        await registered_client.post(f"{api}/notes", json={"content": "Unrelated musing."})

        assert len((await registered_client.get(f"{api}/notes?search=confound")).json()) == 1
        assert len((await registered_client.get(f"{api}/notes?search=Ablation")).json()) == 1

    async def test_deleting_a_project_keeps_its_notes(
        self, registered_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        """Notes are the user's own words. Losing them to a filing change would be data loss."""
        project_id = await make_project(registered_client, api)
        await registered_client.post(
            f"{api}/notes", json={"content": "Still worth keeping", "project_id": project_id}
        )

        await registered_client.delete(f"{api}/projects/{project_id}")

        notes = list(await db.scalars(select(Note)))
        assert len(notes) == 1
        assert notes[0].project_id is None

    async def test_another_user_cannot_read_a_note(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        note_id = (
            await registered_client.post(f"{api}/notes", json={"content": "Private thought"})
        ).json()["id"]

        assert (await other_client.get(f"{api}/notes/{note_id}")).status_code == 404
        assert (await other_client.get(f"{api}/notes")).json() == []


class TestTasks:
    async def test_appends_in_order(self, registered_client: AsyncClient, api: str) -> None:
        project_id = await make_project(registered_client, api)
        for title in ["Read the RAG paper", "Reproduce the baseline", "Write the ablation"]:
            await registered_client.post(
                f"{api}/projects/{project_id}/tasks", json={"title": title}
            )

        tasks = (await registered_client.get(f"{api}/projects/{project_id}/tasks")).json()
        assert [task["title"] for task in tasks] == [
            "Read the RAG paper",
            "Reproduce the baseline",
            "Write the ablation",
        ]

    async def test_completing_a_task_clears_it_from_the_open_count(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        project_id = await make_project(registered_client, api)
        task_id = (
            await registered_client.post(
                f"{api}/projects/{project_id}/tasks", json={"title": "Read"}
            )
        ).json()["id"]

        await registered_client.patch(f"{api}/tasks/{task_id}", json={"status": "done"})

        body = (await registered_client.get(f"{api}/projects/{project_id}")).json()
        assert body["open_task_count"] == 0

    async def test_another_user_cannot_add_a_task(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        project_id = await make_project(registered_client, api)

        response = await other_client.post(
            f"{api}/projects/{project_id}/tasks", json={"title": "Injected"}
        )
        assert response.status_code == 404


class TestWorkspacePrivacy:
    async def test_lists_are_scoped_to_the_caller(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        await make_project(registered_client, api)
        await make_hypothesis(registered_client, api)
        await registered_client.post(f"{api}/experiments", json={"title": "Mine"})
        await registered_client.post(f"{api}/notes", json={"content": "Mine"})

        assert (await other_client.get(f"{api}/projects")).json() == []
        assert (await other_client.get(f"{api}/hypotheses")).json() == []
        assert (await other_client.get(f"{api}/experiments")).json() == []
        assert (await other_client.get(f"{api}/notes")).json() == []

        # The rows exist — they are simply invisible to the other account.
        assert len(list(await db.scalars(select(Project)))) == 1


class TestEveryUpdateEndpointWorks:
    """Editing was untested on two resources, and broken on exactly those two.

    `updated_at` used a server-side `onupdate`, so SQLAlchemy expired the attribute after each
    UPDATE and re-read it during response serialisation — IO in a sync context, raising
    MissingGreenlet. It surfaced only where the response included that column, which is why
    nothing caught it: the endpoints that were tested did not serialise it.

    These cover the whole surface rather than one resource, because the fault was in shared
    code and a single test would have proved only that one endpoint escaped it.
    """

    async def test_a_project_can_be_edited(self, registered_client: AsyncClient, api: str) -> None:
        project = (
            await registered_client.post(
                f"{api}/projects", json={"name": "Before", "research_question": "q"}
            )
        ).json()

        response = await registered_client.patch(
            f"{api}/projects/{project['id']}", json={"name": "After", "status": "paused"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "After"
        assert response.json()["status"] == "paused"

    async def test_editing_a_project_moves_its_updated_timestamp(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """The column that caused the bug, asserted directly."""
        project = (
            await registered_client.post(
                f"{api}/projects", json={"name": "Timestamps", "research_question": "q"}
            )
        ).json()

        edited = (
            await registered_client.patch(
                f"{api}/projects/{project['id']}", json={"name": "Edited"}
            )
        ).json()

        assert edited["updated_at"] >= project["updated_at"]

    async def test_a_note_can_be_edited(self, registered_client: AsyncClient, api: str) -> None:
        note = (await registered_client.post(f"{api}/notes", json={"content": "draft"})).json()

        response = await registered_client.patch(
            f"{api}/notes/{note['id']}", json={"content": "revised"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["content"] == "revised"

    async def test_an_explicit_null_is_refused_where_the_column_cannot_be_null(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """`exclude_unset` separates omitted from sent, but null counts as sent — and reached
        a NOT NULL column as a 500."""
        project = (
            await registered_client.post(
                f"{api}/projects", json={"name": "Nulls", "research_question": "q"}
            )
        ).json()

        for field in ("name", "status"):
            response = await registered_client.patch(
                f"{api}/projects/{project['id']}", json={field: None}
            )
            assert response.status_code == 422, f"{field}=null gave {response.status_code}"

    async def test_an_explicit_null_still_clears_a_nullable_column(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """The other half: refusing every null would break clearing an optional field."""
        project = (
            await registered_client.post(
                f"{api}/projects",
                json={"name": "Nullable", "research_question": "q", "description": "set"},
            )
        ).json()

        response = await registered_client.patch(
            f"{api}/projects/{project['id']}", json={"description": None}
        )

        assert response.status_code == 200, response.text
        assert response.json()["description"] is None
