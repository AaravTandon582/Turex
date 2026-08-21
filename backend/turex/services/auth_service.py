"""Authentication business logic.

The API layer owns cookies and HTTP status; this module owns the rules: who may sign in, what
a session is worth, and when a session must be destroyed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from turex.core import security
from turex.core.config import Settings
from turex.core.errors import ConflictError, InvalidCredentialsError, UnauthenticatedError
from turex.core.logging import get_logger
from turex.models.user import User, UserSession

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

        A token presented after it was rotated away is treated as stolen and ends the session —
        unless it arrives inside the grace window, which is what several browser tabs
        refreshing at the same moment look like.

        The row is locked for the duration. Without the lock, concurrent refreshes all read the
        session before any of them commits, each believes it holds the current token, and the
        last write wins — leaving the other clients holding tokens that were never stored.
        """
        token_hash = security.hash_refresh_token(refresh_token)

        # One query, one lock. Matching both columns together avoids taking two locks in an
        # order that could deadlock, and means the decision below is made on state that cannot
        # change underneath it.
        session = await self._db.scalar(
            select(UserSession)
            .where(
                or_(
                    UserSession.refresh_token_hash == token_hash,
                    UserSession.previous_token_hash == token_hash,
                )
            )
            .with_for_update()
        )
        if session is None:
            raise UnauthenticatedError("Your session expired. Sign in again.")

        presented_previous = session.refresh_token_hash != token_hash

        if presented_previous:
            within_grace = (
                session.rotated_at is not None
                and session.is_active
                and datetime.now(UTC) - session.rotated_at
                <= timedelta(seconds=self._settings.refresh_grace_seconds)
            )
            if not within_grace:
                session.revoked_at = datetime.now(UTC)
                # Commit before raising. The request-scoped transaction rolls back on error,
                # and revoking a session whose token has demonstrably leaked must outlive that.
                await self._db.commit()
                logger.warning(
                    "refresh token replay detected; session revoked",
                    extra={"user_id": str(session.user_id), "session_id": str(session.id)},
                )
                raise UnauthenticatedError("Your session ended. Sign in again.")

        if not session.is_active:
            raise UnauthenticatedError("Your session expired. Sign in again.")

        user = await self._db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise UnauthenticatedError("Your session expired. Sign in again.")

        if presented_previous:
            logger.info(
                "refresh raced with a concurrent rotation; issuing a fresh token",
                extra={"session_id": str(session.id)},
            )

        # A racing tab keeps the window anchored where it was, so every request in the burst is
        # accepted and the window still closes on schedule instead of being pushed forward.
        return await self._rotate(session, user, client, preserve_window=presented_previous)

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

    async def _rotate(
        self,
        session: UserSession,
        user: User,
        client: ClientInfo,
        *,
        preserve_window: bool = False,
    ) -> IssuedSession:
        """Issue a new refresh token for this session.

        `preserve_window` is set when the caller presented the *previous* token inside the
        grace period — several tabs refreshing at once. Leaving the window anchored where it
        was means every tab in the burst is accepted, and the window still closes on schedule
        rather than being pushed forward by each new arrival.
        """
        refresh_token = security.generate_refresh_token()
        if not preserve_window:
            session.previous_token_hash = session.refresh_token_hash
            session.rotated_at = datetime.now(UTC)
        session.refresh_token_hash = security.hash_refresh_token(refresh_token)
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
_DUMMY_PASSWORD_HASH = security.hash_password("turex-timing-equaliser")
