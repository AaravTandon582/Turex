"""Applying the limits to requests.

The rate limiter knows about counters. This knows about HTTP — where a client's identity comes
from, what to raise when a limit is hit, and which header tells the client when to come back.

Keeping the two apart matters because the limiter is exercised in tests with a fake clock and
no HTTP at all, which is the only way to test a fifteen-minute window without waiting.
"""

from __future__ import annotations

import uuid

from fastapi import Request

from atlas.core.errors import RateLimitedError
from atlas.core.logging import get_logger
from atlas.security.rate_limit import Limit, RateLimiter

logger = get_logger(__name__)

TRUSTED_FORWARDING_HEADER = "x-forwarded-for"


def client_address(request: Request) -> str:
    """The caller's address, as well as it can be known.

    Behind a reverse proxy every request appears to come from the proxy, so `X-Forwarded-For`
    is read when present — but only the first entry, and only when Atlas is configured to sit
    behind a proxy. A client can send that header itself, so trusting it unconditionally would
    hand an attacker a way to appear as a new address on every request and defeat the limit
    entirely.
    """
    if request.app.state.trust_proxy_headers:
        forwarded = request.headers.get(TRUSTED_FORWARDING_HEADER)
        if forwarded:
            return forwarded.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


class Guard:
    """Applies one named limit to a request, keyed by address or by user."""

    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    def by_address(self, request: Request, limit: Limit, *, scope: str) -> None:
        self._enforce(f"{scope}:addr:{client_address(request)}", limit, scope=scope)

    def by_user(self, user_id: uuid.UUID, limit: Limit, *, scope: str) -> None:
        self._enforce(f"{scope}:user:{user_id}", limit, scope=scope)

    def by_identifier(self, identifier: str, limit: Limit, *, scope: str) -> None:
        """Keyed on something the caller supplies — an email address on a login attempt.

        Lower-cased so `Person@example.com` and `person@example.com` share a bucket, since
        otherwise changing the capitalisation resets the counter.
        """
        self._enforce(f"{scope}:id:{identifier.strip().lower()}", limit, scope=scope)

    def clear_identifier(self, identifier: str, *, scope: str) -> None:
        """Forget an identifier's history after it succeeds legitimately."""
        reset = getattr(self._limiter, "reset", None)
        if reset is not None:
            reset(f"{scope}:id:{identifier.strip().lower()}")

    def _enforce(self, key: str, limit: Limit, *, scope: str) -> None:
        decision = self._limiter.check(key, limit)
        if decision.allowed:
            return

        # Logged at warning: a limit being hit is either an attack or a bug in a client, and
        # both are worth seeing. The key is not logged — it contains an email or a user id.
        logger.warning(
            "rate limit reached",
            extra={
                "scope": scope,
                "limit": limit.description,
                "retry_after": decision.retry_after_seconds,
            },
        )
        raise RateLimitedError(
            f"Too many attempts. Try again in {_phrase(decision.retry_after_seconds)}.",
            detail=f"{scope} exceeded {limit.description}",
            context={"retry_after_seconds": decision.retry_after_seconds},
        )


def _phrase(seconds: int) -> str:
    """A wait expressed the way a person would say it."""
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    return "a minute" if minutes <= 1 else f"{minutes} minutes"
