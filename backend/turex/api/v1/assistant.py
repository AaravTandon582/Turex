"""Research assistant endpoints, including the streaming answer channel."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse

from turex.ai.prompts import MODE_DESCRIPTIONS, MODE_LABELS
from turex.api.deps import (
    AssistantServiceDep,
    CurrentUser,
    DbDep,
    GuardDep,
    ProviderRegistryDep,
    RetrievalServiceDep,
)
from turex.core.errors import AppError
from turex.core.logging import get_logger
from turex.models.conversation import AssistantMode
from turex.retrieval.indexer import index_coverage
from turex.retrieval.search import RetrievedChunk
from turex.schemas.assistant import (
    AskRequest,
    AssistantStatus,
    CitationRead,
    ConversationCreate,
    ConversationRead,
    MessageRead,
    ModeInfo,
    SearchResponse,
    SearchResult,
)
from turex.security import policy

logger = get_logger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/status", response_model=AssistantStatus)
async def assistant_status(
    user: CurrentUser, registry: ProviderRegistryDep, db: DbDep
) -> AssistantStatus:
    """What the assistant can do here, and how much of the library is searchable."""
    indexed, total = await index_coverage(db, user.id)
    return AssistantStatus(
        chat_available=registry.chat_available,
        embeddings_available=registry.embeddings_available,
        indexed_chunks=indexed,
        total_chunks=total,
        modes=[
            ModeInfo(value=mode, label=MODE_LABELS[mode], description=MODE_DESCRIPTIONS[mode])
            for mode in AssistantMode
        ],
    )


# -- conversations ------------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(
    user: CurrentUser, service: AssistantServiceDep, paper_id: uuid.UUID | None = None
) -> list[ConversationRead]:
    rows = await service.list_conversations(owner=user, paper_id=paper_id)
    return [
        ConversationRead(
            id=conversation.id,
            title=conversation.title,
            mode=conversation.mode,
            paper_id=conversation.paper_id,
            message_count=count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        for conversation, count in rows
    ]


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, user: CurrentUser, service: AssistantServiceDep
) -> ConversationRead:
    conversation = await service.create_conversation(
        owner=user, mode=payload.mode, paper_id=payload.paper_id
    )
    return ConversationRead.model_validate(conversation)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
async def list_messages(
    conversation_id: uuid.UUID, user: CurrentUser, service: AssistantServiceDep
) -> list[MessageRead]:
    messages = await service.messages(owner=user, conversation_id=conversation_id)
    return [
        MessageRead(
            id=message.id,
            role=message.role,
            content=message.content,
            mode=message.mode,
            error_message=message.error_message,
            citations=[CitationRead.model_validate(c) for c in message.citations],
            created_at=message.created_at,
        )
        for message in messages
    ]


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, service: AssistantServiceDep
) -> None:
    await service.delete_conversation(owner=user, conversation_id=conversation_id)


# -- asking -------------------------------------------------------------------------


def _sse(event: str, data: object) -> str:
    """One Server-Sent Event frame.

    SSE rather than a WebSocket: the channel is one-directional, it survives proxies that
    mangle upgrades, and the browser reconnects on its own.
    """
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _source_payload(chunk: RetrievedChunk, marker: int) -> dict[str, object]:
    return {
        "marker": marker,
        "chunk_id": str(chunk.chunk_id),
        "paper_id": str(chunk.paper_id),
        "paper_title": chunk.paper_title,
        "locator": chunk.locator,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "quoted_text": chunk.content,
        "found_by": chunk.found_by,
    }


@router.post("/conversations/{conversation_id}/ask")
async def ask(
    conversation_id: uuid.UUID,
    payload: AskRequest,
    user: CurrentUser,
    service: AssistantServiceDep,
    guard: GuardDep,
) -> StreamingResponse:
    """Ask a question and stream the answer.

    Frames, in order:

    * `sources` — the passages retrieved, sent **before** any prose so the reader can see
      what the answer is being built from.
    * `text` — answer fragments, to append as they arrive.
    * `done` — finished, with the stored message id.
    * `error` — generation failed; the text is safe to display.
    """
    # Checked before the stream opens. Once an SSE response has started, the status code is
    # already sent and a 429 can no longer be expressed.
    await guard.by_user(user.id, policy.MODEL_CALLS_PER_USER, scope="model")

    async def frames() -> AsyncIterator[str]:
        try:
            async for event in service.ask(
                owner=user,
                conversation_id=conversation_id,
                question=payload.question,
                mode=payload.mode,
                level=payload.level,
            ):
                match event.kind:
                    case "sources":
                        yield _sse(
                            "sources",
                            {
                                "sources": [
                                    _source_payload(chunk, index)
                                    for index, chunk in enumerate(event.sources or [], start=1)
                                ]
                            },
                        )
                    case "text":
                        yield _sse("text", {"text": event.text})
                    case "done":
                        yield _sse("done", {"message_id": str(event.message_id)})
                    case "error":
                        yield _sse(
                            "error",
                            {"message": event.text, "message_id": str(event.message_id)},
                        )
        except AppError as exc:
            # A known failure — an unconfigured provider, a missing conversation. Its message
            # was written for the user and explains what to do, so pass it through rather
            # than flattening it into a generic apology.
            logger.info("assistant stream rejected", extra={"detail": exc.detail})
            yield _sse("error", {"message": exc.message})
        except Exception as exc:
            # The response has already begun, so an HTTP error status is no longer possible.
            # The failure has to travel in-band as a frame the client can render.
            logger.exception("assistant stream failed", exc_info=exc)
            yield _sse("error", {"message": "Turex couldn't finish that answer. Try again."})

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-store",
            # Tells nginx not to buffer, which would hold the whole answer until completion
            # and defeat streaming entirely.
            "x-accel-buffering": "no",
        },
    )


# -- search -------------------------------------------------------------------------


@router.get("/search", response_model=SearchResponse)
async def semantic_search(
    user: CurrentUser,
    retrieval: RetrievalServiceDep,
    guard: GuardDep,
    q: Annotated[str, Query(min_length=1, max_length=500, description="What to look for")],
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
    paper_id: uuid.UUID | None = None,
) -> SearchResponse:
    """Search passages by meaning and by keyword, fused into one ranking."""
    await guard.by_user(user.id, policy.SEARCH_PER_USER, scope="search")
    chunks = await retrieval.search(
        owner_id=user.id, query=q, limit=limit, paper_ids=[paper_id] if paper_id else None
    )
    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                chunk_id=chunk.chunk_id,
                paper_id=chunk.paper_id,
                paper_title=chunk.paper_title,
                content=chunk.content,
                locator=chunk.locator,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_title=chunk.section_title,
                score=round(chunk.score, 6),
                found_by=chunk.found_by,
            )
            for chunk in chunks
        ],
    )
