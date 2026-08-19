"""Authentication business logic.

The API layer owns cookies and HTTP status; this module owns the rules: who may sign in, what
a session is worth, and when a session must be destroyed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.core import security
from atlas.core.config import Settings
from atlas.core.errors import ConflictError, InvalidCredentialsError, UnauthenticatedError
from atlas.core.logging import get_logger
from atlas.models.user import User, UserSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """Everything the HTTP layer needs to set cookies and answer the request."""

    user: User
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    # -- registration and sign-in ------------------------------------------------

    async def register(
        self, *, email: str, full_name: str, password: str, client: ClientInfo
    ) -> IssuedSession:
        user = User(
            email=normalize_email(email),
            full_name=full_name,
            password_hash=security.hash_password(password),
        )
        # A savepoint, not a full rollback: rolling back the whole transaction here would
        # discard any work the caller had already done and expire every object loaded in the
        # session, so a duplicate email would corrupt more than it reports.
        try:
            async with self._db.begin_nested():
                self._db.add(user)
                await self._db.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "An account with that email already exists.",
                detail="duplicate email on registration",
            ) from exc

        logger.info("user registered", extra={"user_id": str(user.id)})
        return await self._issue_session(user, client)

    async def login(self, *, email: str, password: str, client: ClientInfo) -> IssuedSession:
        user = await self._db.scalar(select(User).where(User.email == normalize_email(email)))

        # Hash even when the user is missing, so a wrong email and a wrong password take
        # comparable time and the endpoint does not confirm which addresses are registered.
        stored_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
        password_ok = security.verify_password(password, stored_hash)

        if user is None or not password_ok:
            raise InvalidCredentialsError(detail=f"failed login for {normalize_email(email)}")
        if not user.is_active:
            raise InvalidCredentialsError(detail=f"login attempt on disabled user {user.id}")

        if security.password_hash_needs_update(user.password_hash):
            user.password_hash = security.hash_password(password)

        user.last_login_at = datetime.now(UTC)
        logger.info("user signed in", extra={"user_id": str(user.id)})
        return await self._issue_session(user, client)

    # -- session lifecycle -------------------------------------------------------

    async def refresh(self, *, refresh_token: str, client: ClientInfo) -> IssuedSession:
        """Rotate a refresh token.

        A token that was already rotated away is treated as stolen: the session is revoked and
        the caller must sign in again.
        """
        token_hash = security.hash_refresh_token(refresh_token)

        replayed = await self._db.scalar(
            select(UserSession).where(UserSession.previous_token_hash == token_hash)
        )
        if replayed is not None:
            # Two things present a token that was just rotated away: a thief replaying a
            # stolen one, and a second browser tab that refreshed at the same moment. They are
            # indistinguishable from the token alone, so they are told apart by *when*.
            #
            # Inside the grace window it is a concurrent client. Revoking there would log
            # people out for having two tabs open, which is the failure that makes teams turn
            # rotation off altogether — a worse outcome than the race.
            within_grace = (
                replayed.rotated_at is not None
                and replayed.is_active
                and datetime.now(UTC) - replayed.rotated_at
                <= timedelta(seconds=self._settings.refresh_grace_seconds)
            )

            if within_grace:
                user = await self._db.get(User, replayed.user_id)
                if user is not None and user.is_active:
                    logger.info(
                        "refresh raced with a concurrent rotation; issuing a fresh token",
                        extra={"session_id": str(replayed.id)},
                    )
                    return await self._rotate(replayed, user, client)

            replayed.revoked_at = datetime.now(UTC)
            # Commit before raising. The request-scoped transaction rolls back on error, and
            # revoking a session whose token has demonstrably leaked must outlive that.
            await self._db.commit()
            logger.warning(
                "refresh token replay detected; session revoked",
                extra={"user_id": str(replayed.user_id), "session_id": str(replayed.id)},
            )
            raise UnauthenticatedError("Your session ended. Sign in again.")

        session = await self._db.scalar(
            select(UserSession).where(UserSession.refresh_token_hash == token_hash)
        )
        if session is None or not session.is_active:
            raise UnauthenticatedError("Your session expired. Sign in again.")

        user = await self._db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise UnauthenticatedError("Your session expired. Sign in again.")

        return await self._rotate(session, user, client)

    async def revoke(self, *, refresh_token: str | None) -> None:
        """Sign out. Missing or unknown tokens succeed silently — the goal state is reached."""
        if not refresh_token:
            return
        token_hash = security.hash_refresh_token(refresh_token)
        session = await self._db.scalar(
            select(UserSession).where(UserSession.refresh_token_hash == token_hash)
        )
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            logger.info("session revoked", extra={"session_id": str(session.id)})

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Sign out everywhere. Used after a password change or a suspected compromise."""
        sessions = await self._db.scalars(
            select(UserSession).where(
                UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
            )
        )
        now = datetime.now(UTC)
        count = 0
        for session in sessions:
            session.revoked_at = now
            count += 1
        return count

    async def get_active_session(self, session_id: uuid.UUID) -> UserSession | None:
        session = await self._db.get(UserSession, session_id)
        return session if session is not None and session.is_active else None

    # -- internals ---------------------------------------------------------------

    async def _issue_session(self, user: User, client: ClientInfo) -> IssuedSession:
        refresh_token = security.generate_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.refresh_token_ttl_seconds)
        session = UserSession(
            user_id=user.id,
            refresh_token_hash=security.hash_refresh_token(refresh_token),
            expires_at=expires_at,
            user_agent=client.user_agent,
            ip_address=client.ip_address,
        )
        self._db.add(session)
        await self._db.flush()
        return self._build(user, session, refresh_token)

    async def _rotate(self, session: UserSession, user: User, client: ClientInfo) -> IssuedSession:
        refresh_token = security.generate_refresh_token()
        session.previous_token_hash = session.refresh_token_hash
        session.refresh_token_hash = security.hash_refresh_token(refresh_token)
        session.rotated_at = datetime.now(UTC)
        session.expires_at = datetime.now(UTC) + timedelta(
            seconds=self._settings.refresh_token_ttl_seconds
        )
        if client.user_agent:
            session.user_agent = client.user_agent
        if client.ip_address:
            session.ip_address = client.ip_address
        await self._db.flush()
        return self._build(user, session, refresh_token)

    def _build(self, user: User, session: UserSession, refresh_token: str) -> IssuedSession:
        access_token = security.create_access_token(
            user_id=str(user.id),
            session_id=str(session.id),
            secret_key=self._settings.secret_key,
            ttl_seconds=self._settings.access_token_ttl_seconds,
        )
        return IssuedSession(
            user=user,
            access_token=access_token,
            access_token_expires_at=datetime.now(UTC)
            + timedelta(seconds=self._settings.access_token_ttl_seconds),
            refresh_token=refresh_token,
            refresh_token_expires_at=session.expires_at,
        )


# Verified against when no user matches, purely to equalise response time.
_DUMMY_PASSWORD_HASH = security.hash_password("atlas-timing-equaliser")
