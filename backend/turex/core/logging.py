"""Structured logging.

Logs are JSON in production and human-readable locally. A request-scoped context carries the
request id and user id onto every record emitted while handling that request, so a single
failing request can be traced without threading a logger through every call.

Never log credentials or document contents. `redact()` exists for values that must be
mentioned but not exposed.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any, ClassVar

_request_context: ContextVar[dict[str, Any] | None] = ContextVar("request_context", default=None)

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def _current_context() -> dict[str, Any]:
    return _request_context.get() or {}


def bind_request_context(**values: Any) -> None:
    """Attach values to every log record emitted for the remainder of this request."""
    _request_context.set({**_current_context(), **values})


def clear_request_context() -> None:
    _request_context.set(None)


def redact(value: str | None, keep: int = 4) -> str:
    """Render a secret as a short fingerprint so it can be correlated but not reused."""
    if not value:
        return "<unset>"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{'*' * (len(value) - keep)}{value[-keep:]}"


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _current_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_record_extras(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Compact single-line output for local development."""

    _COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[38;5;245m",
        "INFO": "\033[38;5;39m",
        "WARNING": "\033[38;5;214m",
        "ERROR": "\033[38;5;203m",
        "CRITICAL": "\033[38;5;199m",
    }
    _RESET = "\033[0m"
    _DIM = "\033[38;5;245m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        head = f"{color}{record.levelname:<8}{self._RESET} {self._DIM}{record.name}{self._RESET}"
        line = f"{head}  {record.getMessage()}"
        extras = _record_extras(record)
        if extras:
            rendered = " ".join(f"{k}={v}" for k, v in extras.items())
            line += f"  {self._DIM}{rendered}{self._RESET}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(*, json_output: bool, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else ConsoleFormatter())
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn duplicates access logs through its own handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
