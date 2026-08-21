"""Password hashing and token primitives.

Two token types, deliberately different:

* **Access token** — a short-lived signed JWT. Stateless, so authenticating a request costs no
  database round trip.
* **Refresh token** — a long-lived opaque random string. Only its SHA-256 hash is stored, so a
  database leak does not yield usable tokens. Rotated on every use; presenting an already-used
  token revokes the whole session (see `AuthService.refresh`).

Both are delivered as httpOnly cookies, never to JavaScript.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ALGORITHM = "HS256"
_password_hasher = PasswordHasher()

ACCESS_COOKIE_NAME = "turex_access"
REFRESH_COOKIE_NAME = "turex_refresh"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def password_hash_needs_update(password_hash: str) -> bool:
    """True when argon2 parameters have changed since this hash was written."""
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_tokens_match(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(token), stored_hash)


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: str
    session_id: str
    expires_at: datetime


def create_access_token(*, user_id: str, session_id: str, secret_key: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "sid": session_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str, *, secret_key: str) -> AccessTokenClaims | None:
    """Return the claims, or None if the token is expired, tampered with, or malformed."""
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "sid", "exp"]},
        )
    except jwt.PyJWTError:
        return None

    if payload.get("typ") != "access":
        return None

    return AccessTokenClaims(
        user_id=str(payload["sub"]),
        session_id=str(payload["sid"]),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
