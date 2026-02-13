from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class TokenBucketLimiter:
    """Simple thread-safe token bucket tuned for RPM limits."""

    def __init__(self, rpm: int, burst: int | None = None):
        self.rpm = max(1, rpm)
        self.capacity = burst if burst is not None else max(1, rpm)
        self.tokens = float(self.capacity)
        self.refill_per_second = self.rpm / 60.0
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(
                    self.capacity, self.tokens + elapsed * self.refill_per_second
                )
                self.last_refill = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                missing = 1.0 - self.tokens
                wait_seconds = max(0.01, missing / self.refill_per_second)
            time.sleep(wait_seconds)


@dataclass(slots=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 0.35
    max_delay: float = 8.0
    jitter: float = 0.2

    def next_delay(self, attempt_index: int) -> float:
        raw = min(self.max_delay, self.base_delay * (2**attempt_index))
        return max(0.01, raw + random.uniform(0.0, self.jitter))


class CircuitBreaker:
    def __init__(self, threshold: int = 3, recovery_seconds: int = 60):
        self.threshold = max(1, threshold)
        self.recovery_seconds = max(1, recovery_seconds)
        self.failures = 0
        self.open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now >= self.open_until:
                return True
            return False

    def success(self) -> None:
        with self._lock:
            self.failures = 0
            self.open_until = 0.0

    def failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.monotonic() + self.recovery_seconds


def default_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    retry_markers = ("timeout", "timed out", "429", "rate", "503", "502", "500")
    return any(marker in text for marker in retry_markers)


def call_with_retries(
    fn: Callable[..., Any],
    *args: Any,
    policy: RetryPolicy | None = None,
    is_retryable: Callable[[Exception], bool] | None = None,
    **kwargs: Any,
) -> Any:
    policy = policy or RetryPolicy()
    predicate = is_retryable or default_retryable
    last_error: Exception | None = None

    for attempt in range(policy.max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= policy.max_retries or not predicate(exc):
                raise
            time.sleep(policy.next_delay(attempt))

    if last_error is None:
        raise RuntimeError("Retry handler exited without returning a value.")
    raise last_error

