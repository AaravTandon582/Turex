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
from atlas.ai.failures import Failure, classify
from atlas.core.errors import ProviderUnavailableError
from atlas.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_BATCH_SIZE = 96
"""Chunks per embedding request. Large enough that a paper costs a handful of calls, small
enough to stay well under the per-request token ceiling on long passages."""

_GENERIC_FAILURE = "Atlas couldn't reach the AI service. Try again in a moment."


def _failure(exc: Exception) -> Failure:
    """Read the status and body off whichever kind of error the client raised."""
    status = getattr(exc, "status_code", None)
    return classify(status if isinstance(status, int) else None, str(exc))


class OpenAIChatProvider(ChatProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
        fallback_models: Sequence[str] = (),
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds
        )
        self._model = model
        self._fallbacks = tuple(fallback_models)
        """Models to try when the configured one cannot answer at all.

        Not for quality and not for latency — only for the failures where the request itself
        was fine and *this particular model* is unavailable: the account has no credit for it,
        the key is not entitled to it, or the endpoint does not carry it. A smaller model
        answering is better than a feature that has stopped existing, and which model answered
        is logged rather than hidden.

        Deliberately not attempted for a rate limit or an outage. Those are about the service,
        not the model, so another model on the same service will fail the same way — and
        hammering it with a second request is the opposite of backing off.
        """

    def _candidates(self) -> tuple[str, ...]:
        return (self._model, *self._fallbacks)

    def _payload(self, request: ChatRequest, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                *({"role": m.role.value, "content": m.content} for m in request.messages),
            ],
        }

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream an answer, moving down the candidates only before the first token.

        Once text has been emitted the answer is committed: falling back mid-stream would
        splice two models' prose together, and the reader would have no way to tell. A failure
        after that point is reported as a failure.
        """
        failure = Failure(_GENERIC_FAILURE, retryable=True)

        for index, model in enumerate(self._candidates()):
            started = False
            try:
                stream = await self._client.chat.completions.create(
                    **self._payload(request, model), stream=True
                )
                async for event in stream:
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta.content
                    if delta:
                        started = True
                        yield ChatChunk(ChunkKind.text, delta)
                yield ChatChunk(ChunkKind.done)
                return
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                failure = _failure(exc)
                logger.warning(
                    "openai stream failed",
                    extra={"model": model, "retryable": failure.retryable, "detail": str(exc)},
                )
                if started or failure.retryable or index == len(self._candidates()) - 1:
                    break
                logger.info("falling back to another model", extra={"from": model})

        yield ChatChunk(ChunkKind.error, failure.message)

    async def complete(self, request: ChatRequest) -> ChatResult:
        failure = Failure(_GENERIC_FAILURE, retryable=True)

        for index, model in enumerate(self._candidates()):
            try:
                response = await self._client.chat.completions.create(
                    **self._payload(request, model)
                )
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                failure = _failure(exc)
                logger.warning(
                    "openai request failed",
                    extra={"model": model, "retryable": failure.retryable, "detail": str(exc)},
                )
                if failure.retryable or index == len(self._candidates()) - 1:
                    raise ProviderUnavailableError(
                        failure.message, detail=f"{model}: {exc}"
                    ) from exc
                continue

            choice = response.choices[0]
            text = choice.message.content or ""

            if not text.strip():
                # An empty completion is not an answer, and accepting it as one turned a
                # working fallback chain into a confusing failure downstream: the caller
                # reported "no JSON array in a response of 0 characters" rather than trying
                # the next model. Some models spend their whole token budget on internal
                # reasoning and emit nothing, which is indistinguishable from a refusal here
                # and is treated the same way.
                failure = Failure("The AI service returned an empty answer.", retryable=False)
                logger.warning(
                    "model returned nothing",
                    extra={"model": model, "finish_reason": choice.finish_reason},
                )
                if index == len(self._candidates()) - 1:
                    raise ProviderUnavailableError(failure.message, detail=f"{model}: empty")
                continue

            if index > 0:
                logger.info(
                    "answered by a fallback model",
                    extra={"model": model, "configured": self._model},
                )

            return ChatResult(
                text=text,
                usage=Usage(
                    input_tokens=response.usage.prompt_tokens if response.usage else 0,
                    output_tokens=response.usage.completion_tokens if response.usage else 0,
                ),
                stopped_early=choice.finish_reason == "length",
            )

        raise ProviderUnavailableError(failure.message, detail="no candidate model answered")


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(
        self, *, api_key: str, model: str, dimensions: int, base_url: str | None = None
    ) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
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
