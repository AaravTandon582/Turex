"""Rate limiting.

A sliding-window counter behind a small interface. The interface exists because the in-memory
implementation has a real limitation — it is per-process, so a deployment running four workers
enforces roughly four times the configured limit, and restarting clears every counter. That is
acceptable for a single-process deployment and is not acceptable at scale, so the seam for a
shared backend (Redis, or a table) is here rather than needing to be carved out later.

Sliding window rather than fixed buckets: a fixed window lets an attacker spend the whole
allowance at the end of one window and again at the start of the next, which is twice the
intended rate at exactly the moment it matters.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

PRUNE_EVERY = 1000
"""Requests between sweeps of inactive keys. Cheap enough to be unnoticeable, frequent enough
that the map cannot grow unboundedly between them."""


@dataclass(frozen=True, slots=True)
class Limit:
    """How many requests are allowed, over how long."""

    requests: int
    seconds: int

    def __post_init__(self) -> None:
        if self.requests < 1 or self.seconds < 1:
            raise ValueError("a limit needs a positive count and window")

    @property
    def description(self) -> str:
        """Phrased for a person: this ends up in an error message someone has to act on."""
        if self.seconds % 3600 == 0:
            unit, count = "hour", self.seconds // 3600
        elif self.seconds % 60 == 0:
            unit, count = "minute", self.seconds // 60
        else:
            unit, count = "second", self.seconds
        window = unit if count == 1 else f"{count} {unit}s"
        return f"{self.requests} per {window}"


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after_seconds: int
    """Zero when allowed. Otherwise how long until the oldest request leaves the window."""


class RateLimiter(ABC):
    @abstractmethod
    async def check(self, key: str, limit: Limit) -> Decision:
        """Record an attempt against `key` and say whether it is allowed.

        Asynchronous because a shared implementation must reach a database, and an interface
        that is synchronous forces every such implementation to either block the event loop or
        raise. The in-memory one does no I/O and simply never awaits.

        Recording and deciding are one operation deliberately. Splitting them invites a caller
        to check, do the work, and forget to record — which reads as working and enforces
        nothing.
        """


class InMemoryRateLimiter(RateLimiter):
    """Per-process sliding window.

    Timestamps are kept in a deque per key and expired from the left, so the work per call is
    proportional to the number of requests leaving the window rather than to the window length.
    """

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._now = now or time.monotonic
        """Injectable so the tests can move time without sleeping through a window."""

        self._since_prune = 0

    async def check(self, key: str, limit: Limit) -> Decision:
        # Housekeeping happens here rather than on a timer: the map only grows when requests
        # arrive, so the work belongs where the growth does and there is no background task to
        # start, supervise, or forget to stop.
        self._since_prune += 1
        if self._since_prune >= PRUNE_EVERY:
            self._since_prune = 0
            await self.prune()

        now = self._now()
        window_start = now - limit.seconds
        hits = self._hits[key]

        while hits and hits[0] <= window_start:
            hits.popleft()

        if len(hits) >= limit.requests:
            retry_after = max(1, int(hits[0] + limit.seconds - now) + 1)
            return Decision(allowed=False, remaining=0, retry_after_seconds=retry_after)

        hits.append(now)
        return Decision(allowed=True, remaining=limit.requests - len(hits), retry_after_seconds=0)

    async def reset(self, key: str) -> None:
        """Forget a key's history. Called after a successful login, so one bad session of
        typos does not hold back someone who then gets it right."""
        self._hits.pop(key, None)

    async def prune(self, older_than_seconds: int = 3600) -> int:
        """Drop keys with no recent activity, and report how many went.

        Without this the map grows once per distinct client address and never shrinks, which is
        a slow memory leak that only shows up in production.
        """
        cutoff = self._now() - older_than_seconds
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
        return len(stale)

    @property
    def tracked_keys(self) -> int:
        return len(self._hits)
