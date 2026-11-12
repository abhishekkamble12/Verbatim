"""Token-bucket rate limiting for CiteGuard API.

Enforces per-user rate limits on costly operations (chat, uploads, report generation)
to protect against resource exhaustion and abuse. Returns HTTP 429 with Retry-After.
"""

import math
import os
import time
from threading import Lock
from typing import Any

from fastapi import HTTPException


class TokenBucket:
    """Thread-safe token bucket for rate limiting."""

    def __init__(self, rate: float, capacity: float):
        """
        rate: tokens added per second
        capacity: maximum burst capacity
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = Lock()

    def consume(self, amount: float = 1.0) -> tuple[bool, float]:
        """Attempt to consume `amount` tokens.

        Returns:
            (allowed: bool, retry_after_seconds: float)
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens >= amount:
                self.tokens -= amount
                return True, 0.0

            needed = amount - self.tokens
            retry_after = needed / self.rate if self.rate > 0 else 60.0
            return False, retry_after


class RateLimiter:
    """Manages token buckets for users and actions."""

    # Default limits: (rate_per_sec, burst_capacity)
    DEFAULT_LIMITS: dict[str, tuple[float, float]] = {
        "chat": (10.0 / 60.0, 10.0),      # 10 req/min
        "upload": (5.0 / 60.0, 5.0),       # 5 req/min
        "report": (2.0 / 60.0, 2.0),       # 2 req/min
    }

    def __init__(
        self,
        limits: dict[str, tuple[float, float]] | None = None,
        default_limit: tuple[float, float] = (30.0 / 60.0, 30.0),
    ):
        self.limits = limits if limits is not None else self.DEFAULT_LIMITS
        self.default_limit = default_limit
        self._buckets: dict[tuple[str, str], TokenBucket] = {}
        self._lock = Lock()

    def _get_bucket(self, user_id: str, action: str) -> TokenBucket:
        key = (user_id, action)
        with self._lock:
            if key not in self._buckets:
                rate, capacity = self.limits.get(action, self.default_limit)
                self._buckets[key] = TokenBucket(rate=rate, capacity=capacity)
            return self._buckets[key]

    def reset(self) -> None:
        """Clear all active buckets (e.g. between tests)."""
        with self._lock:
            self._buckets.clear()

    def check(self, user_id: str, action: str) -> None:
        """Check if action is permitted for user. Raises HTTPException(429) if exceeded."""
        if os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in ("false", "0", "no", "off"):
            return
        bucket = self._get_bucket(user_id, action)
        allowed, retry_after = bucket.consume()
        if not allowed:
            retry_seconds = max(1, math.ceil(retry_after))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for action '{action}'. Please retry in {retry_seconds}s.",
                headers={"Retry-After": str(retry_seconds)},
            )


# Global singleton instance for application use
rate_limiter = RateLimiter()


def rate_limit(action: str):
    """FastAPI dependency for endpoint rate limiting."""
    def dependency(user: Any) -> None:
        user_id = getattr(user, "id", str(user))
        rate_limiter.check(user_id, action)
    return dependency
