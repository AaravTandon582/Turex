"""The research assistant.

One turn of a conversation, in order:

1. Persist the question, so it survives a failure mid-answer.
2. Retrieve passages from the user's library, scoped to their account.
3. Build the numbered SOURCES block within a token budget.
4. Stream the model's answer to the caller as it arrives.
5. Persist the answer with citations built from the *retrieved* passages.

Step 5 is the point of the whole design. Citations are written by the server from what
retrieval returned, never parsed out of the model's prose. The model chooses which markers to
use; it cannot invent a source that was not put in front of it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from atlas.ai.base import ChatMessage, ChatProvider, ChatRequest, ChunkKind, Role
from atlas.ai.prompts import (
    MODE_EFFORT,
    MODE_RETRIEVAL_LIMIT,
    ExplanationLevel,
    system_prompt,
)
from atlas.core.errors import AppError, ConflictError, NotFoundError
from atlas.core.logging import get_logger
from atlas.models.conversation import (
    AssistantMode,
    Conversation,
    ConversationMessage,
    MessageCitation,
    MessageRole,
)
from atlas.models.paper import Paper
from atlas.models.user import User
from atlas.retrieval.context import build_context, compose_user_turn, markers_used
from atlas.retrieval.search import RetrievalService, RetrievedChunk

logger = get_logger(__name__)

HISTORY_TURNS = 8
"""Prior turns replayed to the model. Enough for a conversation to hold together; short
enough that an hour of reading does not become an enormous prompt."""

MAX_OUTPUT_TOKENS = 8192
"""Generous, because on the models Atlas targets this bounds reasoning and answer together —
a tight limit truncates the answer rather than the thinking."""

TITLE_LENGTH = 80


@dataclass(slots=True)
class TurnEvent:
    """One thing that happened during a turn, streamed to the caller."""

    kind: str
    """`sources` · `text` · `done` · `error`"""

    text: str = ""
    sources: list[RetrievedChunk] | None = None
    message_id: uuid.UUID | None = None


class AssistantService:
    def __init__(
        self,
        db: AsyncSession,
        retrieval: RetrievalService,
        provider: Callable[[], ChatProvider],
    ) -> None:
        self._db = db
        self._retrieval = retrieval
        self._provider = provider
        """A factory, not an instance. Resolving the provider raises when no API key is
        configured, and that must only fail the endpoint that needs a model — reading past
        conversations has to keep working after a key is removed."""

    # -- conversations -------------------------------------------------------------

    async def create_conversation(
        self,
        *,
        owner: User,
        mode: AssistantMode,
        paper_id: uuid.UUID | None = None,
    ) -> Conversation:
        if paper_id is not None:
            paper = await self._db.scalar(
                select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner.id)
            )
            if paper is None:
                raise NotFoundError("We couldn't find that paper.")

        conversation = Conversation(owner_id=owner.id, mode=mode, paper_id=paper_id)
        self._db.add(conversation)
        await self._db.flush()
        return conversation

    async def get_conversation(self, *, owner: User, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self._db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.owner_id == owner.id
            )
        )
        if conversation is None:
            raise NotFoundError("We couldn't find that conversation.")
        return conversation

    async def list_conversations(
        self, *, owner: User, limit: int = 50
    ) -> list[tuple[Conversation, int]]:
        rows = await self._db.execute(
            select(Conversation, func.count(ConversationMessage.id))
            .outerjoin(ConversationMessage, ConversationMessage.conversation_id == Conversation.id)
            .where(Conversation.owner_id == owner.id)
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return [(conversation, count) for conversation, count in rows]

    async def messages(
        self, *, owner: User, conversation_id: uuid.UUID
    ) -> list[ConversationMessage]:
        await self.get_conversation(owner=owner, conversation_id=conversation_id)
        rows = await self._db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            # Eager: serialising a lazily-loaded relationship would attempt sync IO on an
            # async session, which fails at render time rather than at query time.
            .options(selectinload(ConversationMessage.citations))
            .order_by(ConversationMessage.created_at)
        )
        return list(rows)

    async def delete_conversation(self, *, owner: User, conversation_id: uuid.UUID) -> None:
        conversation = await self.get_conversation(owner=owner, conversation_id=conversation_id)
        await self._db.delete(conversation)

    # -- a turn --------------------------------------------------------------------

    async def ask(
        self,
        *,
        owner: User,
        conversation_id: uuid.UUID,
        question: str,
        mode: AssistantMode | None = None,
        level: ExplanationLevel | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """Run one turn, yielding events as they happen."""
        conversation = await self.get_conversation(owner=owner, conversation_id=conversation_id)
        turn_mode = mode or conversation.mode

        cleaned = question.strip()
        if not cleaned:
            raise ConflictError("Ask a question first.")

        history = await self._recent_turns(conversation.id)

        # Persisted before generation starts: if the model fails, the user's question is
        # still in the transcript rather than lost with the error.
        self._db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role=MessageRole.user,
                content=cleaned,
                mode=turn_mode,
            )
        )
        if conversation.title is None:
            conversation.title = _title_from(cleaned)
        conversation.mode = turn_mode
        await self._db.commit()

        # -- retrieve ---------------------------------------------------------------
        chunks = await self._retrieval.search(
            owner_id=owner.id,
            query=cleaned,
            limit=MODE_RETRIEVAL_LIMIT[turn_mode],
            paper_ids=[conversation.paper_id] if conversation.paper_id else None,
        )
        context = build_context(chunks)
        if context.dropped:
            logger.info(
                "context budget trimmed retrieved passages",
                extra={"dropped": context.dropped, "kept": len(context.sources)},
            )

        # Sent first so the reader sees what the answer is being built from before any prose
        # arrives — which is also what makes an ungrounded answer visibly ungrounded.
        yield TurnEvent(kind="sources", sources=[source.chunk for source in context.sources])

        # -- generate ---------------------------------------------------------------
        # Resolved here rather than at construction so an unconfigured instance produces a
        # recorded turn with an actionable explanation, instead of an exception escaping
        # mid-stream as a generic failure.
        try:
            provider = self._provider()
        except AppError as exc:
            message = await self._save_answer(
                conversation=conversation,
                mode=turn_mode,
                answer="",
                failure=exc.message,
                sources=[],
            )
            yield TurnEvent(kind="error", text=exc.message, message_id=message.id)
            return

        request = ChatRequest(
            system=system_prompt(
                turn_mode,
                paper_scoped=conversation.paper_id is not None,
                level=level,
            ),
            messages=[
                *history,
                ChatMessage(role=Role.user, content=compose_user_turn(cleaned, context)),
            ],
            max_output_tokens=MAX_OUTPUT_TOKENS,
            effort=MODE_EFFORT[turn_mode],
        )

        answer: list[str] = []
        failure: str | None = None

        async for chunk in provider.stream(request):
            if chunk.kind is ChunkKind.text:
                answer.append(chunk.text)
                yield TurnEvent(kind="text", text=chunk.text)
            elif chunk.kind is ChunkKind.error:
                failure = chunk.text
                break

        # -- persist ----------------------------------------------------------------
        full_answer = "".join(answer)
        message = await self._save_answer(
            conversation=conversation,
            mode=turn_mode,
            answer=full_answer,
            failure=failure,
            sources=[source.chunk for source in context.sources],
        )

        if failure:
            yield TurnEvent(kind="error", text=failure, message_id=message.id)
        else:
            yield TurnEvent(kind="done", message_id=message.id)

    async def _save_answer(
        self,
        *,
        conversation: Conversation,
        mode: AssistantMode,
        answer: str,
        failure: str | None,
        sources: Sequence[RetrievedChunk],
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=answer,
            mode=mode,
            error_message=failure,
        )
        self._db.add(message)
        await self._db.flush()

        # Citations come from what was retrieved, in the order it was numbered — never from
        # parsing the model's text. `used_in_answer` records which markers the model actually
        # referenced, so the evaluation suite can measure how much context was load-bearing.
        referenced = markers_used(answer, available=len(sources))
        for marker, chunk in enumerate(sources, start=1):
            self._db.add(
                MessageCitation(
                    message_id=message.id,
                    marker=marker,
                    chunk_id=chunk.chunk_id,
                    paper_id=chunk.paper_id,
                    paper_title=chunk.paper_title,
                    locator=chunk.locator[:200],
                    quoted_text=chunk.content,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    used_in_answer=marker in referenced,
                )
            )

        await self._db.commit()
        logger.info(
            "assistant turn complete",
            extra={
                "conversation_id": str(conversation.id),
                "mode": mode.value,
                "sources": len(sources),
                "cited": len(referenced),
                "failed": bool(failure),
            },
        )
        return message

    async def _recent_turns(self, conversation_id: uuid.UUID) -> list[ChatMessage]:
        """Prior turns, oldest first.

        Failed assistant turns are skipped: replaying an error message as though it were an
        answer teaches the model that empty responses are acceptable.
        """
        rows = await self._db.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.error_message.is_(None),
                ConversationMessage.content != "",
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(HISTORY_TURNS)
        )
        recent = list(rows)[::-1]
        return [
            ChatMessage(
                role=Role.user if message.role is MessageRole.user else Role.assistant,
                content=message.content,
            )
            for message in recent
        ]


def _title_from(question: str) -> str:
    """A conversation title, taken from its opening question."""
    collapsed = " ".join(question.split())
    if len(collapsed) <= TITLE_LENGTH:
        return collapsed
    # Cut at a word boundary so the title does not end mid-word.
    truncated = collapsed[:TITLE_LENGTH].rsplit(" ", 1)[0]
    return f"{truncated}…"
