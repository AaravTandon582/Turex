"""Request and response models for the research assistant."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field, field_validator

from turex.ai.prompts import ExplanationLevel
from turex.models.conversation import AssistantMode, MessageRole
from turex.schemas.base import TurexModel


class CitationRead(TurexModel):
    """A source an answer rested on.

    `chunk_id` is null once the underlying passage is gone — the paper was re-ingested or
    deleted. The snapshot fields still show what was cited; only the jump-to-passage link
    stops working.
    """

    model_config = ConfigDict(from_attributes=True)

    marker: int
    chunk_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    paper_title: str
    locator: str
    quoted_text: str
    page_start: int | None
    page_end: int | None
    used_in_answer: bool


class MessageRead(TurexModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    mode: AssistantMode | None
    error_message: str | None
    citations: list[CitationRead] = Field(default_factory=list)
    created_at: datetime


class ConversationRead(TurexModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    mode: AssistantMode
    paper_id: uuid.UUID | None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationCreate(TurexModel):
    mode: AssistantMode = AssistantMode.research
    paper_id: uuid.UUID | None = None


class AskRequest(TurexModel):
    question: str = Field(min_length=1, max_length=8000)
    mode: AssistantMode | None = None
    """Overrides the conversation's mode for this turn, and becomes its new default."""

    level: ExplanationLevel | None = None
    """Who to pitch the answer at. Per-turn only — a reader wanting one concept explained
    from scratch is not asking for every later answer to be beginner-level."""

    @field_validator("question")
    @classmethod
    def _require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Ask a question first")
        return stripped


class ModeInfo(TurexModel):
    value: AssistantMode
    label: str
    description: str


class AssistantStatus(TurexModel):
    """Whether the assistant can actually run on this instance.

    Reported up front so the UI can explain that AI features need configuration, rather than
    presenting a chat box that fails on the first message.
    """

    chat_available: bool
    embeddings_available: bool
    indexed_chunks: int
    total_chunks: int
    modes: list[ModeInfo]


class SearchResult(TurexModel):
    """A passage found by semantic search."""

    chunk_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    content: str
    locator: str
    page_start: int | None
    page_end: int | None
    section_title: str | None
    score: float
    found_by: str
    """`meaning`, `keyword`, or `both` — so a result can explain why it surfaced."""


class SearchResponse(TurexModel):
    query: str
    results: list[SearchResult]
