"""Comprehensive unit and edge-case tests for CiteGuard advanced features:
- SSRF guard protection & DNS rebinding edge cases
- Circuit breaker state machine & concurrency
- Token bucket rate limiter & concurrency
- Structured JSON logging & distributed trace propagation
- Upload size boundary enforcement
"""

import concurrent.futures
import io
import json
import logging
import socket

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from packages.ingestion.ssrf_guard import SSRFBlockedError, validate_url_safe
from packages.llm_gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from packages.observability.logging import (
    JsonFormatter,
    bind_trace_context,
    get_trace_id,
    trace_span,
)
from services.api.main import MAX_UPLOAD_BYTES, CreateUploadRequest
from services.api.rate_limit import RateLimiter, TokenBucket

# ==============================================================================
# 1. SSRF Guard Edge Cases
# ==============================================================================


@pytest.mark.parametrize(
    "malicious_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://127.0.0.1:8000/internal",
        "http://127.0.0.2:9000",
        "http://localhost:5432",
        "http://0.0.0.0:80",
        "http://10.0.0.1/admin",
        "http://10.255.255.255",
        "http://172.16.0.1",
        "http://172.31.255.255",
        "http://192.168.0.1",
        "http://192.168.100.50",
        "http://[::1]:8080",
        "http://[fe80::1]",
        "http://[fc00::1]",
        "file:///etc/passwd",
        "ftp://private.corp/data",
        "gopher://127.0.0.1:70",
    ],
)
def test_ssrf_guard_blocks_all_private_and_metadata_targets(malicious_url):
    with pytest.raises(SSRFBlockedError):
        validate_url_safe(malicious_url)


def test_ssrf_guard_blocks_dns_rebinding_to_metadata(monkeypatch):
    """Simulates an attacker domain resolving to AWS IMDS 169.254.169.254."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
    with pytest.raises(SSRFBlockedError) as exc_info:
        validate_url_safe("https://evil-metadata-rebind.com")
    assert "blocked" in str(exc_info.value).lower()


def test_ssrf_guard_blocks_empty_and_invalid_urls():
    for invalid in ["", "   ", "not-a-url", "http://", "https://"]:
        with pytest.raises(SSRFBlockedError):
            validate_url_safe(invalid)


# ==============================================================================
# 2. Circuit Breaker Concurrent & Edge Cases
# ==============================================================================


def test_circuit_breaker_concurrency():
    """Verify thread-safety when multiple worker threads execute through the breaker."""
    cb = CircuitBreaker(failure_threshold=50, cooldown_seconds=2.0)

    def work(i: int):
        return cb.call(lambda: i * 2)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(work, range(100)))

    assert len(results) == 100
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_circuit_breaker_fast_fail_does_not_call_function():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)

    # First call trips it
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    assert cb.state == CircuitState.OPEN

    call_count = 0

    def expensive_llm_call():
        nonlocal call_count
        call_count += 1
        return "expensive"

    # Next 10 calls fast-fail immediately without calling expensive_llm_call
    for _ in range(10):
        with pytest.raises(CircuitOpenError):
            cb.call(expensive_llm_call)

    assert call_count == 0


# ==============================================================================
# 3. Token Bucket Rate Limiter Concurrency & Accuracy
# ==============================================================================


def test_token_bucket_thread_safety():
    """Verify that multiple threads cannot over-consume beyond capacity."""
    bucket = TokenBucket(rate=0.0, capacity=10.0)  # zero refill to test atomic consumption
    consumed = 0

    def try_consume():
        nonlocal consumed
        allowed, _ = bucket.consume(1.0)
        if allowed:
            consumed += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: try_consume(), range(50)))

    # Exactly 10 tokens must have been granted, no more
    assert consumed == 10


def test_rate_limiter_isolated_tenants():
    limiter = RateLimiter(limits={"chat": (1.0 / 60.0, 1.0)})  # 1 request allowed

    # Alice uses her token
    limiter.check("user_alice", "chat")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("user_alice", "chat")
    assert exc_info.value.status_code == 429

    # Bob has his own bucket and is not blocked by Alice
    limiter.check("user_bob", "chat")


# ==============================================================================
# 4. Observability & Trace Context Propagation
# ==============================================================================


def test_trace_span_error_recording():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("test_error_span")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    with pytest.raises(ValueError):
        with trace_span("faulty_step", logger=logger, attempt=1):
            raise ValueError("Downstream calculation error")

    logs = [json.loads(line) for line in stream.getvalue().strip().split("\n") if line]
    assert len(logs) == 2
    finish_log = logs[1]
    assert finish_log["event"] == "span_finish"
    assert finish_log["error"] == "Downstream calculation error"
    assert finish_log["attempt"] == 1
    assert "duration_ms" in finish_log


def test_nested_trace_spans():
    with bind_trace_context(trace_id="tr_parent"):
        assert get_trace_id() == "tr_parent"
        with trace_span("outer_span"):
            assert get_trace_id() == "tr_parent"
            with trace_span("inner_span"):
                assert get_trace_id() == "tr_parent"
        assert get_trace_id() == "tr_parent"


# ==============================================================================
# 5. Upload Size Boundary Validation
# ==============================================================================


def test_upload_request_rejects_oversized_files():
    # Valid size (e.g. 10 MB)
    req = CreateUploadRequest(filename="paper.pdf", file_size_bytes=10 * 1024 * 1024)
    assert req.file_size_bytes == 10 * 1024 * 1024

    # Exactly 50 MB
    req_max = CreateUploadRequest(filename="paper.pdf", file_size_bytes=MAX_UPLOAD_BYTES)
    assert req_max.file_size_bytes == MAX_UPLOAD_BYTES

    # Exceeding 50 MB by 1 byte -> raises Pydantic ValidationError
    with pytest.raises(ValidationError):
        CreateUploadRequest(filename="paper.pdf", file_size_bytes=MAX_UPLOAD_BYTES + 1)

    # Negative / zero bytes -> raises ValidationError
    with pytest.raises(ValidationError):
        CreateUploadRequest(filename="paper.pdf", file_size_bytes=0)
