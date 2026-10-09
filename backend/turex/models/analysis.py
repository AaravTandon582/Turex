"""Analyses: the computational half of a research project.

The workspace could already describe an experiment — variables, controls, methodology,
expected result — but not *do* one. Everything a researcher actually computes happened
somewhere else and came back as a sentence typed into `actual_result`, which is exactly the
gap between a project tracker and a research environment.

An analysis is a notebook: an ordered list of cells, each holding code and the output it last
produced. It belongs to a project, and optionally to the experiment it is evidence for, so a
number in a write-up can be traced to the code that produced it.

**Nothing here executes anything.** The code runs in the reader's own browser, in Python
compiled to WebAssembly, and only the text comes back to be stored. That is a deliberate
boundary and the reason this feature can exist at all: running code a user supplies is the
single most dangerous thing a web application can do, and the sandbox that makes it safe —
no filesystem, no network, no access to the host — is one the browser already provides and
maintains. Turex storing the result of that is no more dangerous than storing a note.

So the server treats cell source and cell output as **text and nothing more**. It is never
evaluated, never interpolated into a query, and never rendered as HTML.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from turex.db.base import Base, OwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CellKind(enum.StrEnum):
    """What a cell holds.

    Prose sits alongside code because an analysis without it is a pile of numbers. It is the
    same Markdown-and-LaTeX the notebook takes, rendered by the same component.
    """

    code = "code"
    markdown = "markdown"


class CellStatus(enum.StrEnum):
    """What happened the last time this cell ran.

    `stale` is the one that earns its place: a cell whose source changed since it produced its
    output is showing a number that no longer corresponds to the code above it, and silently
    leaving it looking finished is how a wrong figure ends up in a write-up.
    """

    idle = "idle"
    ok = "ok"
    error = "error"
    stale = "stale"


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(python_enum, name=name, native_enum=False, validate_strings=True, length=32)


class Analysis(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A notebook of cells, attached to a project."""

    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_project_id_created_at", "project_id", "created_at"),
        Index("ix_analyses_owner_id", "owner_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("experiments.id", ondelete="SET NULL"), index=True
    )
    """The experiment this is evidence for, if any.

    `SET NULL` rather than `CASCADE`: deleting the plan should not delete the work that was
    done under it. The analysis survives, unattached, which is recoverable — the reverse is
    not.
    """

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cells: Mapped[list[AnalysisCell]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AnalysisCell.ordinal",
    )


class AnalysisCell(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One cell: its source, and whatever it last printed.

    Not owner-scoped itself. It reaches an owner only through its analysis, and the API loads
    it that way, so a second `owner_id` here would be a copy that can disagree with the truth.
    """

    __tablename__ = "analysis_cells"
    __table_args__ = (
        Index("ix_analysis_cells_analysis_id_ordinal", "analysis_id", "ordinal"),
        # Deferred, because inserting a cell renumbers the ones below it one row at a time and
        # every intermediate state of that renumber collides. The question worth asking is
        # whether the positions are unique when the transaction is done. See migration 0019.
        UniqueConstraint(
            "analysis_id",
            "ordinal",
            name="uq_analysis_cells_analysis_id_ordinal",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    kind: Mapped[CellKind] = mapped_column(
        _enum(CellKind, "cell_kind"), nullable=False, server_default=CellKind.code.value
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    output: Mapped[str | None] = mapped_column(Text)
    """Everything the cell printed, plus the value of its last expression.

    Stored so reopening a notebook shows what it showed before rather than a blank slate that
    has to be re-run — a run costs seconds and, for anything real, needs the packages loading
    again.
    """

    image: Mapped[str | None] = mapped_column(Text)
    """A matplotlib figure, as a base64 PNG data URI, or null.

    A plot is the output most worth keeping and the one that cannot survive as text. Held in
    the row rather than the document store because it belongs to the cell's history rather
    than the library's files, and because it dies with the cell.
    """

    status: Mapped[CellStatus] = mapped_column(
        _enum(CellStatus, "cell_status"), nullable=False, server_default=CellStatus.idle.value
    )
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    analysis: Mapped[Analysis] = relationship(back_populates="cells")
