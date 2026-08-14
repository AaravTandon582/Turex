"""Anthropic chat provider.

Everything vendor-specific about talking to Claude lives here: SDK calls, streaming events,
error translation, and refusal handling. The rest of Atlas sees only `ChatProvider`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

from atlas.ai.base import (
    ChatChunk,
    ChatMessage,
    ChatProvider,
    ChatRequest,
    ChatResult,
    ChunkKind,
    Usage,
)
from atlas.core.errors import ProviderDeclinedError, ProviderUnavailableError
from atlas.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-opus-5"

FALLBACK_BETA = "server-side-fallback-2026-07-01"
"""Server-side fallbacks. Claude's safety classifiers can decline a request outright, and
benign security or life-sciences reading occasionally trips one. `fallbacks: "default"` has
the API re-run a declined request on a suitable model inside the same call, routed by refusal
category, so a legitimate research question is answered rather than refused."""

_GENERIC_FAILURE = "Atlas couldn't reach the AI service. Try again in a moment."


class AnthropicChatProvider(ChatProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        adaptive_thinking: bool = True,
        server_side_fallbacks: bool = True,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._adaptive_thinking = adaptive_thinking
        self._fallbacks = server_side_fallbacks

    # -- request construction -----------------------------------------------------

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_output_tokens,
            # The system prompt is byte-stable per mode, so caching it makes every turn after
            # the first in a conversation markedly cheaper.
            "system": [
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [_to_wire(message) for message in request.messages],
        }

        if self._adaptive_thinking:
            # Claude decides how much to think per turn. `max_tokens` bounds thinking and
            # answer together, which is why the caller's budget is generous.
            payload["thinking"] = {"type": "adaptive"}

        if request.effort:
            payload["output_config"] = {"effort": request.effort}

        if self._fallbacks:
            payload["betas"] = [FALLBACK_BETA]
            # Sent through extra_body so this works regardless of whether the installed SDK
            # has typed the parameter yet; the API reads it from the request body either way.
            payload["extra_body"] = {"fallbacks": "default"}

        return payload

    # -- streaming ------------------------------------------------------------------

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        try:
            async with self._client.beta.messages.stream(**self._payload(request)) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield ChatChunk(ChunkKind.text, text)

                final = await stream.get_final_message()

            # Checked after the stream closes: a refusal can arrive with no text at all, and
            # reading content without checking would surface an empty answer as a real one.
            if final.stop_reason == "refusal":
                logger.info(
                    "model declined the request",
                    extra={"category": getattr(final.stop_details, "category", None)},
                )
                yield ChatChunk(
                    ChunkKind.error,
                    "Atlas can't help with that particular request.",
                )
                return

            if final.stop_reason == "max_tokens":
                # The answer is real but cut off. Say so rather than letting it end mid-word.
                yield ChatChunk(
                    ChunkKind.text,
                    "\n\n_This answer was cut short. Ask a narrower question for the rest._",
                )

            yield ChatChunk(ChunkKind.done)

        except anthropic.APIStatusError as exc:
            yield self._failure_chunk(exc, status=exc.status_code)
        except anthropic.APIConnectionError as exc:
            logger.warning("anthropic connection failed", extra={"detail": str(exc)})
            yield ChatChunk(ChunkKind.error, _GENERIC_FAILURE)

    def _failure_chunk(self, exc: Exception, *, status: int) -> ChatChunk:
        if status == 429:
            logger.warning("anthropic rate limited")
            return ChatChunk(ChunkKind.error, "Atlas is being rate limited. Try again in a moment.")
        if status == 401 or status == 403:
            # A misconfigured key is an operator problem, not something the reader can act on.
            logger.error("anthropic rejected our credentials", extra={"status": status})
            return ChatChunk(ChunkKind.error, "Atlas isn't configured to reach the AI service.")
        logger.error("anthropic request failed", extra={"status": status, "detail": str(exc)})
        return ChatChunk(ChunkKind.error, _GENERIC_FAILURE)

    # -- non-streaming ----------------------------------------------------------------

    async def complete(self, request: ChatRequest) -> ChatResult:
        try:
            message = await self._client.beta.messages.create(**self._payload(request))
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailableError(detail=f"anthropic {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(detail=f"anthropic connection: {exc}") from exc

        if message.stop_reason == "refusal":
            raise ProviderDeclinedError(
                "Atlas can't help with that particular request.",
                detail=f"refusal category {getattr(message.stop_details, 'category', None)}",
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        return ChatResult(
            text=text,
            usage=Usage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
            ),
            stopped_early=message.stop_reason == "max_tokens",
        )


def _to_wire(message: ChatMessage) -> dict[str, str]:
    return {"role": message.role.value, "content": message.content}


def build_messages(turns: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [_to_wire(turn) for turn in turns]
