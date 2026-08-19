"""Flashcard and quiz generation, review scheduling, and study progress.

The generation half is where this milestone's honesty rule lives. The model is shown numbered
passages from the paper and must attach a passage number to every card it writes. The service
turns that number into a chunk id and stores the passage text alongside it. An item pointing
at a number it was never given is discarded, so a card in the database always has a real
passage behind it — the same mechanism that keeps assistant citations honest.

The review half is ordinary bookkeeping over `study/scheduling.py`.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from atlas.ai.base import ChatMessage, ChatProvider, ChatRequest, Role
from atlas.ai.structured import parse_items
from atlas.core.errors import NotFoundError, ValidationError
from atlas.core.logging import get_logger
from atlas.ingestion.chunking import is_non_content_section
from atlas.models.paper import Paper, PaperChunk, PaperSection, ProcessingStatus
from atlas.models.study import (
    CardKind,
    CardReview,
    Flashcard,
    QuestionKind,
    Quiz,
    QuizQuestion,
    ReviewRating,
)
from atlas.models.user import User
from atlas.study.prompts import (
    FLASHCARD_SYSTEM,
    PREREQUISITE_SYSTEM,
    QUIZ_SYSTEM,
    SHORT_ANSWER_SYSTEM,
    flashcard_request,
    prerequisite_request,
    quiz_request,
    short_answer_request,
)
from atlas.study.scheduling import MASTERED_INTERVAL_DAYS, STARTING_EASE, next_schedule

logger = get_logger(__name__)

MAX_PASSAGES = 18
"""How many passages the generator is shown. Enough to cover a paper's argument; small enough
that the model is choosing between good candidates rather than skimming everything."""

MIN_PASSAGE_CHARS = 320
"""Preferred floor. Longer passages carry a full claim with its qualifiers, which is what a
good card needs."""

ABSOLUTE_MIN_PASSAGE_CHARS = 120
"""Hard floor. Below this a chunk is a heading, a caption, or a stray line."""

MIN_USABLE_PASSAGES = 4
"""How many substantial passages a paper needs before the shorter ones are ignored."""

MAX_CARDS_PER_RUN = 20
MAX_QUIZ_QUESTIONS = 10
QUIZ_OPTION_COUNT = 4


class GeneratedCard(BaseModel):
    """A flashcard as the model proposes it, before it has been checked against a passage."""

    front: str = Field(min_length=5, max_length=500)
    back: str = Field(min_length=2, max_length=2000)
    kind: CardKind
    source: int


class GeneratedShortAnswer(BaseModel):
    question: str = Field(min_length=8, max_length=500)
    answer: str = Field(min_length=2, max_length=2000)
    explanation: str = Field(min_length=2, max_length=2000)
    source: int


class GeneratedPrerequisite(BaseModel):
    concept: str = Field(min_length=2, max_length=200)
    why: str = Field(min_length=5, max_length=600)
    source: int


class GeneratedQuestion(BaseModel):
    question: str = Field(min_length=8, max_length=500)
    options: list[str] = Field(min_length=QUIZ_OPTION_COUNT, max_length=QUIZ_OPTION_COUNT)
    answer: int
    explanation: str = Field(min_length=2, max_length=2000)
    source: int

    @field_validator("answer")
    @classmethod
    def _in_range(cls, value: int) -> int:
        if not 0 <= value < QUIZ_OPTION_COUNT:
            raise ValueError("answer index out of range")
        return value

    @field_validator("options")
    @classmethod
    def _distinct(cls, value: list[str]) -> list[str]:
        stripped = [option.strip() for option in value]
        if any(not option for option in stripped) or len(set(stripped)) != len(stripped):
            raise ValueError("options must be distinct and non-empty")
        return stripped


@dataclass(frozen=True, slots=True)
class PaperProgress:
    """What one paper's study state looks like. Every number is counted, none estimated."""

    paper_id: uuid.UUID
    title: str
    card_count: int
    due_count: int
    mastered_count: int
    last_reviewed_at: datetime | None
    best_quiz_score: float | None


@dataclass(frozen=True, slots=True)
class StudySummary:
    total_cards: int
    due_now: int
    mastered: int
    reviews_last_seven_days: int
    papers: list[PaperProgress]


