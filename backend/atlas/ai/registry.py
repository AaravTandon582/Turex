"""Choosing providers from configuration.

Constructed once per process and cached. Atlas runs with no provider keys at all — features
that need a model report themselves unavailable rather than failing at the point of use, so a
contributor can work on the library without an account anywhere.
"""

from __future__ import annotations

from atlas.ai.base import ChatProvider, EmbeddingProvider
from atlas.ai.local_embedder import HashingEmbeddingProvider
from atlas.core.config import Environment, Settings
from atlas.core.errors import NotConfiguredError
from atlas.core.logging import get_logger

logger = get_logger(__name__)

LOCAL_EMBEDDING_PROVIDER = "local"


class ProviderRegistry:
    """Resolves the configured chat and embedding providers."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._chat: ChatProvider | None = None
        self._embedder: EmbeddingProvider | None = None

    # -- chat --------------------------------------------------------------------

    @property
    def chat_available(self) -> bool:
        match self._settings.chat_provider:
            case "anthropic":
                return bool(self._settings.anthropic_api_key)
            case "openai":
                return bool(self._settings.openai_api_key)
            case _:
                return False

    def chat(self) -> ChatProvider:
        if self._chat is not None:
            return self._chat

        settings = self._settings
        match settings.chat_provider:
            case "anthropic":
                if not settings.anthropic_api_key:
                    raise NotConfiguredError(
                        "The research assistant isn't set up on this Atlas instance yet.",
                        detail="ANTHROPIC_API_KEY is not set",
                    )
                from atlas.ai.anthropic_provider import AnthropicChatProvider

                self._chat = AnthropicChatProvider(
                    api_key=settings.anthropic_api_key,
                    model=settings.anthropic_model,
                )
            case "openai":
                if not settings.openai_api_key:
                    raise NotConfiguredError(
                        "The research assistant isn't set up on this Atlas instance yet.",
                        detail="OPENAI_API_KEY is not set",
                    )
                from atlas.ai.openai_provider import OpenAIChatProvider

                self._chat = OpenAIChatProvider(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    base_url=settings.openai_base_url,
                    fallback_models=settings.openai_fallback_models,
                )
            case unknown:
                raise NotConfiguredError(detail=f"unknown chat provider {unknown!r}")

        logger.info(
            "chat provider ready",
            extra={
                "provider": self._chat.name,
                "model": settings.openai_model
                if settings.chat_provider == "openai"
                else settings.anthropic_model,
                # Worth logging: a wrong base URL fails in ways that look like a bad key.
                "base_url": settings.openai_base_url or "default",
            },
        )
        return self._chat

    # -- embeddings ---------------------------------------------------------------

    @property
    def embeddings_available(self) -> bool:
        if self._settings.embedding_provider == LOCAL_EMBEDDING_PROVIDER:
            return True
        return bool(self._settings.openai_api_key)

    def embedder(self) -> EmbeddingProvider:
        if self._embedder is not None:
            return self._embedder

        settings = self._settings
        if settings.embedding_provider == LOCAL_EMBEDDING_PROVIDER:
            if settings.environment is not Environment.test:
                logger.warning(
                    "using the local hashing embedder — it matches vocabulary, not meaning, "
                    "so semantic search will miss paraphrase. Set OPENAI_API_KEY for real "
                    "embeddings."
                )
            self._embedder = HashingEmbeddingProvider(dimensions=settings.embedding_dimensions)
        elif settings.embedding_provider == "openai":
            if not settings.openai_api_key:
                raise NotConfiguredError(
                    "Semantic search isn't set up on this Atlas instance yet.",
                    detail="OPENAI_API_KEY is not set",
                )
            from atlas.ai.openai_provider import OpenAIEmbeddingProvider

            self._embedder = OpenAIEmbeddingProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
                dimensions=settings.embedding_dimensions,
                base_url=settings.openai_base_url,
            )
        else:
            raise NotConfiguredError(
                detail=f"unknown embedding provider {settings.embedding_provider!r}"
            )

        logger.info(
            "embedding provider ready",
            extra={"provider": self._embedder.name, "dimensions": self._embedder.dimensions},
        )
        return self._embedder


_registry: ProviderRegistry | None = None


def get_registry(settings: Settings) -> ProviderRegistry:
    """The process-wide registry.

    Cached by hand rather than with `lru_cache`, because `Settings` is a Pydantic model and
    is not hashable — and because a provider holds an HTTP client whose connection pool
    should be shared across requests, not rebuilt per call.
    """
    global _registry
    if _registry is None:
        _registry = ProviderRegistry(settings)
    return _registry


def reset_registry() -> None:
    """Drop the cached registry. Used by tests that swap providers."""
    global _registry
    _registry = None
