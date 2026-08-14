"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.core.config import Settings, get_settings
from atlas.core.errors import UnauthenticatedError
from atlas.core.logging import bind_request_context
from atlas.core.security import ACCESS_COOKIE_NAME, decode_access_token
from atlas.db.session import get_db
from atlas.models.user import User, UserSession
from atlas.services.auth_service import AuthService, ClientInfo

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]


def get_auth_service(db: DbDep, settings: SettingsDep) -> AuthService:
    return AuthService(db, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(request: Request, db: DbDep, settings: SettingsDep) -> User:
    """Resolve the signed-in user, or reject the request.

    The session row is checked alongside the token so that signing out takes effect
    immediately rather than when the access token happens to expire.
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise UnauthenticatedError(detail="no access cookie present")

    claims = decode_access_token(token, secret_key=settings.secret_key)
    if claims is None:
        raise UnauthenticatedError(detail="access token invalid or expired")

    try:
        user_id = uuid.UUID(claims.user_id)
        session_id = uuid.UUID(claims.session_id)
    except ValueError as exc:
        raise UnauthenticatedError(detail="access token carried malformed identifiers") from exc

    row = (
        await db.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .where(User.id == user_id, UserSession.id == session_id)
        )
    ).first()

    if row is None:
        raise UnauthenticatedError(detail="session no longer exists")

    user, session = row
    if not session.is_active:
        raise UnauthenticatedError(detail="session revoked or expired")
    if not user.is_active:
        raise UnauthenticatedError(detail="user account is disabled")

    bind_request_context(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
