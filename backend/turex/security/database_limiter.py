"""A rate limiter every process shares.

The in-memory limiter is correct for one process and wrong for several: four workers each keep
their own counters, so a limit of eight becomes thirty-two, and a restart forgets everything.
That is the difference between a limit and a suggestion.

This keeps the counters in PostgreSQL, which the deployment already has. Redis would be faster
and is the usual answer, but it is a second thing to run, and at the volumes a limiter sees —
one small write per guarded request — a table is entirely adequate. The interface is the same
either way, which is what the interface was for.

The window is fixed rather than sliding. A sliding window needs every timestamp kept and
scanned; a fixed window needs one row per key per window and a single atomic increment. The
cost is that an attacker can spend one window's allowance at its end and the next at its start,
so the *effective* burst is twice the limit for a moment. Halving the configured limit would
trade real usability for that, and it is not worth it: eight login attempts becoming a
momentary sixteen is not what stands between an attacker and a password.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from turex.core.logging import get_logger
from turex.security.rate_limit import Decision, Limit, RateLimiter

logger = get_logger(__name__)


def _window_start(now: datetime, seconds: int) -> datetime:
    """Snap to the start of the current window, so every process agrees on which one it is."""
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


class DatabaseRateLimiter(RateLimiter):
    """Counters in PostgreSQL, shared by every process."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def check(self, key: str, limit: Limit) -> Decision:
        """Record an attempt and say whether it is allowed.

        One statement. `ON CONFLICT … DO UPDATE` makes the read, the increment, and the write
        a single atomic operation, so two processes arriving together cannot both see the same
        count and both decide they are under the limit.
        """
        now = datetime.now(UTC)
        window = _window_start(now, limit.seconds)
        # Hashed so an email address never becomes a row someone can read out of the table.
        digest = hashlib.sha256(key.encode()).hexdigest()

        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO rate_limit_counters (key_hash, window_start, hits)
                    VALUES (:key_hash, :window_start, 1)
                    ON CONFLICT (key_hash, window_start)
                    DO UPDATE SET hits = rate_limit_counters.hits + 1
                    RETURNING hits
                    """
                ),
                {"key_hash": digest, "window_start": window},
            )
            hits = int(result.scalar_one())
            await session.commit()

        if hits > limit.requests:
            retry_after = max(1, int((window.timestamp() + limit.seconds) - now.timestamp()))
            return Decision(allowed=False, remaining=0, retry_after_seconds=retry_after)

        return Decision(
            allowed=True, remaining=max(0, limit.requests - hits), retry_after_seconds=0
        )

    async def reset(self, key: str) -> None:
        """Forget a key, so a correct password clears the account's failed attempts."""
        digest = hashlib.sha256(key.encode()).hexdigest()
        async with self._sessions() as session:
            await session.execute(
                text("DELETE FROM rate_limit_counters WHERE key_hash = :key_hash"),
                {"key_hash": digest},
            )
            await session.commit()

    async def prune(self, older_than_seconds: int = 86_400) -> int:
        """Drop counters whose window closed long ago.

        Rows only accumulate while requests arrive, but nothing removes them afterwards, and a
        table that only grows is a slow leak wherever it lives.
        """
        cutoff = datetime.fromtimestamp(datetime.now(UTC).timestamp() - older_than_seconds, tz=UTC)
        async with self._sessions() as session:
            # RETURNING rather than `rowcount`: the async result object does not expose a
            # row count, and counting what was removed is the point of the return value.
            removed = await session.scalars(
                text(
                    "DELETE FROM rate_limit_counters WHERE window_start < :cutoff "
                    "RETURNING key_hash"
                ),
                {"cutoff": cutoff},
            )
            count = len(list(removed))
            await session.commit()
            return count
