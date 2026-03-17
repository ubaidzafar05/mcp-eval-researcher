"""Production-grade middleware for Cloud Hive API.

Provides security headers, request ID tracing, rate limiting,
structured request logging, and graceful shutdown support.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger("cloud_hive.middleware")


# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects OWASP-recommended security headers into every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP: restrict to self, allow inline styles for UI frameworks
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' http://localhost:* http://127.0.0.1:*; "
            "frame-ancestors 'none'"
        )
        return response


# ---------------------------------------------------------------------------
# Request ID Tracing
# ---------------------------------------------------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request ID to every request for log correlation."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# Rate Limiting (token-bucket per IP)
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory token-bucket rate limiter per client IP.

    Only applies to paths that match `rate_limit_paths`.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: int = 10,
        rate_limit_paths: tuple[str, ...] = ("/research", "/research/stream"),
    ) -> None:
        super().__init__(app)
        self.rpm = requests_per_minute
        self.rate_limit_paths = rate_limit_paths
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_rate_limited(self, client_ip: str) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        bucket = self._buckets[client_ip]
        # Prune old entries
        self._buckets[client_ip] = [t for t in bucket if t > window_start]
        if len(self._buckets[client_ip]) >= self.rpm:
            return True
        self._buckets[client_ip].append(now)
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not any(request.url.path.startswith(p) for p in self.rate_limit_paths):
            return await call_next(request)

        client_ip = self._client_ip(request)
        if self._is_rate_limited(client_ip):
            retry_after = "60"
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": retry_after},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Structured Request Logging
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status, and latency for every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.monotonic()
        request_id = getattr(request.state, "request_id", "-")
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            status = response.status_code if response else 500
            # Skip noisy health checks from log output
            if request.url.path not in ("/health", "/health/deps"):
                logger.info(
                    "%s %s → %s (%.1fms) [rid=%s]",
                    request.method,
                    request.url.path,
                    status,
                    latency_ms,
                    request_id,
                )


# ---------------------------------------------------------------------------
# Graceful Shutdown
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()


def request_shutdown() -> None:
    """Signal that the application should begin graceful shutdown."""
    _shutdown_event.set()


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()
