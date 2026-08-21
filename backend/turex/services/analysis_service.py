"""Storing analyses and their cells.

Deliberately dull. The interesting half of this feature runs in a browser; the server's job is
to hold text, keep it owner-scoped, and keep the cells in order.

The one rule with teeth: **a cell whose source has changed since it ran is marked stale.** A
notebook that shows an output next to code that no longer produces it is worse than one that
shows nothing, because the number looks checked. Saving source is the only place that can
notice, so it is the place that does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from turex.core.errors import NotFoundError, ValidationError
from turex.core.logging import get_logger
from turex.models.analysis import Analysis, AnalysisCell, CellKind, CellStatus
from turex.models.workspace import Experiment, Project

logger = get_logger(__name__)

MAX_CELLS = 200
"""Cells per analysis.

Not a technical limit — a bound on the damage a runaway client can do to one row set. Two
hundred is more than any notebook that stays readable.
"""

MAX_SOURCE_CHARS = 100_000
MAX_OUTPUT_CHARS = 200_000
"""Output is allowed to be larger than source, because a loop printing in error produces a lot
of it and truncating to something *smaller than the code* would hide the mistake being made.
"""

MAX_IMAGE_CHARS = 4_000_000
"""A base64 PNG. Roughly a 3MB image, which is a generous matplotlib figure."""


@dataclass(frozen=True, slots=True)
class CellResult:
    """What a browser reports after running a cell."""

    output: str | None = None
    image: str | None = None
    error: str | None = None
    duration_ms: int | None = None


class AnalysisService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _owned(self, owner_id: uuid.UUID, analysis_id: uuid.UUID) -> Analysis:
        """Load an analysis with its cells, or refuse.

        Scoped by owner in the query rather than checked afterwards: a 404 for someone else's
        analysis and a 404 for one that does not exist are the same answer, which is what
        stops the endpoint confirming that an id belongs to somebody.
        """
        found = await self._db.scalar(
            select(Analysis)
            .where(Analysis.id == analysis_id, Analysis.owner_id == owner_id)
            .options(selectinload(Analysis.cells))
        )
        if found is None:
            raise NotFoundError("That analysis isn't in your workspace.")
        return found

    async def list_for(
        self, owner_id: uuid.UUID, *, project_id: uuid.UUID | None = None
    ) -> list[Analysis]:
        statement = (
            select(Analysis)
            .where(Analysis.owner_id == owner_id)
            .options(selectinload(Analysis.cells))
            .order_by(Analysis.created_at.desc())
        )
        if project_id is not None:
            statement = statement.where(Analysis.project_id == project_id)
        return list((await self._db.execute(statement)).scalars().all())

    async def get(self, owner_id: uuid.UUID, analysis_id: uuid.UUID) -> Analysis:
        return await self._owned(owner_id, analysis_id)

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        title: str,
        description: str | None = None,
        project_id: uuid.UUID | None = None,
        experiment_id: uuid.UUID | None = None,
        starter: str | None = None,
    ) -> Analysis:
        """Create an analysis, optionally attached to a project or experiment.

        The project and experiment are verified to belong to the caller. Without that, a
        foreign key is enough to attach your notebook to somebody else's project — the row
        would be yours, but it would appear in their workspace.
        """
        if project_id is not None:
            await self._require_owned(Project, project_id, owner_id, "project")
        if experiment_id is not None:
            await self._require_owned(Experiment, experiment_id, owner_id, "experiment")

        analysis = Analysis(
            owner_id=owner_id,
            title=title[:300],
            description=description,
            project_id=project_id,
            experiment_id=experiment_id,
        )
        # One cell to start, because an empty notebook has nowhere to type.
        analysis.cells = [
            AnalysisCell(
                ordinal=0, kind=CellKind.code, source=starter or "", status=CellStatus.idle
            )
        ]
        self._db.add(analysis)
        await self._db.flush()
        return analysis

    async def _require_owned(
        self,
        model: type[Project] | type[Experiment],
        row_id: uuid.UUID,
        owner_id: uuid.UUID,
        label: str,
    ) -> None:
        found = await self._db.scalar(
            select(model.id).where(model.id == row_id, model.owner_id == owner_id)
        )
        if found is None:
            raise NotFoundError(f"That {label} isn't in your workspace.")

    async def update(
        self,
        *,
        owner_id: uuid.UUID,
        analysis_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
    ) -> Analysis:
        analysis = await self._owned(owner_id, analysis_id)
        if title is not None:
            analysis.title = title[:300]
        if description is not None:
            analysis.description = description
        await self._db.flush()
        return analysis

    async def delete(self, owner_id: uuid.UUID, analysis_id: uuid.UUID) -> None:
        analysis = await self._owned(owner_id, analysis_id)
        await self._db.delete(analysis)
        await self._db.flush()

    async def add_cell(
        self,
        *,
        owner_id: uuid.UUID,
        analysis_id: uuid.UUID,
        kind: CellKind = CellKind.code,
        source: str = "",
        after: uuid.UUID | None = None,
    ) -> AnalysisCell:
        """Append a cell, or insert one directly below another.

        Inserting renumbers the cells below it. That is a write per cell rather than a clever
        sparse ordering, and it is the right trade at this size: a notebook has tens of cells,
        the renumber is one statement, and gap-based ordering eventually needs a rebalance
        anyway — at which point it is this, only later and by surprise.
        """
        analysis = await self._owned(owner_id, analysis_id)

        if len(analysis.cells) >= MAX_CELLS:
            raise ValidationError(f"An analysis holds at most {MAX_CELLS} cells.")

        position = len(analysis.cells)
        if after is not None:
            existing = {cell.id: cell for cell in analysis.cells}
            if after not in existing:
                raise NotFoundError("That cell isn't in this analysis.")
            position = existing[after].ordinal + 1
            for cell in analysis.cells:
                if cell.ordinal >= position:
                    cell.ordinal += 1

        cell = AnalysisCell(
            ordinal=position,
            kind=kind,
            source=source[:MAX_SOURCE_CHARS],
            status=CellStatus.idle,
        )
        # Appended to the relationship rather than added as a detached row with the id set.
        # Both write the same row, but only this keeps `analysis.cells` correct in memory —
        # and `position` is computed from `len(analysis.cells)`, so a stale collection means
        # the next cell is given an ordinal that is already taken.
        analysis.cells.append(cell)
        await self._db.flush()
        return cell

    async def _cell(
        self, owner_id: uuid.UUID, analysis_id: uuid.UUID, cell_id: uuid.UUID
    ) -> tuple[Analysis, AnalysisCell]:
        """Both, because the caller usually needs the parent too.

        Returning only the cell meant reaching back through `cell.analysis` to stamp the run
        time, and that relationship is not loaded — so the attribute access issued a query
        from inside response handling, where there is no greenlet to await on, and every run
        came back as a 500. The analysis is already in hand here; handing it over costs
        nothing and removes the lazy load entirely.
        """
        analysis = await self._owned(owner_id, analysis_id)
        for cell in analysis.cells:
            if cell.id == cell_id:
                return analysis, cell
        raise NotFoundError("That cell isn't in this analysis.")

    async def save_source(
        self,
        *,
        owner_id: uuid.UUID,
        analysis_id: uuid.UUID,
        cell_id: uuid.UUID,
        source: str,
        kind: CellKind | None = None,
    ) -> AnalysisCell:
        """Save what someone typed, and mark the cell stale if it had already run.

        This is the rule the whole model exists to enforce. An output beside code that no
        longer produces it is a wrong number that looks checked, and editing is the moment it
        becomes wrong.
        """
        _, cell = await self._cell(owner_id, analysis_id, cell_id)
        changed = cell.source != source

        cell.source = source[:MAX_SOURCE_CHARS]
        if kind is not None:
            cell.kind = kind
        if changed and cell.status in (CellStatus.ok, CellStatus.error):
            cell.status = CellStatus.stale

        await self._db.flush()
        return cell

    async def record_run(
        self,
        *,
        owner_id: uuid.UUID,
        analysis_id: uuid.UUID,
        cell_id: uuid.UUID,
        result: CellResult,
    ) -> AnalysisCell:
        """Store what a cell produced when the browser ran it.

        Truncated rather than refused. A cell that printed a million lines is a mistake worth
        seeing the beginning of; rejecting the write would lose the traceback that explains it.
        """
        analysis, cell = await self._cell(owner_id, analysis_id, cell_id)

        cell.output = _clip(result.output, MAX_OUTPUT_CHARS)
        cell.image = _clip(result.image, MAX_IMAGE_CHARS, note=False)
        cell.error = _clip(result.error, MAX_OUTPUT_CHARS)
        cell.duration_ms = result.duration_ms
        cell.status = CellStatus.error if result.error else CellStatus.ok
        cell.executed_at = datetime.now(UTC)

        analysis.last_run_at = cell.executed_at
        await self._db.flush()
        return cell

    async def delete_cell(
        self, *, owner_id: uuid.UUID, analysis_id: uuid.UUID, cell_id: uuid.UUID
    ) -> None:
        """Remove a cell, closing the gap it leaves in the ordering."""
        analysis = await self._owned(owner_id, analysis_id)
        if len(analysis.cells) <= 1:
            raise ValidationError("An analysis keeps at least one cell.")

        target = next((cell for cell in analysis.cells if cell.id == cell_id), None)
        if target is None:
            raise NotFoundError("That cell isn't in this analysis.")

        removed = target.ordinal
        # Removed through the relationship so the loaded collection stays true; `delete-orphan`
        # on the relationship issues the DELETE. A bare `delete()` statement would remove the
        # row while leaving it in `analysis.cells`, and the renumbering below reads that list.
        analysis.cells.remove(target)
        for cell in analysis.cells:
            if cell.ordinal > removed:
                cell.ordinal -= 1
        await self._db.flush()

    async def move_cell(
        self, *, owner_id: uuid.UUID, analysis_id: uuid.UUID, cell_id: uuid.UUID, offset: int
    ) -> Analysis:
        """Swap a cell with its neighbour.

        Order is meaning in a notebook: cells share one interpreter and run top to bottom, so
        moving one changes what the ones after it see.
        """
        analysis = await self._owned(owner_id, analysis_id)
        by_ordinal = sorted(analysis.cells, key=lambda cell: cell.ordinal)

        index = next((i for i, cell in enumerate(by_ordinal) if cell.id == cell_id), None)
        if index is None:
            raise NotFoundError("That cell isn't in this analysis.")

        target = index + offset
        if not 0 <= target < len(by_ordinal):
            return analysis  # Already at the end; not an error, just nothing to do.

        by_ordinal[index].ordinal, by_ordinal[target].ordinal = (
            by_ordinal[target].ordinal,
            by_ordinal[index].ordinal,
        )
        await self._db.flush()
        return analysis

    async def count_for(self, owner_id: uuid.UUID) -> int:
        return int(
            await self._db.scalar(
                select(func.count()).select_from(Analysis).where(Analysis.owner_id == owner_id)
            )
            or 0
        )


def _clip(value: str | None, limit: int, *, note: bool = True) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    if not note:
        return None  # An image cut in half is not an image; better to store none.
    return value[:limit] + f"\n… truncated at {limit:,} characters"
