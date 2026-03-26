"""Production-grade middleware for Cloud Hive API.

ASGI-native middleware is used so SSE streams are not buffered by BaseHTTPMiddleware.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from typing import Callable

from starlette.datastructures import MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("cloud_hive.middleware")


class SecurityHeadersMiddleware:
    """Inject OWASP-recommended headers without breaking streaming."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["X-XSS-Protection"] = "1; mode=block"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                headers["Content-Security-Policy"] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: https:; "
                    "connect-src 'self' http://localhost:* http://127.0.0.1:*; "
                    "frame-ancestors 'none'"
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestIdMiddleware:
    """Attach request ID to scope state and response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                mutable["X-Request-ID"] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class RateLimitMiddleware:
    """Simple in-memory token-bucket rate limiter per client IP."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: int = 10,
        rate_limit_paths: tuple[str, ...] = ("/research", "/research/stream"),
    ) -> None:
        self.app = app
        self.rpm = max(1, requests_per_minute)
        self.rate_limit_paths = rate_limit_paths
        self._buckets: dict[str, list[float]] = defaultdict(list)

    @staticmethod
    def _client_ip(scope: Scope) -> str:
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = scope.get("client")
        if client and isinstance(client, tuple):
            return str(client[0])
        return "unknown"

    def _is_rate_limited(self, client_ip: str) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        self._buckets[client_ip] = [t for t in self._buckets[client_ip] if t > window_start]
        if len(self._buckets[client_ip]) >= self.rpm:
            return True
        self._buckets[client_ip].append(now)
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if not any(path.startswith(p) for p in self.rate_limit_paths):
            await self.app(scope, receive, send)
            return

        client_ip = self._client_ip(scope)
        if self._is_rate_limited(client_ip):
            response = Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Log method, path, status, and latency for every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "")
        state = scope.get("state") or {}
        request_id = str(state.get("request_id", "-"))
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            if path not in ("/health", "/health/deps", "/health/live"):
                logger.info(
                    "%s %s -> %s (%.1fms) [rid=%s]",
                    method,
                    path,
                    status_code,
                    latency_ms,
                    request_id,
                )


_shutdown_event = asyncio.Event()


def request_shutdown() -> None:
    """Signal that the application should begin graceful shutdown."""
    _shutdown_event.set()


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()
