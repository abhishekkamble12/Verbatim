"""Structured JSON logging with trace context propagation."""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variables for distributed tracing across async / sync boundaries
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
_notebook_id_var: ContextVar[str | None] = ContextVar("notebook_id", default=None)


def get_trace_id() -> str | None:
    return _trace_id_var.get()


def get_user_id() -> str | None:
    return _user_id_var.get()


def get_notebook_id() -> str | None:
    return _notebook_id_var.get()


@contextmanager
def bind_trace_context(
    trace_id: str | None = None,
    user_id: str | None = None,
    notebook_id: str | None = None,
):
    """Context manager to bind trace and tenant context for the duration of a block."""
    tid = trace_id or f"tr_{uuid.uuid4().hex[:12]}"
    token_trace = _trace_id_var.set(tid)
    token_user = _user_id_var.set(user_id) if user_id is not None else None
    token_nb = _notebook_id_var.set(notebook_id) if notebook_id is not None else None
    try:
        yield tid
    finally:
        _trace_id_var.reset(token_trace)
        if token_user is not None:
            _user_id_var.reset(token_user)
        if token_nb is not None:
            _notebook_id_var.reset(token_nb)


def clear_trace_context() -> None:
    _trace_id_var.set(None)
    _user_id_var.set(None)
    _notebook_id_var.set(None)


class JsonFormatter(logging.Formatter):
    """Formats log records as structured, single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject contextvars if present
        trace_id = get_trace_id()
        if trace_id:
            data["trace_id"] = trace_id
        user_id = get_user_id()
        if user_id:
            data["user_id"] = user_id
        notebook_id = get_notebook_id()
        if notebook_id:
            data["notebook_id"] = notebook_id

        # Include any extra fields passed in record.__dict__
        standard_keys = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message",
        }
        for k, v in record.__dict__.items():
            if k not in standard_keys and not k.startswith("_"):
                data[k] = v

        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        return json.dumps(data)


class TraceSpan:
    """Represents a measured span in a trace."""

    def __init__(self, name: str, logger: logging.Logger, attributes: dict[str, Any] | None = None):
        self.name = name
        self.logger = logger
        self.attributes = dict(attributes or {})
        self.start_time: float = 0.0

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def __enter__(self):
        self.start_time = time.perf_counter()
        self.logger.info(
            f"Started span: {self.name}",
            extra={"event": "span_start", "span_name": self.name, **self.attributes},
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = round((time.perf_counter() - self.start_time) * 1000.0, 2)
        extra = {
            "event": "span_finish",
            "span_name": self.name,
            "duration_ms": duration_ms,
            **self.attributes,
        }
        if exc_type is not None:
            extra["error"] = str(exc_val)
            self.logger.error(f"Span {self.name} failed after {duration_ms}ms", extra=extra)
        else:
            self.logger.info(f"Finished span: {self.name} in {duration_ms}ms", extra=extra)
        return False


def trace_span(name: str, logger: logging.Logger | None = None, **attributes) -> TraceSpan:
    """Measure duration and emit structured logs for a named execution span."""
    log = logger or logging.getLogger("citeguard.trace")
    return TraceSpan(name, log, attributes)


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the JsonFormatter."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
