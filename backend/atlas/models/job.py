"""The ingestion job queue.

Jobs are rows, claimed with `FOR UPDATE SKIP LOCKED`. The reasoning is in
docs/decisions.md D2; the properties that matter here:

* A job is enqueued in the same transaction as the paper it belongs to, so an upload cannot
  half-succeed.
* Progress is a column, so the UI reports real progress by reading the row it already fetches.
* A worker that dies leaves a claimed row whose lease expires, and the job is retried rather
  than lost.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from atlas.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobKind(enum.StrEnum):
    ingest_paper = "ingest_paper"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class IngestionStage(enum.StrEnum):
    """Named steps, reported to the user while a paper is being read.

    The names are deliberately user-facing — the UI renders them directly, so "Extracting
    text" beats "stage 2 of 5".
    """

    queued = "queued"
    extracting_text = "extracting_text"
    reading_structure = "reading_structure"
    extracting_metadata = "extracting_metadata"
    building_chunks = "building_chunks"
    embedding = "embedding"
    complete = "complete"


STAGE_LABELS: dict[IngestionStage, str] = {
    IngestionStage.queued: "Waiting to start",
    IngestionStage.extracting_text: "Extracting text",
    IngestionStage.reading_structure: "Reading structure",
    IngestionStage.extracting_metadata: "Identifying the paper",
    IngestionStage.building_chunks: "Preparing passages",
    IngestionStage.embedding: "Indexing for search",
    IngestionStage.complete: "Ready",
}


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        # The claim query's access path: oldest queued job that is due.
        Index(
            "ix_ingestion_jobs_claimable",
            "status",
            "scheduled_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_ingestion_jobs_paper_id", "paper_id"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_within_range"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[JobKind] = mapped_column(
        Enum(JobKind, name="job_kind", native_enum=False, length=32),
        nullable=False,
        default=JobKind.ingest_paper,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False, length=32),
        nullable=False,
        default=JobStatus.queued,
    )
    stage: Mapped[IngestionStage] = mapped_column(
        Enum(IngestionStage, name="ingestion_stage", native_enum=False, length=32),
        nullable=False,
        default=IngestionStage.queued,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    error_message: Mapped[str | None] = mapped_column(Text)

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    """When the job becomes eligible. Retries push this forward with a backoff."""

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Lease expiry. A worker that dies mid-job leaves this in the past, and the job is
    reclaimed rather than stuck as `running` forever."""

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]
