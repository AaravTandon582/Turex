"""Papers and the structure Atlas extracts from them.

A paper is stored three ways at once, because three different jobs need different shapes:

* the **original file**, so the reader can render exactly what the author published;
* **sections**, so navigation and citation locators mean something to a human;
* **chunks**, so retrieval has passages of the right size, each still carrying the page and
  section it came from.

Chunks are treated as immutable once written. Citations point at chunk ids, so mutating a
chunk would silently change what a stored citation claims.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atlas.db.base import Base, OwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIMENSIONS = 1536
"""Fixed at the column level. Changing embedding model means a migration and a re-index —
see docs/decisions.md D3."""


class PaperSource(enum.StrEnum):
    upload = "upload"
    arxiv = "arxiv"
    doi = "doi"
    url = "url"


class ProcessingStatus(enum.StrEnum):
    """Where a paper is in the ingestion pipeline."""

    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class ReadingStatus(enum.StrEnum):
    unread = "unread"
    reading = "reading"
    read = "read"
    revisit = "revisit"


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    """A VARCHAR + CHECK constraint rather than a native PostgreSQL enum type.

    Adding a value to a native enum requires ALTER TYPE, which cannot run inside a
    transaction alongside other DDL on older servers. A check constraint is a plain
    migration, and the column stays readable in psql.
    """
    return Enum(python_enum, name=name, native_enum=False, validate_strings=True, length=32)


class Paper(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    __tablename__ = "papers"
    __table_args__ = (
        # A user re-uploading the same file should land on the paper they already have
        # rather than a duplicate. Scoped per owner: two users may hold the same PDF.
        UniqueConstraint("owner_id", "content_hash", name="uq_papers_owner_id_content_hash"),
        Index("ix_papers_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_papers_owner_id_status", "owner_id", "status"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
    )

    # -- Bibliographic metadata, extracted during ingestion --------------------
    # Nullable because a paper exists from the moment it is uploaded, before anything has
    # read it. The UI shows the filename until a real title is known.
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    """Ordered `[{"name": ...}]`. JSONB rather than a table: author identity resolution is a
    hard problem Atlas does not attempt, so these are strings, not entities."""

    abstract: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(255))
    arxiv_id: Mapped[str | None] = mapped_column(String(64))

    # -- Provenance -------------------------------------------------------------
    source: Mapped[PaperSource] = mapped_column(
        _enum(PaperSource, "paper_source"), nullable=False, default=PaperSource.upload
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # -- Pipeline and user state -------------------------------------------------
    status: Mapped[ProcessingStatus] = mapped_column(
        _enum(ProcessingStatus, "processing_status"),
        nullable=False,
        default=ProcessingStatus.pending,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    """User-facing explanation when status is `failed`. Technical detail goes to the logs."""

    reading_status: Mapped[ReadingStatus] = mapped_column(
        _enum(ReadingStatus, "reading_status"), nullable=False, default=ReadingStatus.unread
    )
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sections: Mapped[list[PaperSection]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PaperSection.ordinal",
    )
    chunks: Mapped[list[PaperChunk]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PaperChunk.ordinal",
    )

    @property
    def display_title(self) -> str:
        """What to show before extraction has produced a real title."""
        return self.title or self.original_filename

    def __repr__(self) -> str:
        return f"<Paper {self.display_title[:48]!r}>"


class PaperSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A heading and its span within the document.

    Sections give citations a locator a person recognises — "§4.2 Results" rather than
    "characters 18400–21050".
    """

    __tablename__ = "paper_sections"
    __table_args__ = (
        UniqueConstraint("paper_id", "ordinal", name="uq_paper_sections_paper_id_ordinal"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)

    paper: Mapped[Paper] = relationship(back_populates="sections")
    chunks: Mapped[list[PaperChunk]] = relationship(back_populates="section")


class PaperChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A retrievable passage.

    Every field beyond `content` exists so a retrieved passage can be shown to the user in
    context and cited precisely. A chunk that cannot say where it came from is not usable as
    evidence.
    """

    __tablename__ = "paper_chunks"
    __table_args__ = (
        UniqueConstraint("paper_id", "ordinal", name="uq_paper_chunks_paper_id_ordinal"),
        Index("ix_paper_chunks_paper_id_ordinal", "paper_id", "ordinal"),
        # Lexical half of hybrid retrieval. GIN over the generated tsvector.
        Index("ix_paper_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        # Vector half. HNSW gives good recall at low latency without a training step, and
        # cosine distance matches how the embedding providers normalise their output.
        Index(
            "ix_paper_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("paper_sections.id", ondelete="SET NULL"), index=True
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    """Null until the embedding stage runs, so a paper is readable and lexically searchable
    before its vectors exist."""

    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=False,
    )
    """Maintained by PostgreSQL, not by application code — a trigger or a service that
    forgets to update it produces a search index that is quietly wrong."""

    paper: Mapped[Paper] = relationship(back_populates="chunks")
    section: Mapped[PaperSection | None] = relationship(back_populates="chunks")


class PaperEquation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A displayed equation, found in the extracted text.

    Stored rather than detected on demand so the reader can list them without re-parsing, and
    so an equation keeps a stable id that an explanation can be attached to.

    Detection is heuristic — PDF text extraction does not mark equations — so this table is
    genuinely approximate in a way the rest of the schema is not. See `ingestion/equations.py`.
    """

    __tablename__ = "paper_equations"
    __table_args__ = (
        UniqueConstraint("paper_id", "ordinal", name="uq_paper_equations_paper_id_ordinal"),
        Index("ix_paper_equations_paper_id_ordinal", "paper_id", "ordinal"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(32))
    """The number the paper gave it, when it gave one — what a reader cites."""

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)


class PaperReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One entry from a paper's bibliography.

    Stored so a reader following `[12]` can see what it points at without scrolling to the
    back, and so an entry carrying an arXiv id or a DOI can be added to the library in one
    action — which is what turns a bibliography into a reading list.

    Parsed from extracted text, so approximate. `marker` is null for author-year styles, which
    print no number.
    """

    __tablename__ = "paper_references"
    __table_args__ = (
        UniqueConstraint("paper_id", "ordinal", name="uq_paper_references_paper_id_ordinal"),
        Index("ix_paper_references_paper_id_ordinal", "paper_id", "ordinal"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    marker: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    arxiv_id: Mapped[str | None] = mapped_column(String(64))
    doi: Mapped[str | None] = mapped_column(String(255))
    year: Mapped[int | None] = mapped_column(Integer)
