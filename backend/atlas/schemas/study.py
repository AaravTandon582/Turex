"""Request and response models for flashcards, quizzes, and study progress."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from atlas.models.study import CardKind, Flashcard, Quiz, QuizQuestion, ReviewRating
from atlas.schemas.base import AtlasModel
from atlas.services.study_service import (
    MAX_CARDS_PER_RUN,
    MAX_QUIZ_QUESTIONS,
    PaperProgress,
    StudySummary,
)

SOURCE_EXCERPT_CHARS = 600
"""How much of the source passage travels with a card. Enough to check the answer against,
short enough that a fifty-card response is not megabytes of duplicated paper text."""


def _excerpt(text: str) -> str:
    if len(text) <= SOURCE_EXCERPT_CHARS:
        return text
    return text[:SOURCE_EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"


class FlashcardRead(AtlasModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    chunk_id: uuid.UUID | None
    front: str
    back: str
    kind: CardKind
    source_excerpt: str
    source_page: int | None
    interval_days: int
    due_at: datetime
    review_count: int
    lapse_count: int
    last_reviewed_at: datetime | None

    @classmethod
    def of(cls, card: Flashcard) -> FlashcardRead:
        return cls(
            id=card.id,
            paper_id=card.paper_id,
            chunk_id=card.chunk_id,
            front=card.front,
            back=card.back,
            kind=card.kind,
            source_excerpt=_excerpt(card.source_text),
            source_page=card.source_page,
            interval_days=card.interval_days,
            due_at=card.due_at,
            review_count=card.review_count,
            lapse_count=card.lapse_count,
            last_reviewed_at=card.last_reviewed_at,
        )


class GenerateCardsRequest(AtlasModel):
    count: int = Field(default=10, ge=1, le=MAX_CARDS_PER_RUN)


class ReviewRequest(AtlasModel):
    rating: ReviewRating


class QuizQuestionRead(AtlasModel):
    """A question as the browser sees it while the quiz is being taken.

    The correct index, the explanation, and the source passage are absent here and present in
    `QuizQuestionResult`. Sending them before submission would put the answer key in the page
    source of the quiz being taken.
    """

    id: uuid.UUID
    position: int
    prompt: str
    options: list[str]

    @classmethod
    def of(cls, question: QuizQuestion) -> QuizQuestionRead:
        return cls(
            id=question.id,
            position=question.position,
            prompt=question.prompt,
            options=question.options,
        )


class QuizQuestionResult(QuizQuestionRead):
    correct_index: int
    explanation: str
    selected_index: int | None
    chunk_id: uuid.UUID | None
    source_excerpt: str
    source_page: int | None

    @classmethod
    def of(cls, question: QuizQuestion) -> QuizQuestionResult:
        return cls(
            id=question.id,
            position=question.position,
            prompt=question.prompt,
            options=question.options,
            correct_index=question.correct_index,
            explanation=question.explanation,
            selected_index=question.selected_index,
            chunk_id=question.chunk_id,
            source_excerpt=_excerpt(question.source_text),
            source_page=question.source_page,
        )


class QuizRead(AtlasModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    title: str
    created_at: datetime
    submitted_at: datetime | None
    correct_count: int | None
    question_count: int
    questions: list[QuizQuestionResult | QuizQuestionRead]
    """Result entries once the quiz has been submitted, plain entries before. Declared as a
    union so FastAPI's response model does not strip the answer key back off the result — a
    subclass returned under a base-class annotation is serialised as the base class."""

    @classmethod
    def of(cls, quiz: Quiz) -> QuizRead:
        """Reveal the answers only once the quiz has been submitted."""
        submitted = quiz.submitted_at is not None
        return cls(
            id=quiz.id,
            paper_id=quiz.paper_id,
            title=quiz.title,
            created_at=quiz.created_at,
            submitted_at=quiz.submitted_at,
            correct_count=quiz.correct_count,
            question_count=len(quiz.questions),
            questions=[
                QuizQuestionResult.of(question) if submitted else QuizQuestionRead.of(question)
                for question in quiz.questions
            ],
        )


class GenerateQuizRequest(AtlasModel):
    count: int = Field(default=5, ge=1, le=MAX_QUIZ_QUESTIONS)


class QuizSubmission(AtlasModel):
    answers: dict[uuid.UUID, int] = Field(default_factory=dict)
    """Question id to chosen option index. A question left out is scored as unanswered rather
    than wrong-by-default, so a partial submission reports what it actually measured."""


class PaperProgressRead(AtlasModel):
    paper_id: uuid.UUID
    title: str
    card_count: int
    due_count: int
    mastered_count: int
    last_reviewed_at: datetime | None
    best_quiz_score: float | None

    @classmethod
    def of(cls, progress: PaperProgress) -> PaperProgressRead:
        return cls(
            paper_id=progress.paper_id,
            title=progress.title,
            card_count=progress.card_count,
            due_count=progress.due_count,
            mastered_count=progress.mastered_count,
            last_reviewed_at=progress.last_reviewed_at,
            best_quiz_score=progress.best_quiz_score,
        )


class StudySummaryRead(AtlasModel):
    total_cards: int
    due_now: int
    mastered: int
    reviews_last_seven_days: int
    papers: list[PaperProgressRead]

    @classmethod
    def of(cls, summary: StudySummary) -> StudySummaryRead:
        return cls(
            total_cards=summary.total_cards,
            due_now=summary.due_now,
            mastered=summary.mastered,
            reviews_last_seven_days=summary.reviews_last_seven_days,
            papers=[PaperProgressRead.of(paper) for paper in summary.papers],
        )
