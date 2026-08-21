"""What Atlas says and does when a model call fails.

Every upstream failure used to arrive as one sentence — *"Atlas couldn't reach the AI
service. Try again in a moment."* — which is true of a dropped connection and false of
everything else. A key whose credits had run out answered `402` on every request, Atlas
reported a reachability problem, and a working feature looked like broken code.

So these check two things the classifier and the fallback chain exist for: that the message
names the real problem, and that a model which cannot answer is stepped over rather than
becoming the final word.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from atlas.ai.base import ChatMessage, ChatRequest, ChunkKind, Role
from atlas.ai.failures import classify
from atlas.ai.openai_provider import OpenAIChatProvider
from atlas.core.errors import ProviderUnavailableError

REQUEST = ChatRequest(
    system="be brief",
    messages=[ChatMessage(role=Role.user, content="hello")],
    max_output_tokens=64,
)


def _status_error(status: int, body: str = "") -> openai.APIStatusError:
    """The error shape the OpenAI SDK raises for an HTTP status."""
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status, request=request, text=body or f"status {status}")
    return openai.APIStatusError(body or f"status {status}", response=response, body=None)


class _Completions:
    """Answers from a script, one entry per call, so a fallback chain can be driven."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.models: list[str] = []

    async def create(self, **payload: Any) -> Any:
        self.models.append(payload["model"])
        answer = self.script.pop(0) if self.script else _status_error(500)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _reply(text: str | None, finish_reason: str = "stop") -> Any:
    """The parts of a completion the provider reads, and nothing else."""
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


async def _streamed(text: str) -> Any:
    """A stream yielding one delta, in the shape the SDK produces."""

    class Stream:
        async def __aiter__(self) -> Any:
            choice = SimpleNamespace(delta=SimpleNamespace(content=text))
            yield SimpleNamespace(choices=[choice])

    return Stream()


def _provider(script: list[Any], fallbacks: tuple[str, ...] = ()) -> tuple[Any, _Completions]:
    provider = OpenAIChatProvider(
        api_key="test-key", model="primary/model", fallback_models=fallbacks
    )
    completions = _Completions(script)
    provider._client.chat.completions = completions  # type: ignore[assignment]
    return provider, completions


def _multi_key(script: list[Any], keys: int = 2, fallbacks: tuple[str, ...] = ()):  # type: ignore[no-untyped-def]
    """A provider with several keys, all sharing one script so the order of attempts is
    visible as a single sequence."""
    provider = OpenAIChatProvider(
        api_key="key-0",
        model="primary/model",
        fallback_models=fallbacks,
        extra_api_keys=tuple(f"key-{index}" for index in range(1, keys)),
    )
    completions = _Completions(script)
    for client in provider._clients:
        client.chat.completions = completions  # type: ignore[assignment]
    return provider, completions


class TestTheMessageNamesTheRealProblem:
    def test_an_empty_balance_says_so_and_says_retrying_will_not_help(self) -> None:
        """The failure that started this: reported as unreachable for an entire session."""
        failure = classify(402, "Insufficient credits. Add more using ...")
        assert "credit" in failure.message.lower()
        assert failure.retryable is False
        assert failure.exhausted is True

    def test_an_empty_balance_is_recognised_from_the_body_when_the_status_lies(self) -> None:
        """Some gateways answer 429 or 500 for an empty balance, and only the body says so."""
        assert classify(429, "You exceeded your current quota").exhausted is True

    def test_a_rejected_key_names_the_variable_to_check(self) -> None:
        failure = classify(401)
        assert "OPENAI_API_KEY" in failure.message
        assert failure.retryable is False

    def test_an_unknown_model_names_the_variable_to_check(self) -> None:
        assert "OPENAI_MODEL" in classify(404).message

    def test_a_rate_limit_is_the_one_worth_waiting_out(self) -> None:
        failure = classify(429)
        assert failure.retryable is True
        assert failure.exhausted is False

    @pytest.mark.parametrize("status", [500, 502, 503, None])
    def test_a_service_fault_keeps_the_original_wording(self, status: int | None) -> None:
        """It was the right message all along — for this case only."""
        failure = classify(status)
        assert "couldn't reach" in failure.message
        assert failure.retryable is True

    def test_a_request_that_is_too_large_is_not_retried(self) -> None:
        assert classify(413).retryable is False


