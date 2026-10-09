"""HTTP middleware: query sanitising, request correlation, access logging, security headers."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from turex.core.logging import bind_request_context, clear_request_context, get_logger
from turex.schemas.base import clean_text

logger = get_logger("turex.access")

REQUEST_ID_HEADER = "x-request-id"

_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    # The API only ever returns JSON, so nothing needs to load.
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    # Browsers must not offer to cache a response that contains someone's library.
    "cache-control": "no-store",
}

HSTS_HEADER = "strict-transport-security"
HSTS_VALUE = "max-age=31536000; includeSubDomains"
"""Sent only when cookies are already HTTPS-only.

Sending it over plain HTTP would be ignored by browsers, and sending it from a development
server reachable at localhost would pin the whole of localhost to HTTPS in the developer's
browser — which is remarkably annoying to undo.
"""


class QuerySanitisingMiddleware:
    """Strip characters from the query string that PostgreSQL cannot store.

    `TurexModel` cleans every string in a request *body*, in one place, for the reason its
    docstring gives: a per-field validator is one that can be forgotten. Query parameters were
    never covered by it. A parameter declared as a model — `PaperFilters` — inherits the
    cleaning and is safe; one declared as a bare `Annotated[str, Query()]` is not, and three
    were: the catalog's `q` and `category`, and the assistant's semantic search. A null byte in
    any of them reached asyncpg and came back as a 500, from a URL anyone could type.

    Fixing it here rather than on those three parameters is the same argument one layer down.
    The next search parameter someone adds is covered without knowing this exists.

    Raw ASGI rather than `BaseHTTPMiddleware`, because the query string has to be corrected
    before routing reads it, and `parse_qsl` percent-decodes, so `%00` is caught as well as a
    literal byte. Untouched requests keep their original query string byte for byte: the
    rewrite only happens when cleaning actually removed something.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("query_string"):
            cleaned = self._clean(scope["query_string"])
            if cleaned is not None:
                scope = {**scope, "query_string": cleaned}
        await self._app(scope, receive, send)

    @staticmethod
    def _clean(raw: bytes) -> bytes | None:
        """The cleaned query string, or None when there was nothing to remove."""
        pairs = parse_qsl(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
        cleaned = [(clean_text(key), clean_text(value)) for key, value in pairs]
        if cleaned == pairs:
            return None
        return urlencode(cleaned).encode("utf-8")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign each request an id, log its outcome, and stamp security headers."""

    def __init__(self, app: ASGIApp, *, send_hsts: bool = False) -> None:
        super().__init__(app)
        self._send_hsts = send_hsts

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
        if self._send_hsts:
            response.headers.setdefault(HSTS_HEADER, HSTS_VALUE)

        logger.info(
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"status": response.status_code, "duration_ms": duration_ms},
        )
        clear_request_context()
        return response
