"""OpenAI providers: chat, and the embedding model Turex indexes with by default."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import openai

from turex.ai.base import (
    ChatChunk,
    ChatProvider,
    ChatRequest,
    ChatResult,
    ChunkKind,
    EmbeddingProvider,
    Usage,
)
from turex.ai.failures import Failure, classify
from turex.core.errors import ProviderUnavailableError
from turex.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_BATCH_SIZE = 96
"""Chunks per embedding request. Large enough that a paper costs a handful of calls, small
enough to stay well under the per-request token ceiling on long passages."""

_GENERIC_FAILURE = "Turex couldn't reach the AI service. Try again in a moment."


TRANSIENT_ATTEMPTS = 3
"""How many times a transient failure is actually retried before moving on.

Classifying a failure as retryable and then not retrying it is worse than not classifying it:
the caller is told to try again while the code that could have tried gave up immediately. That
is what happened — every request after the first died on "Connection error" without a single
retry and without touching the fallback models.
"""

RETRY_BACKOFF_SECONDS = 1.0


def _failure(exc: Exception) -> Failure:
    """Read the status and body off whichever kind of error the client raised."""
    status = getattr(exc, "status_code", None)
    return classify(status if isinstance(status, int) else None, str(exc))


class _Rejected(Exception):
    """This model will not answer this request. Carries why, so the caller can decide whether
    another model is worth trying."""

    def __init__(self, failure: Failure, model: str, cause: Exception | None) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.model = model
        self.cause = cause


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
        extra_api_keys: Sequence[str] = (),
    ) -> None:
        keys = [api_key, *(key for key in extra_api_keys if key and key != api_key)]
        self._clients = [
            openai.AsyncOpenAI(api_key=key, base_url=base_url, timeout=timeout_seconds)
            for key in keys
        ]
        """One client per key, tried in order.

        Keys and models fail for different reasons and rotate independently. A model failure —
        this endpoint does not carry it, this key is not entitled to it — is answered by trying
        another model on the *same* key. An account failure — no credit, revoked, rate limited
        — is answered by trying another key, because every model on that key will fail the same
        way and a rate limit in particular is counted per account.

        With one key configured this is exactly the previous behaviour. A second key is worth
        having mainly for rate limits, since those are the failure a different model cannot
        route around.
        """

        self._client = self._clients[0]
        """The first key. Kept as an attribute because the tests substitute it, and because
        every path that does not care about rotation reads this one."""

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

    def _keys(self) -> list[openai.AsyncOpenAI]:
        """Clients to try, newest failure last. The first is always the configured key."""
        return [self._client, *self._clients[1:]]

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
            last = index == len(self._candidates()) - 1
            started = False
            try:
                stream = await self._attempt_stream(request, model)
                async for event in stream:
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta.content
                    if delta:
                        started = True
                        yield ChatChunk(ChunkKind.text, delta)
                yield ChatChunk(ChunkKind.done)
                return
            except (openai.APIStatusError, openai.APIConnectionError, _Rejected) as exc:
                failure = exc.failure if isinstance(exc, _Rejected) else _failure(exc)
                logger.warning(
                    "openai stream failed",
                    extra={"model": model, "detail": str(exc)[:200]},
                )
                # Once text has been emitted the answer is committed: falling back mid-stream
                # would splice two models' prose together with nothing to say which is which.
                if started or failure.account_wide or last:
                    break
                logger.info("falling back to another model", extra={"from": model})

        yield ChatChunk(ChunkKind.error, failure.message)

    async def _attempt_stream(
        self, request: ChatRequest, model: str, client: openai.AsyncOpenAI | None = None
    ) -> Any:
        """Open a stream, retrying while the failure looks transient."""
        failure = Failure(_GENERIC_FAILURE, retryable=True)

        for attempt in range(1, TRANSIENT_ATTEMPTS + 1):
            try:
                return await (client or self._client).chat.completions.create(
                    **self._payload(request, model), stream=True
                )
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                failure = _failure(exc)
                if not failure.retryable or failure.account_wide:
                    raise _Rejected(failure, model, exc) from exc
                if attempt < TRANSIENT_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

        raise _Rejected(failure, model, None)

    async def _attempt(
        self, request: ChatRequest, model: str, client: openai.AsyncOpenAI | None = None
    ) -> Any:
        """One model, retried while the failure looks transient.

        A transient failure is retried here rather than reported as "try again later", which
        is the caller's problem to solve and the caller cannot solve it. An account-wide
        failure — a rate limit — stops immediately: waiting is the correct response and a
        second request is the opposite of it.
        """
        failure = Failure(_GENERIC_FAILURE, retryable=True)

        for attempt in range(1, TRANSIENT_ATTEMPTS + 1):
            try:
                return await (client or self._client).chat.completions.create(
                    **self._payload(request, model)
                )
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                failure = _failure(exc)
                logger.warning(
                    "openai request failed",
                    extra={"model": model, "attempt": attempt, "detail": str(exc)[:200]},
                )
                if not failure.retryable or failure.account_wide:
                    raise _Rejected(failure, model, exc) from exc
                if attempt < TRANSIENT_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

        raise _Rejected(failure, model, None)

    async def complete(self, request: ChatRequest) -> ChatResult:
        """Try each key, and within a key each model, until one answers.

        Two loops because there are two kinds of failure. A model failure routes to another
        model on the same key; an account failure — no credit, revoked, rate limited — makes
        every model on that key fail identically, so it routes to another key instead.
        """
        failure = Failure(_GENERIC_FAILURE, retryable=True)
        clients = self._keys()

        for key_index, client in enumerate(clients):
            last_key = key_index == len(clients) - 1

            for index, model in enumerate(self._candidates()):
                last_model = index == len(self._candidates()) - 1
                try:
                    response = await self._attempt(request, model, client)
                except _Rejected as rejected:
                    failure = rejected.failure
                    if failure.account_wide:
                        # A rate limit counts per account, so every model on this key is
                        # throttled too. Another key is the only thing that helps.
                        break
                    if last_model:
                        break
                    # An empty balance is deliberately *not* account-wide here. It means the
                    # models that cost money cannot answer, and the free ones on the same key
                    # still can — which is the arrangement that keeps a zero-balance key
                    # useful, and the reason the fallback list exists at all.
                    logger.info("falling back to another model", extra={"from": model})
                    continue

                if key_index > 0 or index > 0:
                    logger.info(
                        "answered by a fallback",
                        extra={"model": model, "key": key_index, "configured": self._model},
                    )

                result = self._result(response, model)
                if result is not None:
                    return result

                # An empty answer is not an answer; try the next model on this key.
                failure = Failure("The AI service returned an empty answer.", retryable=False)
                if last_model:
                    break

            if last_key:
                raise ProviderUnavailableError(failure.message, detail="no candidate answered")
            logger.info("trying another API key", extra={"after_key": key_index})

        raise ProviderUnavailableError(failure.message, detail="no candidate answered")

    def _result(self, response: Any, model: str) -> ChatResult | None:
        """A completion, or None when the model returned nothing.

        Some models spend their whole token budget on internal reasoning and emit an empty
        string. Accepting that as success made the caller report "no JSON array in a response
        of 0 characters" rather than trying the next candidate.
        """
        choice = response.choices[0]
        text = choice.message.content or ""

        if not text.strip():
            logger.warning(
                "model returned nothing",
                extra={"model": model, "finish_reason": choice.finish_reason},
            )
            return None

        return ChatResult(
            text=text,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
            stopped_early=choice.finish_reason == "length",
        )


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
                    "Turex couldn't index that document right now. It will try again.",
                    detail=f"openai embeddings: {exc}",
                ) from exc

            # The API preserves input order, but the index is authoritative — relying on
            # position alone would silently mis-pair a vector with its chunk.
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)

        return vectors