class StudyService:
    def __init__(self, db: AsyncSession, provider: Callable[[], ChatProvider]) -> None:
        self._db = db
        self._provider = provider
        """A factory, not an instance: reading cards and reviewing them must keep working on a
        deployment with no model configured. Only generation resolves it."""

    # -- generation ---------------------------------------------------------------

    async def generate_flashcards(
        self, *, owner: User, paper_id: uuid.UUID, count: int
    ) -> list[Flashcard]:
        paper = await self._owned_paper(owner, paper_id)
        passages = await self._passages(paper.id)
        count = max(1, min(count, MAX_CARDS_PER_RUN))

        raw = await self._complete(
            system=FLASHCARD_SYSTEM,
            user=flashcard_request(
                paper_title=paper.display_title,
                count=count,
                passages=_render(passages),
            ),
            max_output_tokens=6000,
        )

        proposed = parse_items(raw, GeneratedCard)[:count]
        cards: list[Flashcard] = []
        now = datetime.now(UTC)

        for proposal in proposed:
            passage = _resolve(passages, proposal.source)
            if passage is None:
                continue
            cards.append(
                Flashcard(
                    owner_id=owner.id,
                    paper_id=paper.id,
                    chunk_id=passage.id,
                    front=proposal.front.strip(),
                    back=proposal.back.strip(),
                    kind=proposal.kind,
                    source_text=passage.content,
                    source_page=passage.page_start,
                    ease=STARTING_EASE,
                    interval_days=0,
                    due_at=now,
                )
            )

        _require_grounded(len(proposed), len(cards), "flashcards")
        self._db.add_all(cards)
        await self._db.commit()
        for card in cards:
            await self._db.refresh(card)

        logger.info(
            "flashcards.generated",
            extra={"paper_id": str(paper.id), "proposed": len(proposed), "stored": len(cards)},
        )
        return cards

    async def generate_quiz(self, *, owner: User, paper_id: uuid.UUID, count: int) -> Quiz:
        paper = await self._owned_paper(owner, paper_id)
        passages = await self._passages(paper.id)
        count = max(1, min(count, MAX_QUIZ_QUESTIONS))

        raw = await self._complete(
            system=QUIZ_SYSTEM,
            user=quiz_request(
                paper_title=paper.display_title,
                count=count,
                passages=_render(passages),
            ),
            max_output_tokens=6000,
        )

        proposed = parse_items(raw, GeneratedQuestion)[:count]
        questions: list[QuizQuestion] = []

        for question in proposed:
            passage = _resolve(passages, question.source)
            if passage is None:
                continue
            options, answer = _shuffle_options(
                question.options, question.answer, seed=f"{paper.id}:{len(questions)}"
            )
            questions.append(
                QuizQuestion(
                    position=len(questions),
                    kind=QuestionKind.multiple_choice,
                    prompt=question.question.strip(),
                    options=options,
                    correct_index=answer,
                    explanation=question.explanation.strip(),
                    chunk_id=passage.id,
                    source_text=passage.content,
                    source_page=passage.page_start,
                )
            )

        _require_grounded(len(proposed), len(questions), "quiz questions")
        quiz = Quiz(owner_id=owner.id, paper_id=paper.id, title=paper.display_title)
        quiz.questions = questions
        self._db.add(quiz)
        await self._db.commit()

        logger.info(
            "quiz.generated",
            extra={"paper_id": str(paper.id), "proposed": len(proposed), "stored": len(questions)},
        )
        return await self.get_quiz(owner=owner, quiz_id=quiz.id)

    async def generate_short_answers(self, *, owner: User, paper_id: uuid.UUID, count: int) -> Quiz:
        """A quiz of recall questions rather than recognition ones.

        Stored as a quiz so the two kinds share history, scoring surfaces, and the same
        grounding: every question keeps the passage it came from.
        """
        paper = await self._owned_paper(owner, paper_id)
        passages = await self._passages(paper.id)
        count = max(1, min(count, MAX_QUIZ_QUESTIONS))

        raw = await self._complete(
            system=SHORT_ANSWER_SYSTEM,
            user=short_answer_request(
                paper_title=paper.display_title, count=count, passages=_render(passages)
            ),
            max_output_tokens=6000,
        )

        proposed = parse_items(raw, GeneratedShortAnswer)[:count]
        questions: list[QuizQuestion] = []
        for item in proposed:
            passage = _resolve(passages, item.source)
            if passage is None:
                continue
            questions.append(
                QuizQuestion(
                    position=len(questions),
                    kind=QuestionKind.short_answer,
                    prompt=item.question.strip(),
                    options=[],
                    correct_index=None,
                    model_answer=item.answer.strip(),
                    explanation=item.explanation.strip(),
                    chunk_id=passage.id,
                    source_text=passage.content,
                    source_page=passage.page_start,
                )
            )

        _require_grounded(len(proposed), len(questions), "short-answer questions")
        quiz = Quiz(owner_id=owner.id, paper_id=paper.id, title=paper.display_title)
        quiz.questions = questions
        self._db.add(quiz)
        await self._db.commit()

        logger.info(
            "short_answers.generated",
            extra={"paper_id": str(paper.id), "stored": len(questions)},
        )
        return await self.get_quiz(owner=owner, quiz_id=quiz.id)

    async def prerequisites(
        self, *, owner: User, paper_id: uuid.UUID
    ) -> list[tuple[GeneratedPrerequisite, PaperChunk]]:
        """What a reader must already understand for this paper to make sense.

        Returned rather than stored: unlike a flashcard, this is read once while deciding
        whether to attempt a paper, and a stale copy would be worse than regenerating it.
        Each entry still carries the passage that shows the assumption, so it can be checked.
        """
        paper = await self._owned_paper(owner, paper_id)
        passages = await self._passages(paper.id)

        raw = await self._complete(
            system=PREREQUISITE_SYSTEM,
            user=prerequisite_request(paper_title=paper.display_title, passages=_render(passages)),
            max_output_tokens=3000,
        )

        grounded: list[tuple[GeneratedPrerequisite, PaperChunk]] = []
        for item in parse_items(raw, GeneratedPrerequisite):
            passage = _resolve(passages, item.source)
            if passage is not None:
                grounded.append((item, passage))
        return grounded

    async def _complete(self, *, system: str, user: str, max_output_tokens: int) -> str:
        result = await self._provider().complete(
            ChatRequest(
                system=system,
                messages=[ChatMessage(role=Role.user, content=user)],
                max_output_tokens=max_output_tokens,
                effort="medium",
            )
        )
        if result.stopped_early:
            # The trailing entry is truncated; the balanced-array reader will drop it. Worth
            # knowing about, because it means the requested count was too high for the budget.
            logger.warning("study.generation_truncated", extra={"chars": len(result.text)})
        return result.text

    async def _passages(self, paper_id: uuid.UUID) -> list[PaperChunk]:
        """Choose the passages the generator sees.

        Content sections only, and spread evenly across the paper rather than taken from the
        front — the first eighteen chunks would produce a deck about the abstract and
        introduction of every paper in the library.

        The length preference is a preference, not a rule. Substantial passages make better
        cards, but a four-page workshop note whose chunks all fall under the bar is still a
        paper someone wants to study, so the bar drops rather than the paper being refused.
        """

        statement = (
            select(PaperChunk)
            .where(
                PaperChunk.paper_id == paper_id,
                func.length(PaperChunk.content) >= ABSOLUTE_MIN_PASSAGE_CHARS,
            )
            .order_by(PaperChunk.ordinal)
        )
        rows = list(await self._db.scalars(statement))

        sections = {
            section.id: section.title
            for section in await self._db.scalars(
                select(PaperSection).where(PaperSection.paper_id == paper_id)
            )
        }
        content = [
            chunk
            for chunk in rows
            if chunk.section_id is None
            or not is_non_content_section(sections.get(chunk.section_id, ""))
        ]

        if not content:
            raise ValidationError(
                "This paper doesn't have enough text to build study material from."
            )

        substantial = [chunk for chunk in content if len(chunk.content) >= MIN_PASSAGE_CHARS]
        chosen = substantial if len(substantial) >= MIN_USABLE_PASSAGES else content

        if len(chosen) <= MAX_PASSAGES:
            return chosen

        step = len(chosen) / MAX_PASSAGES
        return [chosen[int(index * step)] for index in range(MAX_PASSAGES)]

    # -- flashcards ---------------------------------------------------------------

    async def list_cards(
        self,
        *,
        owner: User,
        paper_id: uuid.UUID | None = None,
        due_only: bool = False,
        limit: int = 50,
    ) -> list[Flashcard]:
        statement: Select[tuple[Flashcard]] = select(Flashcard).where(
            Flashcard.owner_id == owner.id
        )
        if paper_id is not None:
            statement = statement.where(Flashcard.paper_id == paper_id)
        if due_only:
            statement = statement.where(Flashcard.due_at <= datetime.now(UTC))

        # Most overdue first, so a short session spends its time where recall is weakest.
        statement = statement.order_by(Flashcard.due_at, Flashcard.created_at).limit(limit)
        return list(await self._db.scalars(statement))

    async def review_card(
        self, *, owner: User, card_id: uuid.UUID, rating: ReviewRating
    ) -> Flashcard:
        card = await self._db.scalar(
            select(Flashcard).where(Flashcard.id == card_id, Flashcard.owner_id == owner.id)
        )
        if card is None:
            raise NotFoundError("That flashcard doesn't exist.")

        now = datetime.now(UTC)
        schedule = next_schedule(
            ease=card.ease, interval_days=card.interval_days, rating=rating, now=now
        )

        self._db.add(
            CardReview(
                card_id=card.id,
                owner_id=owner.id,
                rating=rating,
                interval_before=card.interval_days,
                interval_after=schedule.interval_days,
            )
        )

        card.ease = schedule.ease
        card.interval_days = schedule.interval_days
        card.due_at = schedule.due_at
        card.review_count += 1
        card.last_reviewed_at = now
        if schedule.lapsed:
            card.lapse_count += 1

        await self._db.commit()
        await self._db.refresh(card)
        return card

    async def delete_card(self, *, owner: User, card_id: uuid.UUID) -> None:
        card = await self._db.scalar(
            select(Flashcard).where(Flashcard.id == card_id, Flashcard.owner_id == owner.id)
        )
        if card is None:
            raise NotFoundError("That flashcard doesn't exist.")
        await self._db.delete(card)
        await self._db.commit()

    # -- quizzes ------------------------------------------------------------------

    async def get_quiz(self, *, owner: User, quiz_id: uuid.UUID) -> Quiz:
        quiz = await self._db.scalar(
            select(Quiz)
            .where(Quiz.id == quiz_id, Quiz.owner_id == owner.id)
            .options(selectinload(Quiz.questions))
        )
        if quiz is None:
            raise NotFoundError("That quiz doesn't exist.")
        return quiz

    async def list_quizzes(self, *, owner: User, limit: int = 20) -> list[Quiz]:
        statement = (
            select(Quiz)
            .where(Quiz.owner_id == owner.id)
            .order_by(Quiz.created_at.desc())
            .limit(limit)
            .options(selectinload(Quiz.questions))
        )
        return list(await self._db.scalars(statement))

    async def submit_quiz(
        self,
        *,
        owner: User,
        quiz_id: uuid.UUID,
        answers: dict[uuid.UUID, int],
        writings: dict[uuid.UUID, str] | None = None,
    ) -> Quiz:
        """Record the chosen answers and score the quiz.

        Grading happens here rather than in the client for the obvious reason — the correct
        index is not sent to the browser until the quiz has been submitted.
        """

        quiz = await self.get_quiz(owner=owner, quiz_id=quiz_id)
        if quiz.submitted_at is not None:
            raise ValidationError("This quiz has already been submitted.")

        correct = 0
        for question in quiz.questions:
            if question.kind is QuestionKind.short_answer:
                # Not scored. Free text compared to a model answer by string matching would
                # mark a correct answer wrong for using different words, so the learner
                # compares the two themselves.
                written = (writings or {}).get(question.id)
                if written is not None:
                    question.written_answer = written.strip()[:4000]
                continue

            selected = answers.get(question.id)
            if selected is not None and not 0 <= selected < len(question.options):
                raise ValidationError("An answer refers to an option that doesn't exist.")
            question.selected_index = selected
            if selected == question.correct_index:
                correct += 1

        quiz.submitted_at = datetime.now(UTC)
        # Counts only what was scored. A quiz of short answers reports zero correct out of
        # zero scored, which is honest; claiming a score for questions nobody graded is not.
        quiz.correct_count = correct
        await self._db.commit()
        return quiz

    async def delete_quiz(self, *, owner: User, quiz_id: uuid.UUID) -> None:
        quiz = await self._db.scalar(
            select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner.id)
        )
        if quiz is None:
            raise NotFoundError("That quiz doesn't exist.")
        await self._db.delete(quiz)
        await self._db.commit()

    # -- progress -----------------------------------------------------------------

    async def summary(self, *, owner: User) -> StudySummary:
        now = datetime.now(UTC)

        per_paper = (
            select(
                Flashcard.paper_id,
                Paper.title,
                Paper.original_filename,
                func.count(Flashcard.id).label("cards"),
                func.count(Flashcard.id).filter(Flashcard.due_at <= now).label("due"),
                func.count(Flashcard.id)
                .filter(Flashcard.interval_days >= MASTERED_INTERVAL_DAYS)
                .label("mastered"),
                func.max(Flashcard.last_reviewed_at).label("last_reviewed"),
            )
            .join(Paper, Paper.id == Flashcard.paper_id)
            .where(Flashcard.owner_id == owner.id)
            .group_by(Flashcard.paper_id, Paper.title, Paper.original_filename)
        )

        # Scored per quiz in SQL, reduced to a best-per-paper in Python. Expressing "highest
        # ratio per paper" in one statement needs a window function or a correlated subquery,
        # and neither is worth it over at most a few dozen rows.
        scored = await self._db.execute(
            select(Quiz.paper_id, Quiz.correct_count, func.count(QuizQuestion.id))
            .join(QuizQuestion, QuizQuestion.quiz_id == Quiz.id)
            .where(Quiz.owner_id == owner.id, Quiz.submitted_at.is_not(None))
            .group_by(Quiz.id, Quiz.paper_id, Quiz.correct_count)
        )
        best_scores: dict[uuid.UUID, float] = {}
        for paper_id, correct_count, question_count in scored:
            if not question_count or correct_count is None:
                continue
            score = correct_count / question_count
            best_scores[paper_id] = max(best_scores.get(paper_id, 0.0), score)

        papers: list[PaperProgress] = []
        for row in (await self._db.execute(per_paper)).all():
            papers.append(
                PaperProgress(
                    paper_id=row.paper_id,
                    title=row.title or row.original_filename,
                    card_count=row.cards,
                    due_count=row.due,
                    mastered_count=row.mastered,
                    last_reviewed_at=row.last_reviewed,
                    best_quiz_score=best_scores.get(row.paper_id),
                )
            )
        papers.sort(key=lambda paper: (-paper.due_count, paper.title))

        recent = await self._db.scalar(
            select(func.count(CardReview.id)).where(
                CardReview.owner_id == owner.id,
                CardReview.created_at >= now - timedelta(days=7),
            )
        )

        return StudySummary(
            total_cards=sum(paper.card_count for paper in papers),
            due_now=sum(paper.due_count for paper in papers),
            mastered=sum(paper.mastered_count for paper in papers),
            reviews_last_seven_days=recent or 0,
            papers=papers,
        )

    # -- helpers ------------------------------------------------------------------

    async def _owned_paper(self, owner: User, paper_id: uuid.UUID) -> Paper:
        paper = await self._db.scalar(
            select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner.id)
        )
        if paper is None:
            raise NotFoundError("That paper doesn't exist.")
        if paper.status is not ProcessingStatus.ready:
            raise ValidationError("Atlas is still reading this paper. Try again once it's ready.")
        return paper


