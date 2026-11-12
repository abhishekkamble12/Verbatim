"""Tests for CircuitBreaker in packages.llm_gateway.circuit_breaker."""

import time

import pytest

from packages.llm_gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


def test_circuit_breaker_starts_closed():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0

    result = cb.call(lambda x: x * 2, 5)
    assert result == 10
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_trips_to_open_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)

    def failing_call():
        raise RuntimeError("Service unavailable")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        assert cb.state == CircuitState.CLOSED

    # 3rd consecutive failure trips the breaker
    with pytest.raises(RuntimeError):
        cb.call(failing_call)

    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 3

    # Subsequent call immediately raises CircuitOpenError without calling the function
    mock_called = False

    def probe():
        nonlocal mock_called
        mock_called = True
        return "ok"

    with pytest.raises(CircuitOpenError) as exc_info:
        cb.call(probe)

    assert not mock_called
    assert "Circuit breaker is OPEN" in str(exc_info.value)


def test_circuit_breaker_half_open_recovery():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

    def failing_call():
        raise RuntimeError("Transient error")

    # Trip breaker
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(failing_call)

    assert cb.state == CircuitState.OPEN

    # Wait for cooldown
    time.sleep(0.15)

    # Next call probe succeeds -> circuit resets to CLOSED
    result = cb.call(lambda: "recovered")
    assert result == "recovered"
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_circuit_breaker_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

    def failing_call():
        raise RuntimeError("Persistent error")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(failing_call)

    assert cb.state == CircuitState.OPEN
    time.sleep(0.15)

    # Probe fails -> immediately trips back to OPEN
    with pytest.raises(RuntimeError):
        cb.call(failing_call)

    assert cb.state == CircuitState.OPEN

    # Next call immediately fails fast
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not be called")


def test_circuit_breaker_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)

    def failing_call():
        raise RuntimeError("Intermittent error")

    # 2 failures
    with pytest.raises(RuntimeError):
        cb.call(failing_call)
    with pytest.raises(RuntimeError):
        cb.call(failing_call)
    assert cb.failure_count == 2

    # 1 success resets counter
    cb.call(lambda: "ok")
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_decorator():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=1.0)

    @cb
    def decorated_func(val: int) -> int:
        if val < 0:
            raise ValueError("Negative number")
        return val * 10

    assert decorated_func(2) == 20

    with pytest.raises(ValueError):
        decorated_func(-1)
    with pytest.raises(ValueError):
        decorated_func(-2)

    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        decorated_func(5)


def test_circuit_breaker_ignores_specified_exceptions():
    class CustomConfigError(Exception):
        pass

    cb = CircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=1.0,
        ignored_exceptions=(CustomConfigError,),
    )

    def config_failing_call():
        raise CustomConfigError("Missing key")

    # Ignored exceptions shouldn't increase failure count
    for _ in range(5):
        with pytest.raises(CustomConfigError):
            cb.call(config_failing_call)

    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0

