"""OpenAI providers: chat, and the embedding model Atlas indexes with by default."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import openai

from atlas.ai.base import (
    ChatChunk,
    ChatProvider,
    ChatRequest,
    ChatResult,
    ChunkKind,
    EmbeddingProvider,
    Usage,
)
from atlas.core.errors import ProviderUnavailableError
from atlas.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_BATCH_SIZE = 96
"""Chunks per embedding request. Large enough that a paper costs a handful of calls, small
enough to stay well under the per-request token ceiling on long passages."""

_GENERIC_FAILURE = "Atlas couldn't reach the AI service. Try again in a moment."


class OpenAIChatProvider(ChatProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 120.0) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        return {
            "model": self._model,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                *({"role": m.role.value, "content": m.content} for m in request.messages),
            ],
        }

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        try:
            stream = await self._client.chat.completions.create(
                **self._payload(request), stream=True
            )
            async for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta.content
                if delta:
                    yield ChatChunk(ChunkKind.text, delta)
            yield ChatChunk(ChunkKind.done)
        except openai.APIStatusError as exc:
            logger.error("openai request failed", extra={"status": exc.status_code})
            yield ChatChunk(
                ChunkKind.error,
                "Atlas is being rate limited. Try again in a moment."
                if exc.status_code == 429
                else _GENERIC_FAILURE,
            )
        except openai.APIConnectionError as exc:
            logger.warning("openai connection failed", extra={"detail": str(exc)})
            yield ChatChunk(ChunkKind.error, _GENERIC_FAILURE)

    async def complete(self, request: ChatRequest) -> ChatResult:
        try:
            response = await self._client.chat.completions.create(**self._payload(request))
        except (openai.APIStatusError, openai.APIConnectionError) as exc:
            raise ProviderUnavailableError(detail=f"openai: {exc}") from exc

        choice = response.choices[0]
        return ChatResult(
            text=choice.message.content or "",
            usage=Usage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
            stopped_early=choice.finish_reason == "length",
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str, dimensions: int) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=60.0)
        self._model = model
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = list(texts[start : start + EMBEDDING_BATCH_SIZE])
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                    # Requested explicitly so the vector always matches the pgvector column,
                    # even if the model's native width changes.
                    dimensions=self.dimensions,
                )
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                raise ProviderUnavailableError(
                    "Atlas couldn't index that document right now. It will try again.",
                    detail=f"openai embeddings: {exc}",
                ) from exc

            # The API preserves input order, but the index is authoritative — relying on
            # position alone would silently mis-pair a vector with its chunk.
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)

        return vectors
