"""Conversations with the research assistant, and the citations their answers rest on.

The important design choice here is that a citation stores **both** a reference to the chunk
it came from and a snapshot of what that chunk said. The reference is what makes the citation
resolvable — click it and land on the passage. The snapshot is what keeps it honest: chunks
are rewritten when a paper is re-ingested, and a citation that silently started pointing at
different text would be a fabricated quotation.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from turex.db.base import Base, OwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AssistantMode(enum.StrEnum):
    """What the user is trying to do.

    Distinct modes rather than one prompt that tries to be everything: critique and
    explanation want opposite behaviour, and a single prompt asked to do both does neither
    well. The mode selects the system prompt, the reasoning effort, and how much context is
    retrieved.
    """

    explain = "explain"
    research = "research"
    critique = "critique"
    ideate = "ideate"
    experiment = "experiment"
    study = "study"
    write = "write"


class MessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(python_enum, name=name, native_enum=False, validate_strings=True, length=32)


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_id_updated_at", "owner_id", "updated_at"),)

    title: Mapped[str | None] = mapped_column(String(300))
    """Derived from the first question. Null until that question is asked."""

    mode: Mapped[AssistantMode] = mapped_column(
        _enum(AssistantMode, "assistant_mode"), nullable=False, default=AssistantMode.research
    )

    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    """Set when the conversation is about one paper, which scopes retrieval to it."""

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index(
            "ix_conversation_messages_conversation_id_created_at", "conversation_id", "created_at"
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole, "message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    mode: Mapped[AssistantMode | None] = mapped_column(_enum(AssistantMode, "assistant_mode"))
    """The mode this turn ran in. Recorded per message because a conversation can switch
    mode partway through, and an old answer should still say how it was produced."""

    error_message: Mapped[str | None] = mapped_column(Text)
    """Set when generation failed. The turn is kept rather than discarded so the user's
    question is not lost and the failure is visible in the transcript."""

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list[MessageCitation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MessageCitation.marker",
        # Must be eager-loaded by the caller; see the note on Hypothesis.evidence.
        lazy="raise_on_sql",
    )


class MessageCitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One source an answer drew on.

    Created from the passages actually retrieved and placed in the model's context — never
    parsed out of the model's prose. That is the mechanism behind "Turex does not fabricate
    citations": a citation is a foreign key the server wrote, not a claim the model made.
    """

    __tablename__ = "message_citations"
    __table_args__ = (
        Index("ix_message_citations_message_id_marker", "message_id", "marker"),
        Index("ix_message_citations_chunk_id", "chunk_id"),
        Index("ix_message_citations_paper_id", "paper_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    marker: Mapped[int] = mapped_column(Integer, nullable=False)
    """The number shown in the answer — the [1] the reader clicks."""

    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("paper_chunks.id", ondelete="SET NULL")
    )
    """Null once the chunk is gone, after the paper was re-ingested or deleted. The snapshot
    below still shows what was cited; only the jump-to-passage link stops working."""

    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="SET NULL")
    )

    # -- snapshot, written at citation time and never updated ---------------------
    paper_title: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str] = mapped_column(String(200), nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)

    used_in_answer: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False, default=False
    )
    """Whether the answer actually referenced this marker. Retrieval returns candidates; the
    model uses some of them. Recording both lets the evaluation suite measure how much of the
    retrieved context was genuinely load-bearing."""

    message: Mapped[ConversationMessage] = relationship(back_populates="citations")
