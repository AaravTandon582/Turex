"""Request and response models for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, EmailStr, Field, field_validator

from atlas.schemas.base import AtlasModel

MIN_PASSWORD_LENGTH = 10


class UserRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    created_at: datetime


class RegisterRequest(AtlasModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be blank")
        return stripped

    @field_validator("password")
    @classmethod
    def _reject_trivial_passwords(cls, value: str) -> str:
        # Length alone lets through "aaaaaaaaaa". Requiring some variety costs the user
        # nothing and removes the weakest passwords without a full strength meter.
        if len(set(value)) < 5:
            raise ValueError("Password is too repetitive — use a longer, more varied phrase")
        return value


class LoginRequest(AtlasModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class SessionResponse(AtlasModel):
    """Returned on register, login, and refresh.

    The tokens themselves are set as httpOnly cookies and deliberately absent from the body —
    the client cannot read them, so there is nothing useful to include.
    """

    user: UserRead
    access_token_expires_at: datetime
