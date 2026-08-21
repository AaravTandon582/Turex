"""Flashcards, quizzes, and the review history behind them.

Study material is generated, so the same rule that governs citations governs it here: a card
or a question keeps a foreign key to the chunk it was written from **and** a snapshot of what
that chunk said. Without the key there is nothing to check the answer against; without the
snapshot, re-ingesting the paper would silently change what a card claims its source says.

A card the model produced without pointing at a real passage is not stored at all — see
`services/study_service.py`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from turex.db.base import Base, OwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CardKind(enum.StrEnum):
    """What a card is asking for.

    Recorded because the four kinds are worth different amounts. A definition card is cheap
    recall; a finding card asks what a paper actually demonstrated. Showing the mix lets a
    reader see whether a deck is testing understanding or vocabulary.
    """

    definition = "definition"
    concept = "concept"
    finding = "finding"
    method = "method"


class QuestionKind(enum.StrEnum):
    """How a question is answered.

    Multiple choice is checkable by the server, so it is scored. A short answer is not — the
    learner compares their own answer against the paper's, which is a different and often
    better exercise, because recalling a claim is harder than recognising it.
    """

    multiple_choice = "multiple_choice"
    short_answer = "short_answer"


class ReviewRating(enum.StrEnum):
    """How the review went, in the learner's own judgement.

    Four grades rather than right/wrong: the interval should grow differently for an answer
    that came instantly and one that was dragged up after ten seconds, and only the person
    reviewing knows which happened.
    """

    forgot = "forgot"
    hard = "hard"
    good = "good"
    easy = "easy"


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(python_enum, name=name, native_enum=False, validate_strings=True, length=32)


class Flashcard(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """One question and its answer, with the passage both came from."""

    __tablename__ = "flashcards"
    __table_args__ = (
        Index("ix_flashcards_owner_id_due_at", "owner_id", "due_at"),
        # paper_id alone, not just as the second half of the composite below: deleting a
        # paper cascades here, and without this the cascade sequentially scans the table.
        Index("ix_flashcards_paper_id", "paper_id"),
        Index("ix_flashcards_owner_id_paper_id", "owner_id", "paper_id"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("paper_chunks.id", ondelete="SET NULL"), index=True
    )

    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[CardKind] = mapped_column(_enum(CardKind, "card_kind"), nullable=False)

    # -- snapshot of the source passage, written once ------------------------------
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)

    # -- scheduling ----------------------------------------------------------------
    ease: Mapped[float] = mapped_column(Float, nullable=False, default=2.5, server_default="2.5")
    interval_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lapse_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reviews: Mapped[list[CardReview]] = relationship(
        back_populates="card",
        cascade="all, delete-orphan",
        order_by="CardReview.created_at.desc()",
        lazy="raise_on_sql",
    )


class CardReview(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """One grading of one card.

    Kept as its own table rather than only mutating the card, so "how is my recall trending"
    is answerable from data instead of guessed from the card's current interval.
    """

    __tablename__ = "card_reviews"
    __table_args__ = (
        Index("ix_card_reviews_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_card_reviews_card_id", "card_id"),
    )

    card_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[ReviewRating] = mapped_column(
        _enum(ReviewRating, "review_rating"), nullable=False
    )
    interval_before: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_after: Mapped[int] = mapped_column(Integer, nullable=False)

    card: Mapped[Flashcard] = relationship(back_populates="reviews", lazy="raise_on_sql")


class Quiz(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A generated set of questions about one paper.

    A quiz is one attempt. Retaking generates a new quiz rather than resetting this one, so a
    score always refers to a specific set of questions answered at a specific time.
    """

    __tablename__ = "quizzes"
    __table_args__ = (
        Index("ix_quizzes_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_quizzes_paper_id", "paper_id"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Null while the quiz is still being taken. Set once, on submission."""

    correct_count: Mapped[int | None] = mapped_column(Integer)

    questions: Mapped[list[QuizQuestion]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.position",
        lazy="raise_on_sql",
    )


class QuizQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question, its answer, and the passage that settles it."""

    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position", name="uq_quiz_questions_quiz_id_position"),
    )

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[QuestionKind] = mapped_column(
        _enum(QuestionKind, "question_kind"),
        nullable=False,
        default=QuestionKind.multiple_choice,
        server_default=QuestionKind.multiple_choice.value,
    )

    options: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    """Empty for a short-answer question, which has nothing to choose between."""

    correct_index: Mapped[int | None] = mapped_column(Integer)
    """Null for a short-answer question. Scoring a free-text answer by string comparison would
    mark a correct answer wrong for using different words, which teaches the wrong lesson."""

    model_answer: Mapped[str | None] = mapped_column(Text)
    """What the paper says, for a short-answer question. Shown after the learner commits."""

    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("paper_chunks.id", ondelete="SET NULL"), index=True
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)

    selected_index: Mapped[int | None] = mapped_column(Integer)
    """What the user chose. Null until the quiz is submitted, and on short-answer questions."""

    written_answer: Mapped[str | None] = mapped_column(Text)
    """What the user wrote, for a short-answer question. Kept so they can compare it against
    the paper's answer rather than having to remember what they said."""

    quiz: Mapped[Quiz] = relationship(back_populates="questions", lazy="raise_on_sql")
