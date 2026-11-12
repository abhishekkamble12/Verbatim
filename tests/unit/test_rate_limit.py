"""Unit tests for token bucket rate limiting in services.api.rate_limit."""

import time

import pytest
from fastapi import HTTPException

from services.api.rate_limit import RateLimiter, TokenBucket, rate_limit


def test_token_bucket_initial_burst():
    bucket = TokenBucket(rate=1.0, capacity=3.0)  # 1 token/sec, max 3
    # Initial capacity allows 3 immediate consumes
    allowed, retry_after = bucket.consume()
    assert allowed is True
    assert retry_after == 0.0

    allowed, retry_after = bucket.consume()
    assert allowed is True

    allowed, retry_after = bucket.consume()
    assert allowed is True

    # 4th consume should fail with non-zero retry_after
    allowed, retry_after = bucket.consume()
    assert allowed is False
    assert retry_after > 0.0


def test_token_bucket_refill():
    bucket = TokenBucket(rate=10.0, capacity=2.0)  # 10 tokens/sec
    # Consume all
    assert bucket.consume()[0] is True
    assert bucket.consume()[0] is True
    assert bucket.consume()[0] is False

    # Wait 0.15s (should add ~1.5 tokens)
    time.sleep(0.15)
    allowed, _ = bucket.consume()
    assert allowed is True


def test_rate_limiter_per_user_and_action():
    limiter = RateLimiter(limits={"chat": (1.0, 2.0)})  # 1 req/s, burst 2

    # User 1 consumes 2 tokens
    limiter.check("user-1", "chat")
    limiter.check("user-1", "chat")

    # User 1 3rd call raises HTTPException 429 with Retry-After header
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("user-1", "chat")

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers
    assert int(exc_info.value.headers["Retry-After"]) >= 1

    # User 2 is independent and should succeed
    limiter.check("user-2", "chat")


def test_rate_limiter_unknown_action_defaults():
    limiter = RateLimiter(default_limit=(10.0, 10.0))
    # Any unregistered action uses default limit
    limiter.check("user-1", "custom_action")


def test_rate_limit_fastapi_dependency():
    dep = rate_limit("upload")
    # Consumes upload token
    dep("user_dep_test")


def test_rate_limiter_reset():
    limiter = RateLimiter(limits={"chat": (1.0 / 60.0, 1.0)})
    limiter.check("user_reset", "chat")
    with pytest.raises(HTTPException):
        limiter.check("user_reset", "chat")

    limiter.reset()
    # After reset, user can call again
    limiter.check("user_reset", "chat")


def test_rate_limiter_disabled(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    limiter = RateLimiter(limits={"chat": (1.0 / 60.0, 1.0)})
    for _ in range(10):
        limiter.check("user_unlimited", "chat")


