"""Observability package for CiteGuard: structured logging, distributed tracing, and metrics."""

from packages.observability.logging import (
    JsonFormatter,
    bind_trace_context,
    clear_trace_context,
    configure_structured_logging,
    get_logger,
    get_trace_id,
    trace_span,
)

__all__ = [
    "JsonFormatter",
    "bind_trace_context",
    "clear_trace_context",
    "configure_structured_logging",
    "get_logger",
    "get_trace_id",
    "trace_span",
]

