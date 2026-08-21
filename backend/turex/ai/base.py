"""Provider-neutral interfaces for language and embedding models.

Two interfaces, not one. They are separate because the vendor sets differ — Anthropic has no
embedding model — so a single "AI provider" abstraction would need an exception on its first
day. See `docs/decisions.md` D3.

Nothing above this module imports a vendor SDK. A provider is chosen once, from configuration,
and everything downstream depends only on what is defined here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    user = "user"
    assistant = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """One turn, fully specified.

    `system` is separate from `messages` because every provider treats it separately, and
    because keeping it stable across a conversation is what makes prompt caching work.
    """

    system: str
    messages: Sequence[ChatMessage]
    max_output_tokens: int = 4096
    effort: str | None = None
    """Reasoning depth, where the provider supports it. Higher for critique, lower for
    quick explanations — set per assistant mode."""


class ChunkKind(StrEnum):
    text = "text"
    """A piece of the answer, to append to what the user is reading."""

    done = "done"
    """The turn finished normally."""

    error = "error"
    """The turn failed. `text` carries a message safe to display."""


@dataclass(frozen=True, slots=True)
class ChatChunk:
    kind: ChunkKind
    text: str = ""


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class ChatResult:
    """What a completed turn produced, for logging and cost tracking."""

    text: str = ""
    usage: Usage = field(default_factory=Usage)
    stopped_early: bool = False
    """True when the model hit its output limit rather than finishing its answer."""


class ChatProvider(ABC):
    """A streaming text model."""

    name: str

    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Yield the answer as it is produced.

        Streaming is not an optimisation here. A grounded answer over several papers takes
        many seconds, and a reader who sees nothing for that long assumes the product is
        broken.

        Implementations must translate provider faults into `ProviderUnavailableError` or
        `ProviderDeclinedError` rather than leaking an SDK exception upward.
        """

    @abstractmethod
    async def complete(self, request: ChatRequest) -> ChatResult:
        """Run a turn to completion. For internal work with no reader waiting."""


class EmbeddingProvider(ABC):
    """A text embedding model."""

    name: str
    dimensions: int

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch, returning one vector per input in the same order.

        Batched because embedding a paper means hundreds of chunks, and one request per
        chunk would be both slow and needlessly expensive.
        """

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
