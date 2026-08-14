"""Study mode tests.

The thing worth testing here is not that a model can write a flashcard — it is that Atlas
refuses to store one that is not attached to a real passage of the user's paper. The scripted
model is therefore driven deliberately off the rails: it cites passage numbers it was never
shown, wraps its reply in Markdown, returns truncated JSON, and returns prose instead of JSON.

The scheduling half is pure arithmetic and tested directly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.ai.base import ChatChunk, ChatProvider, ChatRequest, ChatResult
from atlas.ai.structured import parse_items
from atlas.api.deps import get_db, get_study_service
from atlas.models.study import ReviewRating
from atlas.services.study_service import GeneratedCard, StudyService
from atlas.study.scheduling import MINIMUM_EASE, STARTING_EASE, next_schedule
from tests.test_retrieval import TRANSFORMERS_PDF, upload_and_index


class ScriptedGenerator(ChatProvider):
    """Returns whatever text it is told to, and records what it was asked."""

    name = "scripted"

    def __init__(self, reply: str = "[]") -> None:
        self.reply = reply
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        raise AssertionError("study generation must not stream")
        yield  # pragma: no cover - makes this an async generator

    async def complete(self, request: ChatRequest) -> ChatResult:
        self.requests.append(request)
        return ChatResult(text=self.reply)

    @property
    def last_prompt(self) -> str:
        return self.requests[-1].messages[-1].content


@pytest.fixture
def generator(app):  # type: ignore[no-untyped-def]
    """Install a scripted model behind the real study service."""
    holder: dict[str, ScriptedGenerator] = {"provider": ScriptedGenerator()}

    def factory(db: AsyncSession = Depends(get_db)) -> StudyService:
        return StudyService(db, lambda: holder["provider"])

    app.dependency_overrides[get_study_service] = factory  # type: ignore[attr-defined]
    yield holder
    app.dependency_overrides.pop(get_study_service, None)  # type: ignore[attr-defined]


def cards_json(*entries: dict[str, object]) -> str:
    return json.dumps(list(entries))


def a_card(source: int = 1, front: str = "What reduced the latency?") -> dict[str, object]:
    return {
        "front": front,
        "back": "Key-value cache quantisation and speculative decoding.",
        "kind": "finding",
        "source": source,
    }


def a_question(source: int = 1) -> dict[str, object]:
    return {
        "question": "By how much did median latency fall?",
        "options": ["Thirty-one percent", "Ten percent", "Half", "It rose"],
        "answer": 0,
        "explanation": "The abstract reports a thirty-one percent reduction.",
        "source": source,
    }


class TestScheduling:
    def test_first_good_review_schedules_a_day_out(self) -> None:
        schedule = next_schedule(
            ease=STARTING_EASE, interval_days=0, rating=ReviewRating.good, now=_NOW
        )
        assert schedule.interval_days == 1
        assert schedule.due_at == _NOW + timedelta(days=1)

    def test_intervals_grow_with_successful_recall(self) -> None:
        ease, interval = STARTING_EASE, 0
        seen = []
        for _ in range(5):
            schedule = next_schedule(
                ease=ease, interval_days=interval, rating=ReviewRating.good, now=_NOW
            )
            ease, interval = schedule.ease, schedule.interval_days
            seen.append(interval)

        assert seen == sorted(seen), seen
        assert seen[-1] > seen[0]

    def test_forgetting_resets_the_interval_and_counts_a_lapse(self) -> None:
        schedule = next_schedule(
            ease=STARTING_EASE, interval_days=40, rating=ReviewRating.forgot, now=_NOW
        )
        assert schedule.interval_days == 0
        assert schedule.due_at == _NOW
        assert schedule.lapsed is True
        assert schedule.ease < STARTING_EASE

    def test_ease_never_falls_below_the_floor(self) -> None:
        ease = STARTING_EASE
        for _ in range(20):
            ease = next_schedule(
                ease=ease, interval_days=5, rating=ReviewRating.forgot, now=_NOW
            ).ease
        assert ease == MINIMUM_EASE

    def test_easy_outpaces_hard(self) -> None:
        easy = next_schedule(
            ease=STARTING_EASE, interval_days=10, rating=ReviewRating.easy, now=_NOW
        )
        hard = next_schedule(
            ease=STARTING_EASE, interval_days=10, rating=ReviewRating.hard, now=_NOW
        )
        assert easy.interval_days > hard.interval_days
        assert easy.ease > hard.ease


class TestStructuredParsing:
    def test_reads_a_plain_array(self) -> None:
        assert len(parse_items(cards_json(a_card(), a_card()), GeneratedCard)) == 2

    def test_reads_through_a_markdown_fence(self) -> None:
        fenced = f"```json\n{cards_json(a_card())}\n```"
        assert len(parse_items(fenced, GeneratedCard)) == 1

    def test_reads_through_surrounding_prose(self) -> None:
        chatty = f"Here are your cards:\n\n{cards_json(a_card())}\n\nHope these help!"
        assert len(parse_items(chatty, GeneratedCard)) == 1

    def test_keeps_valid_entries_and_drops_broken_ones(self) -> None:
        mixed = cards_json(a_card(), {"front": "x"}, a_card(front="Another question here?"))
        assert len(parse_items(mixed, GeneratedCard)) == 2

    def test_brackets_inside_strings_do_not_end_the_array(self) -> None:
        card = a_card(front="What does the notation [i, j] mean in the paper?")
        assert len(parse_items(cards_json(card), GeneratedCard)) == 1

    def test_a_truncated_response_is_a_failure_not_an_empty_deck(self) -> None:
        from atlas.core.errors import ProviderUnavailableError

        truncated = cards_json(a_card())[:-40]
        with pytest.raises(ProviderUnavailableError):
            parse_items(truncated, GeneratedCard)

    def test_prose_with_no_json_is_a_failure(self) -> None:
        from atlas.core.errors import ProviderUnavailableError

        with pytest.raises(ProviderUnavailableError):
            parse_items("I'd be happy to help with that!", GeneratedCard)


@pytest.mark.usefixtures("generator")
class TestFlashcardGeneration:
    async def test_cards_are_stored_with_the_passage_they_came_from(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card(), a_card(front="What is quantised?"))

        response = await registered_client.post(
            f"{api}/papers/{paper_id}/flashcards", json={"count": 5}
        )

        assert response.status_code == 201, response.text
        cards = response.json()
        assert len(cards) == 2
        for card in cards:
            assert card["chunk_id"], "every card must point at a real chunk"
            assert card["source_excerpt"].strip(), "every card must carry its source text"

    async def test_the_model_only_sees_passages_from_the_requested_paper(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card())

        await registered_client.post(f"{api}/papers/{paper_id}/flashcards", json={"count": 3})

        prompt = generator["provider"].last_prompt
        assert "Transformer" in prompt
        assert "PASSAGES" in prompt
        assert "[1]" in prompt

    async def test_a_card_citing_a_passage_that_was_never_shown_is_discarded(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        """The central guarantee. A source number the model invented cannot become a card."""
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(
            a_card(source=1), a_card(source=999, front="Where did this come from?")
        )

        response = await registered_client.post(
            f"{api}/papers/{paper_id}/flashcards", json={"count": 5}
        )

        assert response.status_code == 201
        cards = response.json()
        assert len(cards) == 1
        assert cards[0]["front"] == "What reduced the latency?"

    async def test_generation_fails_loudly_when_nothing_can_be_grounded(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card(source=800), a_card(source=900))

        response = await registered_client.post(
            f"{api}/papers/{paper_id}/flashcards", json={"count": 5}
        )

        assert response.status_code == 422
        assert "ground" in response.json()["error"]["message"].lower()

    async def test_cards_belong_to_their_owner_alone(
        self, registered_client: AsyncClient, client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card())
        await registered_client.post(f"{api}/papers/{paper_id}/flashcards", json={"count": 1})

        await client.post(
            f"{api}/auth/register",
            json={
                "email": "other@atlas.dev",
                "full_name": "Other Reader",
                "password": "a-sufficiently-long-password",
            },
        )
        response = await client.get(f"{api}/flashcards")

        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.usefixtures("generator")
class TestReview:
    async def test_reviewing_moves_the_card_out_of_the_due_queue(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card())
        created = await registered_client.post(
            f"{api}/papers/{paper_id}/flashcards", json={"count": 1}
        )
        card_id = created.json()[0]["id"]

        due = await registered_client.get(f"{api}/flashcards?due_only=true")
        assert len(due.json()) == 1

        reviewed = await registered_client.post(
            f"{api}/flashcards/{card_id}/reviews", json={"rating": "good"}
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["interval_days"] == 1
        assert reviewed.json()["review_count"] == 1

        still_due = await registered_client.get(f"{api}/flashcards?due_only=true")
        assert still_due.json() == []

    async def test_forgetting_keeps_the_card_due_and_records_a_lapse(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card())
        created = await registered_client.post(
            f"{api}/papers/{paper_id}/flashcards", json={"count": 1}
        )
        card_id = created.json()[0]["id"]

        await registered_client.post(f"{api}/flashcards/{card_id}/reviews", json={"rating": "good"})
        response = await registered_client.post(
            f"{api}/flashcards/{card_id}/reviews", json={"rating": "forgot"}
        )

        assert response.json()["interval_days"] == 0
        assert response.json()["lapse_count"] == 1
        assert len((await registered_client.get(f"{api}/flashcards?due_only=true")).json()) == 1

    async def test_another_account_cannot_review_your_card(
        self, registered_client: AsyncClient, client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card())
        created = await registered_client.post(
            f"{api}/papers/{paper_id}/flashcards", json={"count": 1}
        )
        card_id = created.json()[0]["id"]

        await client.post(
            f"{api}/auth/register",
            json={
                "email": "intruder@atlas.dev",
                "full_name": "Intruder",
                "password": "a-sufficiently-long-password",
            },
        )
        response = await client.post(f"{api}/flashcards/{card_id}/reviews", json={"rating": "easy"})

        assert response.status_code == 404


@pytest.mark.usefixtures("generator")
class TestQuiz:
    async def test_the_answer_key_is_withheld_until_submission(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_question())

        created = await registered_client.post(
            f"{api}/papers/{paper_id}/quizzes", json={"count": 1}
        )

        assert created.status_code == 201, created.text
        question = created.json()["questions"][0]
        assert "correct_index" not in question
        assert "explanation" not in question
        assert len(question["options"]) == 4

    async def test_submitting_scores_the_quiz_and_reveals_the_sources(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_question())
        quiz = (
            await registered_client.post(f"{api}/papers/{paper_id}/quizzes", json={"count": 1})
        ).json()
        question_id = quiz["questions"][0]["id"]

        response = await registered_client.post(
            f"{api}/quizzes/{quiz['id']}/submission", json={"answers": {question_id: 0}}
        )

        assert response.status_code == 200, response.text
        submitted = response.json()
        assert submitted["correct_count"] == 1
        answered = submitted["questions"][0]
        assert answered["correct_index"] == 0
        assert answered["selected_index"] == 0
        assert answered["source_excerpt"].strip()
        assert answered["chunk_id"]

    async def test_a_quiz_cannot_be_submitted_twice(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_question())
        quiz = (
            await registered_client.post(f"{api}/papers/{paper_id}/quizzes", json={"count": 1})
        ).json()

        await registered_client.post(f"{api}/quizzes/{quiz['id']}/submission", json={"answers": {}})
        second = await registered_client.post(
            f"{api}/quizzes/{quiz['id']}/submission", json={"answers": {}}
        )

        assert second.status_code == 422

    async def test_a_question_citing_an_unknown_passage_is_discarded(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_question(source=1), a_question(source=404))

        response = await registered_client.post(
            f"{api}/papers/{paper_id}/quizzes", json={"count": 5}
        )

        assert response.json()["question_count"] == 1


@pytest.mark.usefixtures("generator")
class TestProgress:
    async def test_progress_counts_what_is_actually_there(
        self, registered_client: AsyncClient, api: str, run_worker, generator
    ) -> None:
        paper_id = await upload_and_index(registered_client, api, TRANSFORMERS_PDF, run_worker)
        generator["provider"].reply = cards_json(a_card(), a_card(front="What is speculative?"))
        cards = (
            await registered_client.post(f"{api}/papers/{paper_id}/flashcards", json={"count": 2})
        ).json()

        await registered_client.post(
            f"{api}/flashcards/{cards[0]['id']}/reviews", json={"rating": "good"}
        )

        summary = (await registered_client.get(f"{api}/study/progress")).json()

        assert summary["total_cards"] == 2
        assert summary["due_now"] == 1
        assert summary["mastered"] == 0
        assert summary["reviews_last_seven_days"] == 1
        assert summary["papers"][0]["paper_id"] == paper_id
        assert summary["papers"][0]["card_count"] == 2

    async def test_progress_is_empty_before_anything_is_studied(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        summary = (await registered_client.get(f"{api}/study/progress")).json()
        assert summary == {
            "total_cards": 0,
            "due_now": 0,
            "mastered": 0,
            "reviews_last_seven_days": 0,
            "papers": [],
        }


_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
