"""
Structured JSON logging for all Alpha0Engine services.

Usage:
    from shared.logging import get_logger
    logger = get_logger("my-service")
    logger.info("scored entity", extra={"ticker": "AAPL", "score": 0.85, "duration_ms": 42})

In production (ENV=prod/staging): JSON one-line per log.
In development: human-readable colored output.
"""
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Optional

_request_ctx: ContextVar[dict] = ContextVar("request_ctx", default={})


def bind_context(**kwargs):
    _request_ctx.set({**_request_ctx.get(), **kwargs})


def clear_context():
    _request_ctx.set({})


class JSONFormatter(logging.Formatter):
    """Single-line JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z",
            "level": record.levelname,
            "service": getattr(record, "service", record.name),
            "msg": record.getMessage(),
        }

        ctx = _request_ctx.get()
        if ctx:
            payload.update(ctx)

        for key in ("ticker", "action", "duration_ms", "entity_id", "error",
                     "status_code", "method", "path", "records", "tier"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val

        if record.exc_info and record.exc_info[1]:
            payload["error"] = str(record.exc_info[1])
            payload["error_type"] = type(record.exc_info[1]).__name__

        return json.dumps(payload, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = self.formatTime(record, "%H:%M:%S")
        base = f"{color}{ts} [{record.levelname:>7}]{self.RESET} {record.name}: {record.getMessage()}"

        extras = []
        for key in ("ticker", "action", "duration_ms", "entity_id", "records", "tier"):
            val = getattr(record, key, None)
            if val is not None:
                extras.append(f"{key}={val}")
        ctx = _request_ctx.get()
        for k, v in ctx.items():
            extras.append(f"{k}={v}")

        if extras:
            base += f"  [{', '.join(extras)}]"
        if record.exc_info and record.exc_info[1]:
            base += f"\n  {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        return base


def setup_logging(service_name: str, level: Optional[str] = None):
    """Configure root logger for the current service process."""
    env = os.environ.get("ENV", "dev").lower()
    log_level = level or os.environ.get("LOG_LEVEL", "INFO")

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if env in ("prod", "staging", "production"):
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(DevFormatter())

    root.addHandler(handler)

    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.service = service_name
        return record

    logging.setLogRecordFactory(record_factory)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Call setup_logging() once at service startup first."""
    return logging.getLogger(name)


class Timer:
    """Context manager that logs duration_ms on exit."""

    def __init__(self, logger: logging.Logger, action: str, **extra):
        self.logger = logger
        self.action = action
        self.extra = extra
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = round((time.perf_counter() - self.start) * 1000, 1)
        extra = {**self.extra, "action": self.action, "duration_ms": duration_ms}
        if exc_val:
            extra["error"] = str(exc_val)
            self.logger.error(f"{self.action} failed", extra=extra)
        else:
            self.logger.info(f"{self.action} completed", extra=extra)
        return False
