"""Rate limiting: the counter itself, and the endpoints that depend on it.

Before this existed, thirty password guesses against a real account took two seconds and none
were refused — roughly nine hundred attempts a minute against a ten-character minimum. The
counter is tested with an injected clock so a fifteen-minute window can be exercised without
waiting fifteen minutes, and the endpoints are tested through real HTTP.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from atlas.security.guard import _phrase
from atlas.security.policy import LOGIN_PER_ACCOUNT, REGISTRATION_PER_ADDRESS
from atlas.security.rate_limit import InMemoryRateLimiter, Limit
from tests.conftest import REGISTRATION


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def limiter(clock: Clock) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(now=clock)


class TestTheCounter:
    def test_allows_up_to_the_limit_then_refuses(self, limiter: InMemoryRateLimiter) -> None:
        limit = Limit(requests=3, seconds=60)
        assert [limiter.check("k", limit).allowed for _ in range(3)] == [True, True, True]
        assert limiter.check("k", limit).allowed is False

    def test_reports_how_long_to_wait(self, limiter: InMemoryRateLimiter) -> None:
        limit = Limit(requests=1, seconds=60)
        limiter.check("k", limit)
        assert 1 <= limiter.check("k", limit).retry_after_seconds <= 61

    def test_the_window_slides_rather_than_resetting_in_steps(
        self, limiter: InMemoryRateLimiter, clock: Clock
    ) -> None:
        """A fixed window would allow the full allowance twice across a boundary.

        Three requests at t=0 and three more at t=61 is fine. Three at t=59 and three at t=61
        must not be, because that is six in two seconds.
        """
        limit = Limit(requests=3, seconds=60)
        for _ in range(3):
            assert limiter.check("k", limit).allowed

        clock.advance(59)
        assert limiter.check("k", limit).allowed is False, "still inside the window"

        clock.advance(2)
        assert limiter.check("k", limit).allowed is True, "the first three have now aged out"

    def test_keys_do_not_interfere(self, limiter: InMemoryRateLimiter) -> None:
        limit = Limit(requests=1, seconds=60)
        assert limiter.check("a", limit).allowed
        assert limiter.check("b", limit).allowed
        assert limiter.check("a", limit).allowed is False

    def test_a_reset_forgives_a_key(self, limiter: InMemoryRateLimiter) -> None:
        limit = Limit(requests=1, seconds=60)
        limiter.check("k", limit)
        limiter.reset("k")
        assert limiter.check("k", limit).allowed

    def test_pruning_drops_only_inactive_keys(
        self, limiter: InMemoryRateLimiter, clock: Clock
    ) -> None:
        """Without pruning the map grows once per client address and never shrinks."""
        limit = Limit(requests=5, seconds=60)
        limiter.check("old", limit)
        clock.advance(7200)
        limiter.check("fresh", limit)

        assert limiter.prune(older_than_seconds=3600) == 1
        assert limiter.tracked_keys == 1

    def test_a_limit_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            Limit(requests=0, seconds=60)
        with pytest.raises(ValueError):
            Limit(requests=5, seconds=0)

    @pytest.mark.parametrize(
        ("limit", "expected"),
        [
            (Limit(3, 60), "3 per minute"),
            (Limit(8, 900), "8 per 15 minutes"),
            (Limit(40, 3600), "40 per hour"),
            (Limit(5, 7200), "5 per 2 hours"),
        ],
    )
    def test_limits_describe_themselves_for_a_person(self, limit: Limit, expected: str) -> None:
        assert limit.description == expected

    @pytest.mark.parametrize(
        ("seconds", "expected"), [(30, "30 seconds"), (60, "a minute"), (900, "15 minutes")]
    )
    def test_waits_are_phrased_the_way_someone_would_say_them(
        self, seconds: int, expected: str
    ) -> None:
        assert _phrase(seconds) == expected


class TestMemoryIsBounded:
    def test_inactive_keys_are_swept_without_a_background_task(
        self, limiter: InMemoryRateLimiter, clock: Clock
    ) -> None:
        """One key per client address, never removed, is a slow leak that only shows up in
        production. The sweep runs on request volume rather than on a timer."""
        from atlas.security.rate_limit import PRUNE_EVERY

        limit = Limit(requests=5, seconds=60)
        for index in range(PRUNE_EVERY // 2):
            limiter.check(f"visitor-{index}", limit)

        before = limiter.tracked_keys
        clock.advance(7200)
        for index in range(PRUNE_EVERY):
            limiter.check("active", limit)

        assert limiter.tracked_keys < before, (
            f"{before} keys before, {limiter.tracked_keys} after — nothing was swept"
        )


class TestSecurityHeaders:
    async def test_every_response_carries_the_baseline_headers(
        self, client: AsyncClient, api: str
    ) -> None:
        headers = (await client.get(f"{api}/health")).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert "no-store" in headers["cache-control"]
        assert "default-src 'none'" in headers["content-security-policy"]

    async def test_hsts_is_absent_when_cookies_are_not_https_only(
        self, client: AsyncClient, api: str
    ) -> None:
        """Pinning localhost to HTTPS in a developer's browser is painful to undo, and the
        header is ignored over plain HTTP anyway."""
        assert "strict-transport-security" not in (await client.get(f"{api}/health")).headers


class TestBruteForceIsRefused:
    """The reason this module exists."""

    async def test_repeated_wrong_passwords_stop_being_answered(
        self, registered_client: AsyncClient, client: AsyncClient, api: str
    ) -> None:
        attempts = [
            await client.post(
                f"{api}/auth/login",
                json={"email": REGISTRATION["email"], "password": f"wrong-guess-{index}"},
            )
            for index in range(LOGIN_PER_ACCOUNT.requests + 3)
        ]
        codes = [response.status_code for response in attempts]

        assert 429 in codes, f"no attempt was refused: {codes}"
        assert codes[-1] == 429, "the limit must keep holding, not lapse"
        assert codes.count(401) <= LOGIN_PER_ACCOUNT.requests

    async def test_a_refusal_says_when_to_come_back(
        self, registered_client: AsyncClient, client: AsyncClient, api: str
    ) -> None:
        last = None
        for index in range(LOGIN_PER_ACCOUNT.requests + 2):
            last = await client.post(
                f"{api}/auth/login",
                json={"email": REGISTRATION["email"], "password": f"wrong-{index}"},
            )

        assert last is not None and last.status_code == 429
        assert "retry-after" in last.headers, "a 429 must carry Retry-After"
        assert int(last.headers["retry-after"]) > 0
        assert last.json()["error"]["code"] == "rate_limited"

    async def test_the_limit_follows_the_account_not_the_capitalisation(
        self, registered_client: AsyncClient, client: AsyncClient, api: str
    ) -> None:
        """Otherwise changing one letter's case resets the counter and defeats the whole thing."""
        for index in range(LOGIN_PER_ACCOUNT.requests):
            await client.post(
                f"{api}/auth/login",
                json={"email": REGISTRATION["email"], "password": f"wrong-{index}"},
            )

        shouted = await client.post(
            f"{api}/auth/login",
            json={"email": REGISTRATION["email"].upper(), "password": "wrong-again"},
        )
        assert shouted.status_code == 429

    async def test_the_right_password_still_works_before_the_limit(
        self, registered_client: AsyncClient, client: AsyncClient, api: str
    ) -> None:
        """A few typos must not lock someone out of their own account."""
        for index in range(3):
            await client.post(
                f"{api}/auth/login",
                json={"email": REGISTRATION["email"], "password": f"typo-{index}"},
            )

        signed_in = await client.post(
            f"{api}/auth/login",
            json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
        )
        assert signed_in.status_code == 200

    async def test_succeeding_clears_the_accounts_counter(
        self, registered_client: AsyncClient, client: AsyncClient, api: str
    ) -> None:
        """So a bad session of typos does not follow someone around after they get it right."""
        for index in range(LOGIN_PER_ACCOUNT.requests - 1):
            await client.post(
                f"{api}/auth/login",
                json={"email": REGISTRATION["email"], "password": f"typo-{index}"},
            )
        await client.post(
            f"{api}/auth/login",
            json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
        )

        retried = await client.post(
            f"{api}/auth/login", json={"email": REGISTRATION["email"], "password": "typo-again"}
        )
        assert retried.status_code == 401, "the counter should have been cleared, not exhausted"


class TestRegistrationIsBounded:
    async def test_accounts_cannot_be_created_in_bulk(self, client: AsyncClient, api: str) -> None:
        codes = [
            (
                await client.post(
                    f"{api}/auth/register",
                    json={
                        "email": f"bulk-{index}@atlas.dev",
                        "full_name": f"Bulk {index}",
                        "password": "a-sufficiently-long-password",
                    },
                )
            ).status_code
            for index in range(REGISTRATION_PER_ADDRESS.requests + 2)
        ]

        assert 429 in codes, f"registration was never refused: {codes}"
        assert codes.count(201) <= REGISTRATION_PER_ADDRESS.requests


class TestExpensiveWorkIsBounded:
    async def test_search_is_limited_per_user(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Cheap per call, but the debounced UI issues one per pause in typing."""
        from atlas.security.policy import SEARCH_PER_USER

        codes = set()
        for index in range(SEARCH_PER_USER.requests + 2):
            response = await registered_client.get(f"{api}/assistant/search?q=query{index}")
            codes.add(response.status_code)
            if response.status_code == 429:
                break

        assert 429 in codes
