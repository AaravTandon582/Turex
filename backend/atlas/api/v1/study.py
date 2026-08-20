"""Flashcards, quizzes, and study progress."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from atlas.api.deps import CurrentUser, GuardDep, StudyServiceDep
from atlas.schemas.study import (
    SOURCE_EXCERPT_CHARS,
    FlashcardRead,
    GenerateCardsRequest,
    GenerateQuizRequest,
    PrerequisiteRead,
    QuizRead,
    QuizSubmission,
    ReviewRequest,
    StudySummaryRead,
)
from atlas.security import policy

router = APIRouter(tags=["study"])


# -- flashcards -------------------------------------------------------------------


@router.post(
    "/papers/{paper_id}/flashcards",
    response_model=list[FlashcardRead],
    status_code=status.HTTP_201_CREATED,
)
async def generate_flashcards(
    paper_id: uuid.UUID,
    payload: GenerateCardsRequest,
    user: CurrentUser,
    service: StudyServiceDep,
    guard: GuardDep,
) -> list[FlashcardRead]:
    await guard.by_user(user.id, policy.MODEL_CALLS_PER_USER, scope="model")
    cards = await service.generate_flashcards(owner=user, paper_id=paper_id, count=payload.count)
    return [FlashcardRead.of(card) for card in cards]


@router.get("/flashcards", response_model=list[FlashcardRead])
async def list_flashcards(
    user: CurrentUser,
    service: StudyServiceDep,
    paper_id: uuid.UUID | None = None,
    due_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[FlashcardRead]:
    cards = await service.list_cards(owner=user, paper_id=paper_id, due_only=due_only, limit=limit)
    return [FlashcardRead.of(card) for card in cards]


@router.post("/flashcards/{card_id}/reviews", response_model=FlashcardRead)
async def review_flashcard(
    card_id: uuid.UUID,
    payload: ReviewRequest,
    user: CurrentUser,
    service: StudyServiceDep,
) -> FlashcardRead:
    card = await service.review_card(owner=user, card_id=card_id, rating=payload.rating)
    return FlashcardRead.of(card)


@router.delete("/flashcards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flashcard(card_id: uuid.UUID, user: CurrentUser, service: StudyServiceDep) -> None:
    await service.delete_card(owner=user, card_id=card_id)


# -- quizzes ----------------------------------------------------------------------


@router.post(
    "/papers/{paper_id}/quizzes", response_model=QuizRead, status_code=status.HTTP_201_CREATED
)
async def generate_quiz(
    paper_id: uuid.UUID,
    payload: GenerateQuizRequest,
    user: CurrentUser,
    service: StudyServiceDep,
    guard: GuardDep,
) -> QuizRead:
    await guard.by_user(user.id, policy.MODEL_CALLS_PER_USER, scope="model")
    quiz = await service.generate_quiz(owner=user, paper_id=paper_id, count=payload.count)
    return QuizRead.of(quiz)


@router.post(
    "/papers/{paper_id}/short-answers", response_model=QuizRead, status_code=status.HTTP_201_CREATED
)
async def generate_short_answers(
    paper_id: uuid.UUID,
    payload: GenerateQuizRequest,
    user: CurrentUser,
    service: StudyServiceDep,
    guard: GuardDep,
) -> QuizRead:
    """Questions that must be recalled rather than recognised.

    Stored as a quiz so both kinds share the same history and grounding; the server does not
    score them, because matching free text against a model answer marks correct answers wrong.
    """
    await guard.by_user(user.id, policy.MODEL_CALLS_PER_USER, scope="model")
    quiz = await service.generate_short_answers(owner=user, paper_id=paper_id, count=payload.count)
    return QuizRead.of(quiz)


@router.get("/papers/{paper_id}/prerequisites", response_model=list[PrerequisiteRead])
async def paper_prerequisites(
    paper_id: uuid.UUID,
    user: CurrentUser,
    service: StudyServiceDep,
    guard: GuardDep,
) -> list[PrerequisiteRead]:
    """What a reader needs to understand before this paper will make sense.

    Generated on request rather than stored: it is read once while deciding whether to attempt
    a paper, and a stale copy would be worse than regenerating it.
    """
    await guard.by_user(user.id, policy.MODEL_CALLS_PER_USER, scope="model")
    entries = await service.prerequisites(owner=user, paper_id=paper_id)
    return [
        PrerequisiteRead(
            concept=item.concept,
            why=item.why,
            chunk_id=chunk.id,
            source_excerpt=chunk.content[:SOURCE_EXCERPT_CHARS],
            source_page=chunk.page_start,
        )
        for item, chunk in entries
    ]


@router.get("/quizzes", response_model=list[QuizRead])
async def list_quizzes(
    user: CurrentUser,
    service: StudyServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[QuizRead]:
    quizzes = await service.list_quizzes(owner=user, limit=limit)
    return [QuizRead.of(quiz) for quiz in quizzes]


@router.get("/quizzes/{quiz_id}", response_model=QuizRead)
async def get_quiz(quiz_id: uuid.UUID, user: CurrentUser, service: StudyServiceDep) -> QuizRead:
    quiz = await service.get_quiz(owner=user, quiz_id=quiz_id)
    return QuizRead.of(quiz)


@router.post("/quizzes/{quiz_id}/submission", response_model=QuizRead)
async def submit_quiz(
    quiz_id: uuid.UUID,
    payload: QuizSubmission,
    user: CurrentUser,
    service: StudyServiceDep,
) -> QuizRead:
    quiz = await service.submit_quiz(
        owner=user, quiz_id=quiz_id, answers=payload.answers, writings=payload.written
    )
    return QuizRead.of(quiz)


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(quiz_id: uuid.UUID, user: CurrentUser, service: StudyServiceDep) -> None:
    await service.delete_quiz(owner=user, quiz_id=quiz_id)


# -- progress ---------------------------------------------------------------------


@router.get("/study/progress", response_model=StudySummaryRead)
async def study_progress(user: CurrentUser, service: StudyServiceDep) -> StudySummaryRead:
    return StudySummaryRead.of(await service.summary(owner=user))
