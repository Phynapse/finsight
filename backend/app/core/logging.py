"""Structured logging with per-request correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from typing import Any

_configured = False

_request_id: ContextVar[str | None] = ContextVar("finsight_request_id", default=None)

_LOG_RECORD_FIELDS = (
    "name",
    "levelname",
    "pathname",
    "lineno",
    "msg",
    "args",
    "exc_info",
    "stack_info",
)


def new_request_id() -> str:
    """Generate a short, opaque correlation ID."""
    import uuid

    return uuid.uuid4().hex[:16]


def set_request_id(request_id: str | None) -> Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Attach the active request ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log shippers."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in ("http_method", "http_path", "http_status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable console output for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Install the FinSight logging configuration exactly once."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else ConsoleFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Keep third-party libraries from drowning out application logs.
    for noisy in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger that always carries the request ID filter."""
    logger = logging.getLogger(name)
    if not any(isinstance(existing, RequestIdFilter) for existing in logger.filters):
        logger.addFilter(RequestIdFilter())
    return logger