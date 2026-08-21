"""The research workspace: projects, notes, hypotheses, and experiments.

This is the part of Turex that makes it a place to *do* research rather than a place to read
about it. The schema follows the loop directly — a project holds a question, hypotheses are
candidate answers to it, experiments test those hypotheses, and notes are the user's own
thinking threaded through all of it.

Two decisions worth stating:

* **Evidence is a link, not a paragraph.** Support for a hypothesis points at a real chunk of
  a real paper, so "three passages support this" is a countable fact rather than a claim the
  user typed.
* **Everything is optional.** A note need not belong to a project; a hypothesis need not have
  an experiment. Research does not arrive in the right order, and a schema that insists on it
  would be abandoned within a day.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from turex.db.base import Base, OwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(python_enum, name=name, native_enum=False, validate_strings=True, length=32)


class ProjectStatus(enum.StrEnum):
    active = "active"
    paused = "paused"
    complete = "complete"


class HypothesisStatus(enum.StrEnum):
    """Where a hypothesis stands.

    `weakly_supported` exists as a distinct state because collapsing it into `supported`
    is how a tentative result becomes a confident one without anyone deciding it should.
    """

    proposed = "proposed"
    testing = "testing"
    supported = "supported"
    weakly_supported = "weakly_supported"
    contradicted = "contradicted"
    abandoned = "abandoned"


class EvidenceStance(enum.StrEnum):
    supports = "supports"
    contradicts = "contradicts"


class ExperimentStatus(enum.StrEnum):
    planned = "planned"
    running = "running"
    complete = "complete"
    abandoned = "abandoned"


class TaskStatus(enum.StrEnum):
    todo = "todo"
    doing = "doing"
    done = "done"


class Project(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_owner_id_updated_at", "owner_id", "updated_at"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    research_question: Mapped[str | None] = mapped_column(Text)
    """The question the project exists to answer. The single most important field here, and
    the thing the workspace is organised around."""

    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus, "project_status"), nullable=False, default=ProjectStatus.active
    )

    papers: Mapped[list[ProjectPaper]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    hypotheses: Mapped[list[Hypothesis]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    experiments: Mapped[list[Experiment]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class ProjectPaper(Base):
    """A paper gathered for a project."""

    __tablename__ = "project_papers"
    __table_args__ = (Index("ix_project_papers_paper_id", "paper_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    relevance_note: Mapped[str | None] = mapped_column(Text)
    """Why this paper is here — the thing you always remember at the time and never later."""

    project: Mapped[Project] = relationship(back_populates="papers")


class Hypothesis(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        Index("ix_hypotheses_project_id_position", "project_id", "position"),
        Index("ix_hypotheses_owner_id", "owner_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    """Written as a claim that could turn out to be false. The UI nudges toward that."""

    motivation: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[str | None] = mapped_column(Text)
    """What has to be true for the hypothesis to be testable at all. Recording these is what
    makes a later failure interpretable rather than just disappointing."""

    status: Mapped[HypothesisStatus] = mapped_column(
        _enum(HypothesisStatus, "hypothesis_status"),
        nullable=False,
        default=HypothesisStatus.proposed,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    project: Mapped[Project | None] = relationship(back_populates="hypotheses")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # Loading this implicitly would be sync IO on an async session, which fails at
        # render time with an obscure error. Raising here turns that into an immediate,
        # obvious failure — callers load evidence explicitly.
        lazy="raise_on_sql",
    )
    experiments: Mapped[list[Experiment]] = relationship(back_populates="hypothesis")


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A passage bearing on a hypothesis, for or against.

    Anchored to a chunk the same way a citation is, and carrying the same snapshot, so the
    evidence remains readable after the paper is re-ingested.
    """

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_hypothesis_id_stance", "hypothesis_id", "stance"),
        # Both cascade from a paper being deleted.
        Index("ix_evidence_chunk_id", "chunk_id"),
        Index("ix_evidence_paper_id", "paper_id"),
        UniqueConstraint("hypothesis_id", "chunk_id", name="uq_evidence_hypothesis_id_chunk_id"),
    )

    hypothesis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("paper_chunks.id", ondelete="SET NULL")
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="SET NULL")
    )

    stance: Mapped[EvidenceStance] = mapped_column(
        _enum(EvidenceStance, "evidence_stance"), nullable=False
    )
    paper_title: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str] = mapped_column(String(200), nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text)
    """The user's own account of why this passage bears on the hypothesis. The passage is the
    evidence; this is the argument."""

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="evidence")


class Experiment(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A planned or completed test.

    `expected_result` is recorded before running and never overwritten by `actual_result`.
    Keeping both is the difference between an experiment and a story told afterwards.
    """

    __tablename__ = "experiments"
    __table_args__ = (
        Index("ix_experiments_project_id_created_at", "project_id", "created_at"),
        Index("ix_experiments_owner_id", "owner_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    hypothesis_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hypotheses.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)

    independent_variables: Mapped[str | None] = mapped_column(Text)
    dependent_variables: Mapped[str | None] = mapped_column(Text)
    controls: Mapped[str | None] = mapped_column(Text)
    confounders: Mapped[str | None] = mapped_column(Text)
    dataset: Mapped[str | None] = mapped_column(Text)
    methodology: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[str | None] = mapped_column(Text)

    expected_result: Mapped[str | None] = mapped_column(Text)
    actual_result: Mapped[str | None] = mapped_column(Text)
    interpretation: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ExperimentStatus] = mapped_column(
        _enum(ExperimentStatus, "experiment_status"),
        nullable=False,
        default=ExperimentStatus.planned,
    )
    run_on: Mapped[date | None] = mapped_column(Date)

    project: Mapped[Project | None] = relationship(back_populates="experiments")
    hypothesis: Mapped[Hypothesis | None] = relationship(back_populates="experiments")


class Note(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A note in the research notebook.

    Markdown, stored as written. Every link is optional and nullable — a thought arrives
    before it is clear what it belongs to, and forcing a filing decision at that moment is how
    notebooks stop being used.
    """

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_owner_id_updated_at", "owner_id", "updated_at"),
        Index("ix_notes_project_id", "project_id"),
        Index("ix_notes_paper_id", "paper_id"),
        Index("ix_notes_hypothesis_id", "hypothesis_id"),
    )

    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="SET NULL")
    )
    hypothesis_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hypotheses.id", ondelete="SET NULL")
    )


class Task(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A next action inside a project."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_id_status", "project_id", "status"),
        Index("ix_tasks_owner_id", "owner_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"), nullable=False, default=TaskStatus.todo
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    project: Mapped[Project] = relationship(back_populates="tasks")
