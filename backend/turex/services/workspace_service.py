"""Project, hypothesis, experiment, note, and task logic.

Every method is owner-scoped in its query, the same rule as everywhere else in Turex: a
resource belonging to another account is indistinguishable from one that does not exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from turex.core.errors import NotFoundError, ValidationError
from turex.core.logging import get_logger
from turex.models.paper import Paper, PaperChunk, PaperSection
from turex.models.user import User
from turex.models.workspace import (
    Evidence,
    EvidenceStance,
    Experiment,
    Hypothesis,
    Note,
    Project,
    ProjectPaper,
    Task,
)

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    """A project plus the counts its card and header show, gathered in one pass."""

    project: Project
    paper_count: int
    hypothesis_count: int
    experiment_count: int
    note_count: int
    open_task_count: int


class WorkspaceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # -- helpers ------------------------------------------------------------------

    async def _owned(self, model: type[T], owner: User, entity_id: uuid.UUID, label: str) -> T:
        statement: Select[Any] = select(model).where(
            model.id == entity_id,  # type: ignore[attr-defined]
            model.owner_id == owner.id,  # type: ignore[attr-defined]
        )
        entity = await self._db.scalar(statement)
        if entity is None:
            raise NotFoundError(f"We couldn't find that {label}.")
        return entity

    # -- projects -----------------------------------------------------------------

    def _overview_statement(self) -> Select[Any]:
        """Project rows with their counts.

        Correlated subqueries rather than a per-project fan-out: a workspace with twenty
        projects should cost one query to render, not eighty.
        """
        papers = (
            select(func.count())
            .select_from(ProjectPaper)
            .where(ProjectPaper.project_id == Project.id)
            .scalar_subquery()
        )
        hypotheses = (
            select(func.count())
            .select_from(Hypothesis)
            .where(Hypothesis.project_id == Project.id)
            .scalar_subquery()
        )
        experiments = (
            select(func.count())
            .select_from(Experiment)
            .where(Experiment.project_id == Project.id)
            .scalar_subquery()
        )
        notes = (
            select(func.count())
            .select_from(Note)
            .where(Note.project_id == Project.id)
            .scalar_subquery()
        )
        open_tasks = (
            select(func.count())
            .select_from(Task)
            .where(Task.project_id == Project.id, Task.status != "done")
            .scalar_subquery()
        )

        return select(Project, papers, hypotheses, experiments, notes, open_tasks)

    @staticmethod
    def _to_overview(row: Any) -> ProjectOverview:
        project, papers, hypotheses, experiments, notes, open_tasks = row
        return ProjectOverview(
            project=project,
            paper_count=papers,
            hypothesis_count=hypotheses,
            experiment_count=experiments,
            note_count=notes,
            open_task_count=open_tasks,
        )

    async def list_projects(self, *, owner: User) -> list[ProjectOverview]:
        rows = await self._db.execute(
            self._overview_statement()
            .where(Project.owner_id == owner.id)
            .order_by(Project.updated_at.desc())
        )
        return [self._to_overview(row) for row in rows]

    async def project_overview(self, *, owner: User, project_id: uuid.UUID) -> ProjectOverview:
        row = (
            await self._db.execute(
                self._overview_statement().where(
                    Project.id == project_id, Project.owner_id == owner.id
                )
            )
        ).first()
        if row is None:
            raise NotFoundError("We couldn't find that project.")
        return self._to_overview(row)

    async def get_project(self, *, owner: User, project_id: uuid.UUID) -> Project:
        return await self._owned(Project, owner, project_id, "project")

    async def create_project(self, *, owner: User, **fields: Any) -> Project:
        project = Project(owner_id=owner.id, **fields)
        self._db.add(project)
        await self._db.flush()
        logger.info("project created", extra={"project_id": str(project.id)})
        return project

    async def update_project(
        self, *, owner: User, project_id: uuid.UUID, changes: dict[str, Any]
    ) -> Project:
        project = await self.get_project(owner=owner, project_id=project_id)
        for field, value in changes.items():
            setattr(project, field, value)
        await self._db.flush()
        return project

    async def delete_project(self, *, owner: User, project_id: uuid.UUID) -> None:
        project = await self.get_project(owner=owner, project_id=project_id)
        await self._db.delete(project)

    async def project_papers(
        self, *, owner: User, project_id: uuid.UUID
    ) -> list[tuple[Paper, str | None]]:
        await self.get_project(owner=owner, project_id=project_id)
        rows = await self._db.execute(
            select(Paper, ProjectPaper.relevance_note)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(Paper.created_at.desc())
        )
        return [(paper, note) for paper, note in rows]

    async def add_paper(
        self,
        *,
        owner: User,
        project_id: uuid.UUID,
        paper_id: uuid.UUID,
        relevance_note: str | None = None,
    ) -> None:
        await self.get_project(owner=owner, project_id=project_id)
        paper = await self._db.scalar(
            select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner.id)
        )
        if paper is None:
            raise NotFoundError("We couldn't find that paper.")

        existing = await self._db.get(ProjectPaper, (project_id, paper_id))
        if existing is None:
            self._db.add(
                ProjectPaper(
                    project_id=project_id, paper_id=paper_id, relevance_note=relevance_note
                )
            )
        elif relevance_note is not None:
            existing.relevance_note = relevance_note
        await self._db.flush()

    async def remove_paper(
        self, *, owner: User, project_id: uuid.UUID, paper_id: uuid.UUID
    ) -> None:
        await self.get_project(owner=owner, project_id=project_id)
        await self._db.execute(
            delete(ProjectPaper).where(
                ProjectPaper.project_id == project_id, ProjectPaper.paper_id == paper_id
            )
        )

    # -- hypotheses ---------------------------------------------------------------

    async def list_hypotheses(
        self, *, owner: User, project_id: uuid.UUID | None = None
    ) -> list[Hypothesis]:
        statement = select(Hypothesis).where(Hypothesis.owner_id == owner.id)
        if project_id is not None:
            statement = statement.where(Hypothesis.project_id == project_id)
        rows = await self._db.scalars(
            statement.order_by(Hypothesis.position, Hypothesis.created_at)
        )
        return list(rows)

    async def get_hypothesis(self, *, owner: User, hypothesis_id: uuid.UUID) -> Hypothesis:
        return await self._owned(Hypothesis, owner, hypothesis_id, "hypothesis")

    async def create_hypothesis(self, *, owner: User, **fields: Any) -> Hypothesis:
        if project_id := fields.get("project_id"):
            await self.get_project(owner=owner, project_id=project_id)
        hypothesis = Hypothesis(owner_id=owner.id, **fields)
        self._db.add(hypothesis)
        await self._db.flush()
        return hypothesis

    async def update_hypothesis(
        self, *, owner: User, hypothesis_id: uuid.UUID, changes: dict[str, Any]
    ) -> Hypothesis:
        hypothesis = await self.get_hypothesis(owner=owner, hypothesis_id=hypothesis_id)
        for field, value in changes.items():
            setattr(hypothesis, field, value)
        await self._db.flush()
        return hypothesis

    async def delete_hypothesis(self, *, owner: User, hypothesis_id: uuid.UUID) -> None:
        hypothesis = await self.get_hypothesis(owner=owner, hypothesis_id=hypothesis_id)
        await self._db.delete(hypothesis)

    async def evidence_for(self, *, owner: User, hypothesis_id: uuid.UUID) -> list[Evidence]:
        await self.get_hypothesis(owner=owner, hypothesis_id=hypothesis_id)
        rows = await self._db.scalars(
            select(Evidence)
            .where(Evidence.hypothesis_id == hypothesis_id)
            .order_by(Evidence.stance, Evidence.created_at)
        )
        return list(rows)

    async def attach_evidence(
        self,
        *,
        owner: User,
        hypothesis_id: uuid.UUID,
        chunk_id: uuid.UUID,
        stance: EvidenceStance,
        reasoning: str | None,
    ) -> Evidence:
        """Link a passage to a hypothesis, for or against.

        The passage is looked up and snapshotted here rather than being sent by the client:
        a client-supplied quotation could say anything, and evidence has to be evidence.
        """
        await self.get_hypothesis(owner=owner, hypothesis_id=hypothesis_id)

        row = (
            await self._db.execute(
                select(PaperChunk, Paper, PaperSection.title)
                .join(Paper, Paper.id == PaperChunk.paper_id)
                .outerjoin(PaperSection, PaperSection.id == PaperChunk.section_id)
                .where(PaperChunk.id == chunk_id, Paper.owner_id == owner.id)
            )
        ).first()
        if row is None:
            raise NotFoundError("We couldn't find that passage.")

        chunk, paper, section_title = row

        duplicate = await self._db.scalar(
            select(Evidence).where(
                Evidence.hypothesis_id == hypothesis_id, Evidence.chunk_id == chunk_id
            )
        )
        if duplicate is not None:
            # Re-attaching the same passage flips its stance rather than duplicating it —
            # changing your mind about what a passage shows is a normal part of research.
            duplicate.stance = stance
            if reasoning is not None:
                duplicate.reasoning = reasoning
            await self._db.flush()
            return duplicate

        evidence = Evidence(
            hypothesis_id=hypothesis_id,
            chunk_id=chunk.id,
            paper_id=paper.id,
            stance=stance,
            paper_title=paper.display_title,
            locator=_locator(chunk, section_title)[:200],
            quoted_text=chunk.content,
            reasoning=reasoning,
        )
        self._db.add(evidence)
        await self._db.flush()
        return evidence

    async def detach_evidence(self, *, owner: User, evidence_id: uuid.UUID) -> None:
        row = (
            await self._db.execute(
                select(Evidence)
                .join(Hypothesis, Hypothesis.id == Evidence.hypothesis_id)
                .where(Evidence.id == evidence_id, Hypothesis.owner_id == owner.id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("We couldn't find that evidence.")
        await self._db.delete(row)

    async def evidence_counts(
        self, hypothesis_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """(supporting, contradicting) per hypothesis, in one query."""
        if not hypothesis_ids:
            return {}

        rows = await self._db.execute(
            select(
                Evidence.hypothesis_id,
                func.count().filter(Evidence.stance == EvidenceStance.supports),
                func.count().filter(Evidence.stance == EvidenceStance.contradicts),
            )
            .where(Evidence.hypothesis_id.in_(hypothesis_ids))
            .group_by(Evidence.hypothesis_id)
        )
        return {row[0]: (row[1], row[2]) for row in rows}

    # -- experiments --------------------------------------------------------------

    async def list_experiments(
        self, *, owner: User, project_id: uuid.UUID | None = None
    ) -> list[Experiment]:
        statement = select(Experiment).where(Experiment.owner_id == owner.id)
        if project_id is not None:
            statement = statement.where(Experiment.project_id == project_id)
        rows = await self._db.scalars(statement.order_by(Experiment.created_at.desc()))
        return list(rows)

    async def get_experiment(self, *, owner: User, experiment_id: uuid.UUID) -> Experiment:
        return await self._owned(Experiment, owner, experiment_id, "experiment")

    async def create_experiment(self, *, owner: User, **fields: Any) -> Experiment:
        if project_id := fields.get("project_id"):
            await self.get_project(owner=owner, project_id=project_id)
        if hypothesis_id := fields.get("hypothesis_id"):
            await self.get_hypothesis(owner=owner, hypothesis_id=hypothesis_id)
        experiment = Experiment(owner_id=owner.id, **fields)
        self._db.add(experiment)
        await self._db.flush()
        return experiment

    async def update_experiment(
        self, *, owner: User, experiment_id: uuid.UUID, changes: dict[str, Any]
    ) -> Experiment:
        experiment = await self.get_experiment(owner=owner, experiment_id=experiment_id)
        for field, value in changes.items():
            setattr(experiment, field, value)
        await self._db.flush()
        return experiment

    async def delete_experiment(self, *, owner: User, experiment_id: uuid.UUID) -> None:
        experiment = await self.get_experiment(owner=owner, experiment_id=experiment_id)
        await self._db.delete(experiment)

    # -- notes --------------------------------------------------------------------

    async def list_notes(
        self,
        *,
        owner: User,
        project_id: uuid.UUID | None = None,
        paper_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> list[Note]:
        statement = select(Note).where(Note.owner_id == owner.id)
        if project_id is not None:
            statement = statement.where(Note.project_id == project_id)
        if paper_id is not None:
            statement = statement.where(Note.paper_id == paper_id)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(Note.title.ilike(pattern) | Note.content.ilike(pattern))
        rows = await self._db.scalars(statement.order_by(Note.updated_at.desc()))
        return list(rows)

    async def get_note(self, *, owner: User, note_id: uuid.UUID) -> Note:
        return await self._owned(Note, owner, note_id, "note")

    async def create_note(self, *, owner: User, **fields: Any) -> Note:
        if project_id := fields.get("project_id"):
            await self.get_project(owner=owner, project_id=project_id)
        note = Note(owner_id=owner.id, **fields)
        self._db.add(note)
        await self._db.flush()
        return note

    async def update_note(
        self, *, owner: User, note_id: uuid.UUID, changes: dict[str, Any]
    ) -> Note:
        note = await self.get_note(owner=owner, note_id=note_id)
        for field, value in changes.items():
            setattr(note, field, value)
        await self._db.flush()
        return note

    async def delete_note(self, *, owner: User, note_id: uuid.UUID) -> None:
        note = await self.get_note(owner=owner, note_id=note_id)
        await self._db.delete(note)

    # -- tasks --------------------------------------------------------------------

    async def list_tasks(self, *, owner: User, project_id: uuid.UUID) -> list[Task]:
        await self.get_project(owner=owner, project_id=project_id)
        rows = await self._db.scalars(
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.position, Task.created_at)
        )
        return list(rows)

    async def create_task(self, *, owner: User, project_id: uuid.UUID, title: str) -> Task:
        await self.get_project(owner=owner, project_id=project_id)
        cleaned = title.strip()
        if not cleaned:
            raise ValidationError("Give the task a name.")

        highest = await self._db.scalar(
            select(func.max(Task.position)).where(Task.project_id == project_id)
        )
        task = Task(
            owner_id=owner.id,
            project_id=project_id,
            title=cleaned,
            position=(highest or 0) + 1,
        )
        self._db.add(task)
        await self._db.flush()
        return task

    async def update_task(
        self, *, owner: User, task_id: uuid.UUID, changes: dict[str, Any]
    ) -> Task:
        task = await self._owned(Task, owner, task_id, "task")
        for field, value in changes.items():
            setattr(task, field, value)
        await self._db.flush()
        return task

    async def delete_task(self, *, owner: User, task_id: uuid.UUID) -> None:
        task = await self._owned(Task, owner, task_id, "task")
        await self._db.delete(task)


def _locator(chunk: PaperChunk, section_title: str | None) -> str:
    """Same shape as a retrieval locator, so evidence and citations read alike."""
    parts: list[str] = []
    if chunk.page_start:
        parts.append(
            f"pp. {chunk.page_start}-{chunk.page_end}"
            if chunk.page_end and chunk.page_end != chunk.page_start
            else f"p. {chunk.page_start}"
        )
    if section_title:
        parts.append(f"§{section_title}")
    return " · ".join(parts) or f"passage {chunk.ordinal + 1}"
