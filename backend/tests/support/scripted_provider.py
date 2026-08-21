"""A chat model that says exactly what a test tells it to.

Shared by the assistant suite and the evaluation suite: both need to drive the model into
specific misbehaviour, and a second copy would drift from the first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from turex.ai.base import ChatChunk, ChatProvider, ChatRequest, ChatResult, ChunkKind


class ScriptedChatProvider(ChatProvider):
    """Emits a fixed answer and records the request it was given."""

    name = "scripted"

    def __init__(self, *, answer: str = "The latency drops [1].", fail: str | None = None) -> None:
        self._answer = answer
        self._fail = fail
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        self.requests.append(request)
        if self._fail:
            yield ChatChunk(ChunkKind.error, self._fail)
            return
        # Split into fragments so the test exercises accumulation, not a single blob.
        for word in self._answer.split(" "):
            yield ChatChunk(ChunkKind.text, word + " ")
        yield ChatChunk(ChunkKind.done)

    async def complete(self, request: ChatRequest) -> ChatResult:
        self.requests.append(request)
        return ChatResult(text=self._answer)

    @property
    def last_prompt(self) -> str:
        return self.requests[-1].messages[-1].content