def _render(passages: Sequence[PaperChunk]) -> str:
    """Number the passages exactly as the prompt tells the model they are numbered."""
    blocks = []
    for index, chunk in enumerate(passages, start=1):
        page = f" (page {chunk.page_start})" if chunk.page_start else ""
        blocks.append(f"[{index}]{page}\n{chunk.content}")
    return "\n\n".join(blocks)


def _resolve(passages: Sequence[PaperChunk], source: int) -> PaperChunk | None:
    """Map a passage number back to the chunk, or nothing if the model invented the number."""
    if 1 <= source <= len(passages):
        return passages[source - 1]
    logger.warning("study.unknown_source", extra={"source": source, "shown": len(passages)})
    return None


def _require_grounded(proposed: int, stored: int, label: str) -> None:
    """Fail loudly when nothing survived grounding.

    Returning an empty list here would read to the user as "this paper produced no cards",
    when what actually happened is that every card cited a passage that does not exist — or
    that the model produced nothing at all. Both are failures; neither is an empty deck.
    """
    if not stored:
        raise ValidationError(
            f"Atlas could not ground any {label} in this paper's text. Try again."
        )


def _shuffle_options(options: list[str], answer: int, *, seed: str) -> tuple[list[str], int]:
    """Move the correct option somewhere other than wherever the model put it.

    Observed live: a model that placed the correct answer first in every question of a quiz.
    That is not dishonesty, it is a drafting habit — the true statement is the one it thinks of
    first — but a quiz whose answer is always A tests nothing except pattern recognition.

    Seeded from the paper and the question's position rather than the clock, so the same quiz
    reads the same way every time it is loaded and the behaviour is testable.
    """
    order = list(range(len(options)))
    random.Random(seed).shuffle(order)
    return [options[index] for index in order], order.index(answer)
