"""Authentication workflow tests.

These cover the security-relevant behaviour of sessions: that credentials are checked, that
tokens rotate, that a replayed token destroys the session, and that signing out is immediate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.core.security import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from atlas.models.user import User, UserSession
from tests.conftest import REGISTRATION


class TestRegistration:
    async def test_creates_account_and_signs_user_in(self, client: AsyncClient, api: str) -> None:
        response = await client.post(f"{api}/auth/register", json=REGISTRATION)

        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == REGISTRATION["email"]
        assert body["user"]["full_name"] == REGISTRATION["full_name"]
        assert ACCESS_COOKIE_NAME in response.cookies
        assert REFRESH_COOKIE_NAME in response.cookies

    async def test_never_returns_the_password_hash(self, client: AsyncClient, api: str) -> None:
        response = await client.post(f"{api}/auth/register", json=REGISTRATION)
        assert "password" not in response.text.lower()

    async def test_stores_email_lowercased(
        self, client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        payload = {**REGISTRATION, "email": "Ada@Example.EDU"}
        await client.post(f"{api}/auth/register", json=payload)

        user = await db.scalar(select(User))
        assert user is not None
        assert user.email == "ada@example.edu"

    async def test_rejects_duplicate_email(self, client: AsyncClient, api: str) -> None:
        await client.post(f"{api}/auth/register", json=REGISTRATION)
        response = await client.post(f"{api}/auth/register", json=REGISTRATION)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("email", "not-an-email"),
            ("password", "short"),
            ("password", "aaaaaaaaaaaaaaa"),  # long but only one distinct character
            ("full_name", "   "),
        ],
    )
    async def test_rejects_invalid_input(
        self, client: AsyncClient, api: str, field: str, value: str
    ) -> None:
        response = await client.post(f"{api}/auth/register", json={**REGISTRATION, field: value})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"

    async def test_password_is_hashed_not_stored(
        self, client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        await client.post(f"{api}/auth/register", json=REGISTRATION)

        user = await db.scalar(select(User))
        assert user is not None
        assert user.password_hash != REGISTRATION["password"]
        assert user.password_hash.startswith("$argon2")


class TestLogin:
    async def test_signs_in_with_correct_credentials(self, client: AsyncClient, api: str) -> None:
        await client.post(f"{api}/auth/register", json=REGISTRATION)
        await client.post(f"{api}/auth/logout")

        response = await client.post(
            f"{api}/auth/login",
            json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
        )

        assert response.status_code == 200
        assert response.json()["user"]["email"] == REGISTRATION["email"]

    async def test_email_is_case_insensitive(self, client: AsyncClient, api: str) -> None:
        await client.post(f"{api}/auth/register", json=REGISTRATION)

        response = await client.post(
            f"{api}/auth/login",
            json={"email": "ADA@EXAMPLE.EDU", "password": REGISTRATION["password"]},
        )

        assert response.status_code == 200

    async def test_rejects_wrong_password(self, client: AsyncClient, api: str) -> None:
        await client.post(f"{api}/auth/register", json=REGISTRATION)

        response = await client.post(
            f"{api}/auth/login",
            json={"email": REGISTRATION["email"], "password": "wrong-password-entirely"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    async def test_unknown_email_is_indistinguishable_from_wrong_password(
        self, client: AsyncClient, api: str
    ) -> None:
        """Account enumeration defence: both failures must look identical to the caller."""
        await client.post(f"{api}/auth/register", json=REGISTRATION)

        wrong_password = await client.post(
            f"{api}/auth/login",
            json={"email": REGISTRATION["email"], "password": "wrong-password-entirely"},
        )
        unknown_email = await client.post(
            f"{api}/auth/login",
            json={"email": "nobody@example.edu", "password": "wrong-password-entirely"},
        )

        assert wrong_password.status_code == unknown_email.status_code
        assert wrong_password.json() == unknown_email.json()


class TestCurrentUser:
    async def test_returns_the_signed_in_user(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.get(f"{api}/auth/me")

        assert response.status_code == 200
        assert response.json()["email"] == REGISTRATION["email"]

    async def test_rejects_anonymous_requests(self, client: AsyncClient, api: str) -> None:
        response = await client.get(f"{api}/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    async def test_rejects_a_forged_token(self, client: AsyncClient, api: str) -> None:
        client.cookies.set(ACCESS_COOKIE_NAME, "not.a.real.token")
        response = await client.get(f"{api}/auth/me")

        assert response.status_code == 401


class TestRefresh:
    async def test_rotates_the_refresh_token(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        original = registered_client.cookies[REFRESH_COOKIE_NAME]

        response = await registered_client.post(f"{api}/auth/refresh")

        assert response.status_code == 200
        assert registered_client.cookies[REFRESH_COOKIE_NAME] != original

    async def test_replaying_a_rotated_token_revokes_the_session(
        self, registered_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        """A token replayed after the grace window is theft, and ends the session.

        The rotation is aged deliberately. Replaying *immediately* is the concurrent-tab case
        covered below, and the two must not be conflated — telling them apart is the whole
        point of recording when the rotation happened.
        """
        stolen = registered_client.cookies[REFRESH_COOKIE_NAME]
        await registered_client.post(f"{api}/auth/refresh")

        session = await db.scalar(select(UserSession))
        assert session is not None
        session.rotated_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()

        registered_client.cookies.set(REFRESH_COOKIE_NAME, stolen)
        response = await registered_client.post(f"{api}/auth/refresh")

        assert response.status_code == 401
        await db.refresh(session)
        assert session.revoked_at is not None, "replay must revoke the session, not just fail"

    async def test_tabs_refreshing_at_once_do_not_end_the_session(
        self, registered_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        """Several tabs refreshing together all present the token that was just rotated away.

        That is indistinguishable from a replay by token alone, and revoking there logs someone
        out for having tabs open. Before the grace window existed, five concurrent refreshes
        left the session dead.
        """
        import asyncio

        responses = await asyncio.gather(
            *[registered_client.post(f"{api}/auth/refresh") for _ in range(5)]
        )

        codes = [response.status_code for response in responses]
        assert all(code == 200 for code in codes), codes

        still_signed_in = await registered_client.get(f"{api}/auth/me")
        assert still_signed_in.status_code == 200, "the session was revoked by its own tabs"

        session = await db.scalar(select(UserSession))
        assert session is not None and session.revoked_at is None

    async def test_requires_a_refresh_cookie(self, client: AsyncClient, api: str) -> None:
        response = await client.post(f"{api}/auth/refresh")
        assert response.status_code == 401


class TestLogout:
    async def test_ends_the_session_immediately(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        access_token = registered_client.cookies[ACCESS_COOKIE_NAME]

        logout = await registered_client.post(f"{api}/auth/logout")
        assert logout.status_code == 204

        # Re-present the still-unexpired access token: it must no longer be honoured.
        registered_client.cookies.set(ACCESS_COOKIE_NAME, access_token)
        response = await registered_client.get(f"{api}/auth/me")
        assert response.status_code == 401

    async def test_is_safe_to_call_without_a_session(self, client: AsyncClient, api: str) -> None:
        response = await client.post(f"{api}/auth/logout")
        assert response.status_code == 204
