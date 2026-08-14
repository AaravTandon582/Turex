"""Research assistant tests.

The behaviour under test is the product's central promise: an answer is assembled from
passages actually retrieved from the user's library, every citation resolves to a real one,
and Atlas cannot be made to cite something it never read.

A scripted chat provider stands in for the model, so these assert on Atlas's behaviour rather
than on a model's output — including the case where the model misbehaves and writes a citation
marker for a source that does not exist.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.ai.base import ChatChunk, ChatProvider, ChatRequest, ChatResult, ChunkKind
from atlas.api.deps import get_assistant_service, get_db, get_retrieval_service
from atlas.models.conversation import ConversationMessage, MessageCitation, MessageRole
from atlas.retrieval.search import RetrievalService
from atlas.services.assistant_service import AssistantService
from tests.test_retrieval import TRANSFORMERS_PDF, upload_and_index


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


@pytest.fixture
def scripted(app, settings):  # type: ignore[no-untyped-def]
    """Install a scripted model, returning a handle to configure and inspect it."""
    holder: dict[str, ScriptedChatProvider] = {"provider": ScriptedChatProvider()}

    # Reuses the real database session and the real retrieval service; only the model is
    # replaced, so retrieval, persistence, and citation building are genuinely exercised.
    def factory(
        db: AsyncSession = Depends(get_db),
        retrieval: RetrievalService = Depends(get_retrieval_service),
    ) -> AssistantService:
        return AssistantService(db, retrieval, lambda: holder["provider"])

    app.dependency_overrides[get_assistant_service] = factory  # type: ignore[attr-defined]
    yield holder
    app.dependency_overrides.pop(get_assistant_service, None)  # type: ignore[attr-defined]


async def start_conversation(client: AsyncClient, api: str, **payload: object) -> str:
    response = await client.post(f"{api}/assistant/conversations", json=payload or {})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def ask(client: AsyncClient, api: str, conversation_id: str, question: str) -> list[str]:
    """Send a question and return the raw SSE frames."""
    async with client.stream(
        "POST",
        f"{api}/assistant/conversations/{conversation_id}/ask",
        json={"question": question},
    ) as response:
        assert response.status_code == 200, await response.aread()
        body = "".join([chunk async for chunk in response.aiter_text()])
    return [frame for frame in body.split("\n\n") if frame.strip()]


def frames_of(frames: Sequence[str], event: str) -> list[str]:
    return [frame for frame in frames if frame.startswith(f"event: {event}")]


class TestConversations:
    async def test_creates_and_lists(
        self, registered_client: AsyncClient, api: str, scripted
    ) -> None:
        conversation_id = await start_conversation(registered_client, api, mode="critique")

        listed = (await registered_client.get(f"{api}/assistant/conversations")).json()

        assert [c["id"] for c in listed] == [conversation_id]
        assert listed[0]["mode"] == "critique"
        assert listed[0]["title"] is None

    async def test_scoping_to_an_unknown_paper_is_rejected(
        self, registered_client: AsyncClient, api: str, scripted
    ) -> None:
        response = await registered_client.post(
            f"{api}/assistant/conversations",
            json={"paper_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert response.status_code == 404

    async def test_another_user_cannot_reach_a_conversation(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str, scripted
    ) -> None:
        conversation_id = await start_conversation(registered_client, api)

        response = await other_client.get(
            f"{api}/assistant/conversations/{conversation_id}/messages"
        )
        assert response.status_code == 404

    async def test_reports_which_features_are_configured(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """The UI needs to know before showing a chat box that would fail on first use."""
        status = (await registered_client.get(f"{api}/assistant/status")).json()

        assert status["chat_available"] is False, "no API key is set in tests"
        assert status["embeddings_available"] is True
        assert {mode["value"] for mode in status["modes"]} >= {"explain", "critique", "research"}


class TestAsking:
    async def test_streams_sources_before_any_prose(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        """The reader should see what the answer is built from before the answer arrives."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        conversation_id = await start_conversation(registered_client, api)

        frames = await ask(registered_client, api, conversation_id, "Why is inference slow?")

        assert frames[0].startswith("event: sources")
        assert frames_of(frames, "text")
        assert frames[-1].startswith("event: done")

    async def test_records_the_exchange(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        conversation_id = await start_conversation(registered_client, api)

        await ask(registered_client, api, conversation_id, "Why is inference slow?")

        messages = (
            await registered_client.get(f"{api}/assistant/conversations/{conversation_id}/messages")
        ).json()

        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "Why is inference slow?"
        assert "latency drops" in messages[1]["content"]

    async def test_titles_the_conversation_from_the_first_question(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        conversation_id = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation_id, "What limits inference speed?")

        listed = (await registered_client.get(f"{api}/assistant/conversations")).json()
        assert listed[0]["title"] == "What limits inference speed?"

    async def test_the_prompt_carries_the_retrieved_passages(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        """Grounding is a property of the prompt, not a claim in the system message."""
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        conversation_id = await start_conversation(registered_client, api)

        await ask(registered_client, api, conversation_id, "What did speculative decoding do?")

        prompt = scripted["provider"].last_prompt
        assert "SOURCES" in prompt
        assert "[1]" in prompt
        assert "speculative decoding" in prompt.lower()

    async def test_the_mode_selects_the_system_prompt(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        conversation_id = await start_conversation(registered_client, api, mode="critique")
        await ask(registered_client, api, conversation_id, "Assess the method.")

        system = scripted["provider"].requests[-1].system
        assert "critical evaluation" in system
        # The shared grounding rules are present in every mode.
        assert "fabricated citation" in system


class TestCitations:
    async def test_citations_come_from_retrieval(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        conversation_id = await start_conversation(registered_client, api)

        await ask(registered_client, api, conversation_id, "What reduced latency?")

        citations = list(await db.scalars(select(MessageCitation)))
        assert citations, "an answer over a non-empty library must record its sources"
        for citation in citations:
            # Each resolves to a real chunk of a real paper, with a locator.
            assert citation.chunk_id is not None
            assert citation.paper_id is not None
            assert citation.locator
            assert citation.quoted_text.strip()

    async def test_a_fabricated_marker_creates_no_citation(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        """The model writes [9] when far fewer sources were supplied.

        Atlas must not manufacture a ninth source. Citations are built from what retrieval
        returned, so the invented marker simply has nothing behind it.
        """
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(
            answer="As established in [9] and [42], this is certain."
        )
        conversation_id = await start_conversation(registered_client, api)

        await ask(registered_client, api, conversation_id, "What reduced latency?")

        citations = list(await db.scalars(select(MessageCitation)))
        assert all(citation.marker <= len(citations) for citation in citations)
        assert not any(citation.marker in (9, 42) for citation in citations)
        assert all(citation.used_in_answer is False for citation in citations)

    async def test_records_which_sources_the_answer_actually_used(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        scripted["provider"] = ScriptedChatProvider(answer="Quantisation helps [1].")
        conversation_id = await start_conversation(registered_client, api)

        await ask(registered_client, api, conversation_id, "What reduced latency?")

        citations = {c.marker: c for c in await db.scalars(select(MessageCitation))}
        assert citations[1].used_in_answer is True
        for marker, citation in citations.items():
            if marker != 1:
                assert citation.used_in_answer is False

    async def test_an_empty_library_produces_no_citations(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        conversation_id = await start_conversation(registered_client, api)

        await ask(registered_client, api, conversation_id, "What does the literature say?")

        assert list(await db.scalars(select(MessageCitation))) == []

    async def test_an_empty_library_tells_the_model_to_say_so(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        conversation_id = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation_id, "What does the literature say?")

        prompt = scripted["provider"].last_prompt
        assert "general knowledge" in prompt

    async def test_citations_are_returned_with_the_message(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        conversation_id = await start_conversation(registered_client, api)
        await ask(registered_client, api, conversation_id, "What reduced latency?")

        messages = (
            await registered_client.get(f"{api}/assistant/conversations/{conversation_id}/messages")
        ).json()

        citations = messages[1]["citations"]
        assert citations
        assert all(c["paper_title"] and c["locator"] for c in citations)


class TestFailures:
    async def test_a_model_failure_keeps_the_question(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,
        db: AsyncSession,  # type: ignore[no-untyped-def]
    ) -> None:
        """Losing the user's question along with the error is the worst possible outcome."""
        scripted["provider"] = ScriptedChatProvider(fail="Atlas couldn't reach the AI service.")
        conversation_id = await start_conversation(registered_client, api)

        frames = await ask(registered_client, api, conversation_id, "Why is this slow?")

        assert frames_of(frames, "error")
        messages = list(
            await db.scalars(select(ConversationMessage).order_by(ConversationMessage.created_at))
        )
        assert messages[0].role is MessageRole.user
        assert messages[0].content == "Why is this slow?"
        assert messages[1].error_message is not None

    async def test_a_failure_message_is_safe_to_display(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        scripted["provider"] = ScriptedChatProvider(fail="Atlas couldn't reach the AI service.")
        conversation_id = await start_conversation(registered_client, api)

        frames = await ask(registered_client, api, conversation_id, "Why?")

        error = frames_of(frames, "error")[0]
        assert "Traceback" not in error
        assert "anthropic" not in error.lower()

    async def test_a_failed_turn_is_not_replayed_as_history(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        """Replaying an empty answer teaches the model that empty answers are acceptable."""
        conversation_id = await start_conversation(registered_client, api)
        scripted["provider"] = ScriptedChatProvider(fail="Something went wrong.")
        await ask(registered_client, api, conversation_id, "First question?")

        scripted["provider"] = ScriptedChatProvider(answer="A real answer.")
        await ask(registered_client, api, conversation_id, "Second question?")

        history = scripted["provider"].requests[-1].messages
        assert not any(message.content == "" for message in history)

    async def test_rejects_an_empty_question(
        self,
        registered_client: AsyncClient,
        api: str,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        conversation_id = await start_conversation(registered_client, api)

        response = await registered_client.post(
            f"{api}/assistant/conversations/{conversation_id}/ask", json={"question": "   "}
        )
        assert response.status_code == 422

    async def test_another_user_cannot_ask_in_a_conversation(
        self,
        registered_client: AsyncClient,
        other_client: AsyncClient,
        api: str,
        scripted,  # type: ignore[no-untyped-def]
    ) -> None:
        conversation_id = await start_conversation(registered_client, api)

        async with other_client.stream(
            "POST",
            f"{api}/assistant/conversations/{conversation_id}/ask",
            json={"question": "Show me their research."},
        ) as response:
            body = (await response.aread()).decode()

        # The stream opens before ownership is known, so the refusal arrives as a frame.
        assert "event: error" in body or response.status_code == 404
        assert "Show me their research" not in body