class TestTheFallbackChain:
    async def test_a_model_with_no_credit_is_stepped_over(self) -> None:
        provider, completions = _provider(
            [_status_error(402, "Insufficient credits"), _reply("an answer")],
            fallbacks=("spare/model",),
        )
        result = await provider.complete(REQUEST)

        assert result.text == "an answer"
        assert completions.models == ["primary/model", "spare/model"]

    async def test_an_empty_answer_is_not_an_answer(self) -> None:
        """A model that spends its whole budget on internal reasoning emits nothing. Accepting
        that as success made the caller report "no JSON array in a response of 0 characters"
        instead of trying the next model."""
        provider, completions = _provider(
            [_reply(""), _reply("a real answer")], fallbacks=("spare/model",)
        )
        assert (await provider.complete(REQUEST)).text == "a real answer"
        assert completions.models == ["primary/model", "spare/model"]

    async def test_a_rate_limit_does_not_trigger_a_fallback(self) -> None:
        """A rate limit is the account being throttled, not the model. Another model is another
        request against the same limit — the opposite of backing off."""
        provider, completions = _provider([_status_error(429)], fallbacks=("spare/model",))

        # `str(exc)` is the internal detail; `.message` is what the reader is shown. Asserting
        # on the latter is the point — the detail may name a status code, the message may not.
        with pytest.raises(ProviderUnavailableError) as raised:
            await provider.complete(REQUEST)
        assert "rate limited" in raised.value.message
        assert completions.models == ["primary/model"], "no retry, no fallback: just wait"

    async def test_a_transient_failure_is_actually_retried(self) -> None:
        """Classifying a failure as retryable and then not retrying it is worse than not
        classifying it — the caller is told to try again while the code that could have tried
        gave up. Every request after the first died on "Connection error" that way."""
        provider, completions = _provider(
            [_status_error(503), _status_error(503), _reply("recovered")]
        )
        assert (await provider.complete(REQUEST)).text == "recovered"
        assert completions.models == ["primary/model"] * 3

    async def test_a_model_that_keeps_dropping_falls_through_to_the_next(self) -> None:
        """A connection that keeps failing may be *that model's* upstream rather than the
        service. One flaky primary model otherwise fails every request while working
        fallbacks sit unused, which is exactly what happened."""
        provider, completions = _provider(
            [_status_error(503), _status_error(503), _status_error(503), _reply("from the spare")],
            fallbacks=("spare/model",),
        )
        assert (await provider.complete(REQUEST)).text == "from the spare"
        assert completions.models == ["primary/model"] * 3 + ["spare/model"]

    async def test_the_last_candidate_reports_rather_than_looping(self) -> None:
        provider, completions = _provider(
            [_status_error(402), _status_error(402)], fallbacks=("spare/model",)
        )
        with pytest.raises(ProviderUnavailableError) as raised:
            await provider.complete(REQUEST)
        assert "credit" in raised.value.message
        assert completions.models == ["primary/model", "spare/model"]

    async def test_no_fallbacks_configured_means_the_first_failure_is_final(self) -> None:
        provider, completions = _provider([_status_error(402)])
        with pytest.raises(ProviderUnavailableError):
            await provider.complete(REQUEST)
        assert completions.models == ["primary/model"]


class TestStreaming:
    @staticmethod
    async def _collect(provider: Any) -> list[Any]:
        return [chunk async for chunk in provider.stream(REQUEST)]

    async def test_a_stream_falls_back_before_the_first_token(self) -> None:
        provider, completions = _provider(
            [_status_error(402), await _streamed("hello")], fallbacks=("spare/model",)
        )
        chunks = await self._collect(provider)

        assert [chunk.text for chunk in chunks if chunk.kind is ChunkKind.text] == ["hello"]
        assert completions.models == ["primary/model", "spare/model"]

    async def test_a_stream_reports_the_real_reason(self) -> None:
        provider, _ = _provider([_status_error(402, "Insufficient credits")])
        [error] = [c for c in await self._collect(provider) if c.kind is ChunkKind.error]
        assert "credit" in error.text.lower()


class TestKeyRotation:
    """Keys and models rotate independently, because they fail for different reasons."""

    async def test_a_rate_limited_key_moves_to_the_next_key(self) -> None:
        """A rate limit counts per account, so every model on that key is throttled too."""
        provider, completions = _multi_key(
            [_status_error(429), _reply("from the second key")], fallbacks=("spare/model",)
        )
        result = await provider.complete(REQUEST)

        assert result.text == "from the second key"
        # The spare *model* is never tried on the first key: it would be another request
        # against the same limit.
        assert completions.models == ["primary/model", "primary/model"]

    async def test_an_empty_balance_tries_the_free_models_before_another_key(self) -> None:
        """The arrangement that keeps a spent key useful: paid models stop, free ones do not."""
        provider, completions = _multi_key(
            [_status_error(402, "Insufficient credits"), _reply("from a free model")],
            fallbacks=("free/model",),
        )
        result = await provider.complete(REQUEST)

        assert result.text == "from a free model"
        assert completions.models == ["primary/model", "free/model"], "same key, next model"

    async def test_every_key_exhausted_reports_rather_than_looping(self) -> None:
        provider, completions = _multi_key([_status_error(429)] * 4, keys=2)

        with pytest.raises(ProviderUnavailableError) as raised:
            await provider.complete(REQUEST)
        assert "rate limited" in raised.value.message
        assert completions.models == ["primary/model", "primary/model"]

    async def test_one_key_behaves_exactly_as_before(self) -> None:
        """Adding the dimension must not change the single-key path, which is every existing
        deployment."""
        provider, completions = _multi_key(
            [_status_error(402), _reply("answered")], keys=1, fallbacks=("spare/model",)
        )
        assert (await provider.complete(REQUEST)).text == "answered"
        assert completions.models == ["primary/model", "spare/model"]

    def test_duplicate_keys_are_not_tried_twice(self) -> None:
        """`ATLAS_OPENAI_API_KEYS` repeating the primary key is an easy mistake and would
        otherwise double every failure path for no benefit."""
        provider = OpenAIChatProvider(
            api_key="same", model="m", extra_api_keys=("same", "different")
        )
        assert len(provider._clients) == 2
