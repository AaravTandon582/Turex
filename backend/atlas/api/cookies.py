"""Session cookie handling.

Tokens live in httpOnly cookies rather than in a JavaScript-readable store, so a cross-site
scripting bug cannot exfiltrate a session. `SameSite=Lax` blocks the cross-site form-post CSRF
path while still allowing normal top-level navigation back into the app.
"""

from __future__ import annotations

from fastapi import Response

from atlas.core.config import Settings
from atlas.core.security import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from atlas.services.auth_service import IssuedSession

_REFRESH_PATH = "/api/v1/auth"
"""The refresh token is only ever sent to the auth endpoints, so it is scoped to them."""


def set_session_cookies(response: Response, session: IssuedSession, settings: Settings) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        session.access_token,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        session.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path=_REFRESH_PATH,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        ACCESS_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path=_REFRESH_PATH,
    )
