"""Middleware layer for the API gateway.

Three middlewares are used, in this outer->inner order:
  1. RequestLoggingMiddleware   - request/response logging with trace id
  2. RateLimitMiddleware        - in-process token bucket per client
  3. JWTAuthMiddleware          - bearer auth for all non-exempt paths
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_429_TOO_MANY_REQUESTS

from .jwt import verify_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging middleware
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a trace id and log request + response timing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %d (%.1f ms) trace=%s",
            request.method, request.url.path, response.status_code, elapsed_ms, trace_id,
        )
        return response


# ---------------------------------------------------------------------------
# Rate limiting (token bucket, in-process by default)
# ---------------------------------------------------------------------------
class _Buckets:
    """Per-client in-memory token buckets."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._buckets: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._buckets.setdefault(key, deque())
        # Lazy refill
        while bucket and now - bucket[0] > 1.0 / self.refill_per_sec:
            bucket.popleft()
            if len(bucket) >= self.capacity:
                bucket.append(now)
        if len(bucket) < self.capacity:
            bucket.append(now)
            return True
        return False


_buckets = _Buckets(capacity=20, refill_per_sec=5)  # 20 rps burst per client


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        key = request.client.host if request.client else "anon"
        if not _buckets.allow(key):
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "rate_limited", "message": "Too many requests, please retry."},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# JWT auth
# ---------------------------------------------------------------------------
class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, exempt_paths: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self.exempt_paths = exempt_paths

    async def dispatch(self, request: Request, call_next) -> Response:
        # Exempt paths bypass auth entirely. Static dashboard assets and the
        # SPA catch-all are public so the single-server launcher can serve the
        # UI without a token.
        path = request.url.path
        if any(path.startswith(p) for p in self.exempt_paths):
            return await call_next(request)
        # Static files / SPA root are public
        if path == "/" or not path.startswith("/api/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"error": "unauthorized", "message": "Missing bearer token."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth[7:].strip()
        payload = verify_token(token)
        if payload is None:
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"error": "unauthorized", "message": "Invalid or expired token."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user = payload.get("sub", "anonymous")
        request.state.roles = payload.get("roles", [])
        return await call_next(request)
