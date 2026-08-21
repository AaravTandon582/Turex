"""Translate exceptions into the single API error envelope.

Every failure the API returns has the shape ``{"error": {"code", "message", ...}}``. Handlers
raise domain errors; nothing constructs an error response by hand.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from turex.core.config import Settings
from turex.core.errors import AppError, ErrorCode, ValidationError
from turex.core.logging import get_logger

logger = get_logger(__name__)

_STATUS_TO_CODE = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.validation_failed,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.unauthenticated,
    status.HTTP_403_FORBIDDEN: ErrorCode.forbidden,
    status.HTTP_404_NOT_FOUND: ErrorCode.not_found,
    status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.not_found,
    status.HTTP_409_CONFLICT: ErrorCode.conflict,
    status.HTTP_413_CONTENT_TOO_LARGE: ErrorCode.payload_too_large,
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: ErrorCode.unsupported_media_type,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.rate_limited,
}

_GENERIC_MESSAGE = "Turex couldn't complete that request. Try again."


def _field_path(location: tuple[object, ...]) -> str:
    """Render Pydantic's location tuple as a dotted path, dropping the 'body'/'query' root."""
    parts = [str(part) for part in location if part not in ("body", "query", "path")]
    return ".".join(parts) or "request"


def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    del settings  # Responses are identical in every environment; see AppError.to_payload.

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error(
                "request failed: %s", exc.code.value, extra={"detail": exc.detail}, exc_info=exc
            )
        else:
            logger.info("request rejected: %s", exc.code.value, extra={"detail": exc.detail})
        # `Retry-After` is the standard way to tell a client when to come back, and a
        # well-behaved one will wait rather than retrying immediately and deepening the
        # problem it just hit.
        headers: dict[str, str] = {}
        retry_after = exc.context.get("retry_after_seconds")
        if isinstance(retry_after, int):
            headers["retry-after"] = str(retry_after)

        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_payload(),
            headers=headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": _field_path(error["loc"]), "message": error["msg"]} for error in exc.errors()
        ]
        error = ValidationError(context={"fields": fields})
        return JSONResponse(status_code=error.status_code, content=error.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.internal_error)
        message = exc.detail if isinstance(exc.detail, str) and exc.detail else _GENERIC_MESSAGE
        if exc.status_code >= 500:
            message = _GENERIC_MESSAGE
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code.value, "message": message}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Anything reaching here is a bug. Log it fully; tell the user nothing about it.
        logger.exception("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": ErrorCode.internal_error.value, "message": _GENERIC_MESSAGE}
            },
        )
