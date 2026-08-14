"""Highlights and margin notes on a paper.

Anchoring is the hard part. A highlight has to survive the page being re-rendered at a
different zoom, in a different browser, on a different device — so it cannot be stored as
pixel coordinates.

Instead each annotation records **the text it covers and where that text sits in the page's
extracted content**: page number, character offset, and length, plus the selected text itself.
Re-locating is then a string match near a known offset, which is stable across renderers. The
stored text is also what makes the annotation meaningful on its own — it appears in the
notebook and in exports, where no PDF is being rendered at all.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atlas.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HighlightColour(enum.StrEnum):
    """Four colours, so a user can develop their own coding without a palette to manage.

    Named by intent rather than by hue: what a highlight *means* is the useful thing to
    filter and export by, and the meaning survives a change of palette.
    """

    important = "important"
    question = "question"
    method = "method"
    result = "result"


class Annotation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "annotations"
    __table_args__ = (
        Index("ix_annotations_paper_id_page_number", "paper_id", "page_number"),
        Index("ix_annotations_owner_id_created_at", "owner_id", "created_at"),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("text_length > 0", name="text_length_positive"),
        CheckConstraint("text_offset >= 0", name="text_offset_non_negative"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    """Character offset of the selection within that page's extracted text."""

    text_length: Mapped[int] = mapped_column(Integer, nullable=False)

    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    """The highlighted text itself. Both the anchor of last resort and the thing shown
    wherever the highlight appears outside the reader."""

    colour: Mapped[HighlightColour] = mapped_column(
        Enum(HighlightColour, name="highlight_colour", native_enum=False, length=32),
        nullable=False,
        default=HighlightColour.important,
    )
    note: Mapped[str | None] = mapped_column(Text)
    """The user's own words about this passage. Null for a plain highlight."""

    paper: Mapped[object] = relationship("Paper", viewonly=True)
