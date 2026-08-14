"""HTTP middleware: request correlation, access logging, and security headers."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from atlas.core.logging import bind_request_context, clear_request_context, get_logger

logger = get_logger("atlas.access")

REQUEST_ID_HEADER = "x-request-id"

_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    # The API only ever returns JSON, so nothing needs to load.
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign each request an id, log its outcome, and stamp security headers."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        clear_request_context()
        bind_request_context(request_id=request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handler produces the response; this only records timing.
            logger.exception(
                "%s %s failed",
                request.method,
                request.url.path,
                extra={"duration_ms": round((time.perf_counter() - started) * 1000, 2)},
            )
            clear_request_context()
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        logger.info(
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"status": response.status_code, "duration_ms": duration_ms},
        )
        clear_request_context()
        return response
