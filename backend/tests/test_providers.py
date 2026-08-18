"""How a provider is chosen and configured.

These matter because a misconfiguration here fails at the worst moment — the first time
someone asks a question — and the failure modes look alike. A wrong base URL, a missing key,
and an unknown provider name all surface as "the assistant isn\'t working".
"""

from __future__ import annotations

import pytest

from atlas.ai.registry import ProviderRegistry
from atlas.core.config import Settings
from atlas.core.errors import NotConfiguredError

HACK_CLUB = "https://ai.hackclub.com/proxy/v1"


def settings_with(**overrides: object) -> Settings:
    """Build settings from these values alone.

    `_env_file=None` matters: without it pydantic-settings reads the developer's own `.env`,
    and these tests silently start asserting against whatever key and base URL happen to be
    configured on the machine running them. That is exactly what happened the first time a
    real key was added — two tests that had always passed began failing for a reason that had
    nothing to do with the code.
    """
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://localhost/atlas_test",
        "secret_key": "a-test-secret-key-that-is-long-enough",
    }
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


class TestOpenAICompatibleServices:
    """Any service speaking the OpenAI wire format is reachable by base URL alone."""

    def test_the_base_url_reaches_the_client(self) -> None:
        registry = ProviderRegistry(
            settings_with(
                chat_provider="openai",
                openai_api_key="a-test-key",
                openai_base_url=HACK_CLUB,
                openai_model="anthropic/claude-opus-5",
            )
        )
        provider = registry.chat()
        assert str(provider._client.base_url).rstrip("/") == HACK_CLUB  # type: ignore[attr-defined]

    def test_a_vendor_qualified_model_name_is_passed_through_unchanged(self) -> None:
        """These services namespace their models. Rewriting the name would break every one."""
        registry = ProviderRegistry(
            settings_with(
                chat_provider="openai",
                openai_api_key="a-test-key",
                openai_base_url=HACK_CLUB,
                openai_model="anthropic/claude-opus-5",
            )
        )
        assert registry.chat()._model == "anthropic/claude-opus-5"  # type: ignore[attr-defined]

    def test_an_unset_base_url_leaves_the_sdk_default_alone(self) -> None:
        """A plain OpenAI deployment must be unaffected by the option existing."""
        registry = ProviderRegistry(
            settings_with(chat_provider="openai", openai_api_key="a-test-key")
        )
        assert "openai.com" in str(registry.chat()._client.base_url)  # type: ignore[attr-defined]

    def test_the_embedder_honours_the_same_base_url(self) -> None:
        registry = ProviderRegistry(
            settings_with(
                embedding_provider="openai",
                openai_api_key="a-test-key",
                openai_base_url=HACK_CLUB,
            )
        )
        assert str(registry.embedder()._client.base_url).rstrip("/") == HACK_CLUB  # type: ignore[attr-defined]


class TestMisconfigurationIsExplicit:
    def test_a_missing_key_names_the_variable_that_is_missing(self) -> None:
        registry = ProviderRegistry(settings_with(chat_provider="openai", openai_api_key=None))
        with pytest.raises(NotConfiguredError) as caught:
            registry.chat()
        assert "OPENAI_API_KEY" in (caught.value.detail or "")

    def test_an_unknown_provider_name_is_refused_rather_than_guessed(self) -> None:
        registry = ProviderRegistry(settings_with(chat_provider="hackclub"))
        with pytest.raises(NotConfiguredError):
            registry.chat()

    def test_availability_is_reported_without_constructing_a_client(self) -> None:
        """The status endpoint must answer on a deployment with no key configured."""
        assert ProviderRegistry(settings_with(chat_provider="openai")).chat_available is False
        assert (
            ProviderRegistry(
                settings_with(chat_provider="openai", openai_api_key="a-test-key")
            ).chat_available
            is True
        )
