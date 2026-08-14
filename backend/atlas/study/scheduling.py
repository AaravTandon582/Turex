"""Spaced-repetition scheduling.

A trimmed SM-2. The full algorithm carries a six-point grade scale and a separate "learning
steps" state machine; neither earns its complexity here, and both make the behaviour hard to
explain to the person being scheduled.

What is kept is the part that does the work: an ease factor per card that rises when recall is
easy and falls when it is hard, multiplying an interval that grows geometrically. What is
dropped is everything that only matters at deck sizes far beyond a personal library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from atlas.models.study import ReviewRating

MINIMUM_EASE = 1.3
"""Below this a card would be scheduled almost daily forever. SM-2's floor, for the same
reason: a card this hard needs rewriting, not more frequent repetition."""

STARTING_EASE = 2.5
MAXIMUM_INTERVAL_DAYS = 365
MASTERED_INTERVAL_DAYS = 21
"""Three weeks of successful recall is the point where a card stops being work in progress.
Used only for reporting — nothing in the schedule changes at this boundary."""

_EASE_DELTA: dict[ReviewRating, float] = {
    ReviewRating.forgot: -0.20,
    ReviewRating.hard: -0.15,
    ReviewRating.good: 0.0,
    ReviewRating.easy: 0.15,
}

_FIRST_INTERVAL_DAYS: dict[ReviewRating, int] = {
    ReviewRating.forgot: 0,
    ReviewRating.hard: 1,
    ReviewRating.good: 1,
    ReviewRating.easy: 3,
}


@dataclass(frozen=True, slots=True)
class Schedule:
    ease: float
    interval_days: int
    due_at: datetime
    lapsed: bool


def next_schedule(
    *,
    ease: float,
    interval_days: int,
    rating: ReviewRating,
    now: datetime | None = None,
) -> Schedule:
    """Where a card goes after being graded.

    `now` is a parameter rather than read from the clock so the scheduler is testable without
    freezing time globally.
    """

    moment = now or datetime.now(UTC)
    next_ease = min(3.0, max(MINIMUM_EASE, ease + _EASE_DELTA[rating]))

    if rating is ReviewRating.forgot:
        # Back to the start of the ladder, and due again in this session rather than
        # tomorrow: a card you just failed is the one worth seeing again today.
        return Schedule(ease=next_ease, interval_days=0, due_at=moment, lapsed=True)

    if interval_days == 0:
        next_interval = _FIRST_INTERVAL_DAYS[rating]
    else:
        multiplier = {
            ReviewRating.hard: 1.2,
            ReviewRating.good: next_ease,
            ReviewRating.easy: next_ease * 1.3,
        }[rating]
        next_interval = math.ceil(interval_days * multiplier)

    next_interval = min(MAXIMUM_INTERVAL_DAYS, max(1, next_interval))
    return Schedule(
        ease=next_ease,
        interval_days=next_interval,
        due_at=moment + timedelta(days=next_interval),
        lapsed=False,
    )
