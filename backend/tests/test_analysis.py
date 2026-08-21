"""Analyses: the computational half of a project.

The server does not execute anything here — code runs in the reader's browser and only text
comes back — so what is worth testing is not "does Python work" but the three things the
server is actually responsible for: that a notebook stays in order, that one account cannot
touch another's, and that an output never survives beside code that no longer produces it.

That last one is the rule with teeth. A number sitting under code that has since changed looks
checked and is not, which is how a wrong figure reaches a write-up.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.models.analysis import CellKind, CellStatus
from atlas.models.user import User
from atlas.services.analysis_service import (
    MAX_OUTPUT_CHARS,
    AnalysisService,
    CellResult,
)


@pytest.fixture
async def service(db: AsyncSession) -> AnalysisService:
    return AnalysisService(db)


@pytest.fixture
async def owner(db: AsyncSession) -> User:
    user = User(
        email="analyst@atlas.dev",
        full_name="Analyst",
        password_hash="not-a-real-hash",
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def stranger(db: AsyncSession) -> User:
    user = User(
        email="stranger@atlas.dev",
        full_name="Stranger",
        password_hash="not-a-real-hash",
    )
    db.add(user)
    await db.flush()
    return user


class TestNotebookShape:
    async def test_a_new_analysis_has_somewhere_to_type(
        self, service: AnalysisService, owner: User
    ) -> None:
        """An empty notebook has no cell to click into, which is a dead end on arrival."""
        analysis = await service.create(owner_id=owner.id, title="First", starter="print(1)")
        assert len(analysis.cells) == 1
        assert analysis.cells[0].source == "print(1)"
        assert analysis.cells[0].status is CellStatus.idle

    async def test_cells_append_in_order(self, service: AnalysisService, owner: User) -> None:
        analysis = await service.create(owner_id=owner.id, title="Ordered")
        for _ in range(3):
            await service.add_cell(owner_id=owner.id, analysis_id=analysis.id)

        reloaded = await service.get(owner.id, analysis.id)
        assert [cell.ordinal for cell in reloaded.cells] == [0, 1, 2, 3]

    async def test_a_cell_can_be_inserted_below_another(
        self, service: AnalysisService, owner: User
    ) -> None:
        """Order is meaning: cells share one interpreter and run top to bottom."""
        analysis = await service.create(owner_id=owner.id, title="Insert")
        first = analysis.cells[0]
        last = await service.add_cell(owner_id=owner.id, analysis_id=analysis.id, source="last")
        middle = await service.add_cell(
            owner_id=owner.id, analysis_id=analysis.id, source="middle", after=first.id
        )

        reloaded = await service.get(owner.id, analysis.id)
        ordered = [cell.id for cell in sorted(reloaded.cells, key=lambda c: c.ordinal)]
        assert ordered == [first.id, middle.id, last.id]

    async def test_moving_a_cell_swaps_it_with_its_neighbour(
        self, service: AnalysisService, owner: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Move")
        first = analysis.cells[0]
        second = await service.add_cell(owner_id=owner.id, analysis_id=analysis.id, source="two")

        await service.move_cell(
            owner_id=owner.id, analysis_id=analysis.id, cell_id=second.id, offset=-1
        )
        reloaded = await service.get(owner.id, analysis.id)
        ordered = [cell.id for cell in sorted(reloaded.cells, key=lambda c: c.ordinal)]
        assert ordered == [second.id, first.id]

    async def test_moving_past_the_end_does_nothing_rather_than_failing(
        self, service: AnalysisService, owner: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Edge")
        await service.move_cell(
            owner_id=owner.id,
            analysis_id=analysis.id,
            cell_id=analysis.cells[0].id,
            offset=-1,
        )
        assert (await service.get(owner.id, analysis.id)).cells[0].ordinal == 0

    async def test_deleting_a_cell_closes_the_gap_it_leaves(
        self, service: AnalysisService, owner: User
    ) -> None:
        """A hole in the ordering makes the next insert land in the wrong place."""
        analysis = await service.create(owner_id=owner.id, title="Delete")
        middle = await service.add_cell(owner_id=owner.id, analysis_id=analysis.id)
        await service.add_cell(owner_id=owner.id, analysis_id=analysis.id)

        await service.delete_cell(owner_id=owner.id, analysis_id=analysis.id, cell_id=middle.id)
        reloaded = await service.get(owner.id, analysis.id)
        assert sorted(cell.ordinal for cell in reloaded.cells) == [0, 1]

    async def test_the_last_cell_cannot_be_deleted(
        self, service: AnalysisService, owner: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Only")
        with pytest.raises(Exception, match="at least one cell"):
            await service.delete_cell(
                owner_id=owner.id, analysis_id=analysis.id, cell_id=analysis.cells[0].id
            )


class TestOutputsNeverOutliveTheirCode:
    async def test_editing_a_cell_that_ran_marks_it_stale(
        self, service: AnalysisService, owner: User
    ) -> None:
        """The rule this whole model exists for."""
        analysis = await service.create(owner_id=owner.id, title="Stale", starter="1 + 1")
        cell = analysis.cells[0]

        await service.record_run(
            owner_id=owner.id,
            analysis_id=analysis.id,
            cell_id=cell.id,
            result=CellResult(output="2", duration_ms=3),
        )
        assert cell.status is CellStatus.ok

        await service.save_source(
            owner_id=owner.id, analysis_id=analysis.id, cell_id=cell.id, source="1 + 2"
        )
        assert cell.status is CellStatus.stale
        assert cell.output == "2", "the old output is kept, but no longer presented as current"

    async def test_saving_identical_source_does_not_mark_it_stale(
        self, service: AnalysisService, owner: User
    ) -> None:
        """Autosave fires on a pause, not only on a change; a no-op save must be a no-op."""
        analysis = await service.create(owner_id=owner.id, title="Same", starter="x = 1")
        cell = analysis.cells[0]
        await service.record_run(
            owner_id=owner.id, analysis_id=analysis.id, cell_id=cell.id, result=CellResult("done")
        )

        await service.save_source(
            owner_id=owner.id, analysis_id=analysis.id, cell_id=cell.id, source="x = 1"
        )
        assert cell.status is CellStatus.ok

    async def test_editing_a_cell_that_never_ran_stays_idle(
        self, service: AnalysisService, owner: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Fresh")
        cell = await service.save_source(
            owner_id=owner.id,
            analysis_id=analysis.id,
            cell_id=analysis.cells[0].id,
            source="anything",
        )
        assert cell.status is CellStatus.idle

    async def test_a_failed_run_is_recorded_as_an_error_with_its_traceback(
        self, service: AnalysisService, owner: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Boom", starter="1/0")
        cell = await service.record_run(
            owner_id=owner.id,
            analysis_id=analysis.id,
            cell_id=analysis.cells[0].id,
            result=CellResult(error="ZeroDivisionError: division by zero"),
        )
        assert cell.status is CellStatus.error
        assert "ZeroDivisionError" in (cell.error or "")

    async def test_runaway_output_is_truncated_rather_than_refused(
        self, service: AnalysisService, owner: User
    ) -> None:
        """A loop printing in error is a mistake worth seeing the start of. Rejecting the write
        would lose the traceback that explains it."""
        analysis = await service.create(owner_id=owner.id, title="Loud")
        cell = await service.record_run(
            owner_id=owner.id,
            analysis_id=analysis.id,
            cell_id=analysis.cells[0].id,
            result=CellResult(output="x" * (MAX_OUTPUT_CHARS + 5_000)),
        )
        assert cell.output is not None
        assert len(cell.output) < MAX_OUTPUT_CHARS + 200
        assert "truncated" in cell.output

    async def test_a_run_stamps_the_analysis(self, service: AnalysisService, owner: User) -> None:
        """Reaching the parent through `cell.analysis` triggered a lazy load during response
        handling, where there is no greenlet to await on — every run came back a 500."""
        analysis = await service.create(owner_id=owner.id, title="Stamped")
        await service.record_run(
            owner_id=owner.id,
            analysis_id=analysis.id,
            cell_id=analysis.cells[0].id,
            result=CellResult(output="ok"),
        )
        assert (await service.get(owner.id, analysis.id)).last_run_at is not None


class TestOwnership:
    async def test_one_account_cannot_read_anothers_analysis(
        self, service: AnalysisService, owner: User, stranger: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Private")
        with pytest.raises(Exception, match="isn't in your workspace"):
            await service.get(stranger.id, analysis.id)

    async def test_one_account_cannot_write_to_anothers_cell(
        self, service: AnalysisService, owner: User, stranger: User
    ) -> None:
        analysis = await service.create(owner_id=owner.id, title="Private")
        with pytest.raises(Exception, match="isn't in your workspace"):
            await service.save_source(
                owner_id=stranger.id,
                analysis_id=analysis.id,
                cell_id=analysis.cells[0].id,
                source="mine now",
            )

    async def test_an_analysis_cannot_be_attached_to_someone_elses_project(
        self, service: AnalysisService, owner: User, stranger: User, db: AsyncSession
    ) -> None:
        """A foreign key alone is enough to make your notebook appear in their workspace."""
        from atlas.models.workspace import Project

        theirs = Project(owner_id=stranger.id, name="Theirs", research_question="?")
        db.add(theirs)
        await db.flush()

        with pytest.raises(Exception, match="isn't in your workspace"):
            await service.create(owner_id=owner.id, title="Sneaky", project_id=theirs.id)

    async def test_listing_shows_only_your_own(
        self, service: AnalysisService, owner: User, stranger: User
    ) -> None:
        await service.create(owner_id=owner.id, title="Mine")
        await service.create(owner_id=stranger.id, title="Theirs")

        assert [a.title for a in await service.list_for(owner.id)] == ["Mine"]
        assert [a.title for a in await service.list_for(stranger.id)] == ["Theirs"]


class TestRoutes:
    async def test_the_whole_cycle_over_http(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        created = await registered_client.post(f"{api}/analyses", json={"title": "End to end"})
        assert created.status_code == 201
        analysis = created.json()
        cell_id = analysis["cells"][0]["id"]
        assert analysis["cells"][0]["source"], "the starter cell is something you can press play on"

        ran = await registered_client.post(
            f"{api}/analyses/{analysis['id']}/cells/{cell_id}/run",
            json={"output": "mean 5.0", "duration_ms": 12},
        )
        assert ran.status_code == 200
        assert ran.json()["status"] == "ok"

        edited = await registered_client.put(
            f"{api}/analyses/{analysis['id']}/cells/{cell_id}",
            json={"source": "something else"},
        )
        assert edited.json()["status"] == "stale"

    async def test_another_account_gets_404_not_403(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        """403 would confirm the id belongs to somebody."""
        created = await registered_client.post(f"{api}/analyses", json={"title": "Private"})
        analysis_id = created.json()["id"]

        assert (await other_client.get(f"{api}/analyses/{analysis_id}")).status_code == 404

    async def test_an_unknown_analysis_is_a_404(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        assert (await registered_client.get(f"{api}/analyses/{uuid.uuid4()}")).status_code == 404

    async def test_a_markdown_cell_can_be_added(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        created = await registered_client.post(f"{api}/analyses", json={"title": "Mixed"})
        added = await registered_client.post(
            f"{api}/analyses/{created.json()['id']}/cells",
            json={"kind": "markdown", "source": "## Results"},
        )
        assert added.status_code == 201
        assert added.json()["kind"] == CellKind.markdown.value
