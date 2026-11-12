"""Unit tests for structured JSON logging and trace propagation in packages.observability."""

import io
import json
import logging

from packages.observability.logging import (
    JsonFormatter,
    bind_trace_context,
    clear_trace_context,
    get_trace_id,
    trace_span,
)


def test_json_formatter_outputs_valid_json():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    test_logger = logging.getLogger("test_structured_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    test_logger.info("Test message", extra={"custom_metric": 42, "endpoint": "/chat"})

    output = stream.getvalue().strip()
    data = json.loads(output)

    assert data["message"] == "Test message"
    assert data["level"] == "INFO"
    assert data["logger"] == "test_structured_logger"
    assert data["custom_metric"] == 42
    assert data["endpoint"] == "/chat"
    assert "timestamp" in data


def test_trace_context_binding():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    test_logger = logging.getLogger("test_context_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    clear_trace_context()
    assert get_trace_id() is None

    with bind_trace_context(trace_id="tr_123456", user_id="user_alice", notebook_id="nb_789"):
        assert get_trace_id() == "tr_123456"
        test_logger.info("User action occurred")

    output = stream.getvalue().strip()
    data = json.loads(output)
    assert data["trace_id"] == "tr_123456"
    assert data["user_id"] == "user_alice"
    assert data["notebook_id"] == "nb_789"

    # Context should be restored/cleared after exit
    assert get_trace_id() is None


def test_trace_span_measures_latency_and_records_attributes():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    test_logger = logging.getLogger("test_span_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    with trace_span("hybrid_retrieval", logger=test_logger, top_k=10) as span:
        span.set_attribute("results_count", 5)

    lines = [json.loads(line) for line in stream.getvalue().strip().split("\n") if line]
    assert len(lines) == 2  # start and finish logs

    start_log, finish_log = lines[0], lines[1]
    assert start_log["event"] == "span_start"
    assert start_log["span_name"] == "hybrid_retrieval"

    assert finish_log["event"] == "span_finish"
    assert finish_log["span_name"] == "hybrid_retrieval"
    assert finish_log["results_count"] == 5
    assert "duration_ms" in finish_log
    assert finish_log["duration_ms"] >= 0.0
