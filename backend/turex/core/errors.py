"""Application error types and the single error envelope the API returns.

Two audiences, two payloads. `message` is written for a person using Turex and is always safe
to display. `detail` is written for whoever is reading the logs and never crosses the wire
outside debug mode.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable identifiers the frontend can branch on. Never renamed, only added to."""

    validation_failed = "validation_failed"
    unauthenticated = "unauthenticated"
    invalid_credentials = "invalid_credentials"
    forbidden = "forbidden"
    not_found = "not_found"
    conflict = "conflict"
    payload_too_large = "payload_too_large"
    unsupported_media_type = "unsupported_media_type"
    rate_limited = "rate_limited"
    provider_unavailable = "provider_unavailable"
    provider_declined = "provider_declined"
    not_configured = "not_configured"
    processing_failed = "processing_failed"
    internal_error = "internal_error"


class AppError(Exception):
    """Base class for every error Turex raises deliberately.

    Anything else reaching the handler is a bug and is reported as `internal_error`.
    """

    status_code: int = 500
    code: ErrorCode = ErrorCode.internal_error
    message: str = "Turex couldn't complete that request. Try again."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.detail = detail
        self.context = context or {}
        super().__init__(self.detail or self.message)

    def to_payload(self) -> dict[str, Any]:
        """The wire format. `detail` is deliberately absent — it goes to the logs only.

        Keeping internals out of responses even in debug mode means two failures that must be
        indistinguishable to a caller (an unknown email versus a wrong password) stay that way
        no matter how the server is configured.
        """
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.context:
            payload["context"] = self.context
        return {"error": payload}


class ValidationError(AppError):
    status_code = 422
    code = ErrorCode.validation_failed
    message = "Some of that information isn't valid."


class UnauthenticatedError(AppError):
    status_code = 401
    code = ErrorCode.unauthenticated
    message = "Sign in to continue."


class InvalidCredentialsError(AppError):
    status_code = 401
    code = ErrorCode.invalid_credentials
    message = "That email and password combination doesn't match an account."


class ForbiddenError(AppError):
    status_code = 403
    code = ErrorCode.forbidden
    message = "You don't have access to that."


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.not_found
    message = "We couldn't find that."


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.conflict
    message = "That already exists."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = ErrorCode.payload_too_large
    message = "That file is too large."


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = ErrorCode.unsupported_media_type
    message = "Turex can't read that file type yet."


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.rate_limited
    message = "Too many requests. Wait a moment and try again."


class ProviderUnavailableError(AppError):
    """An upstream model or embedding provider failed in a way a retry might fix."""

    status_code = 503
    code = ErrorCode.provider_unavailable
    message = "Turex couldn't reach the AI service. Try again in a moment."


class ProviderDeclinedError(AppError):
    """The model declined to answer. Distinct from a failure — retrying will not help."""

    status_code = 422
    code = ErrorCode.provider_declined
    message = "Turex can't help with that request."


class NotConfiguredError(AppError):
    """A capability was used before its credentials or settings were supplied."""

    status_code = 503
    code = ErrorCode.not_configured
    message = "That feature isn't set up on this Turex instance yet."


class ProcessingFailedError(AppError):
    status_code = 422
    code = ErrorCode.processing_failed
    message = "Turex couldn't process that document."
