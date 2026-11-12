"""Circuit breaker pattern for protecting against cascading failures in external APIs.

States:
  - CLOSED: Normal operation. Successes reset failure count; failures increment it.
    If failure_count >= failure_threshold, the breaker transitions to OPEN.
  - OPEN: Requests immediately raise CircuitOpenError without calling the downstream function.
    After cooldown_seconds, the breaker moves to HALF_OPEN.
  - HALF_OPEN: A single probe request is allowed through. If it succeeds, the breaker resets
    to CLOSED. If it fails, the breaker trips back to OPEN and resets the cooldown timer.
"""

import time
from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any, TypeVar

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when an operation is attempted while the circuit breaker is open."""


class CircuitBreaker:
    """Thread-safe circuit breaker implementation."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        expected_exceptions: tuple[type[Exception], ...] = (Exception,),
        ignored_exceptions: tuple[type[Exception], ...] = (),
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.expected_exceptions = expected_exceptions
        self.ignored_exceptions = ignored_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute callable fn through the circuit breaker."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            elapsed = time.monotonic() - (self._opened_at or 0.0)
            remaining = max(0.0, self.cooldown_seconds - elapsed)
            raise CircuitOpenError(
                f"Circuit breaker is OPEN. Fast-failing calls. Cooldown remaining: {remaining:.1f}s"
            )

        # In CLOSED or HALF_OPEN: attempt execution
        try:
            result = fn(*args, **kwargs)
        except self.ignored_exceptions:
            # Re-raise ignored exceptions without counting toward failure threshold
            raise
        except self.expected_exceptions:
            self._handle_failure()
            raise
        else:
            self._handle_success()
            return result

    def _handle_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def _handle_failure(self) -> None:
        self._failure_count += 1
        if self.state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        """Support use as a decorator."""
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return self.call(fn, *args, **kwargs)
        return wrapper
