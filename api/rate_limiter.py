"""Simple per-IP rate limiter middleware using a token-bucket approach.

Configurable via environment variables:
  RATE_LIMIT_RPM  — max requests per minute per IP (default 120, 0 = disabled)
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config import get_settings


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, capacity: int) -> None:
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Token-bucket per-IP rate limiter.

    Static assets and the health endpoint are excluded so they never
    consume tokens.
    """

    _SKIP_PREFIXES = ("/assets/", "/favicon.ico", "/api/v1/hooks/")
    _SKIP_PATHS = {"/health"}

    def __init__(self, app: Any, rpm: int = 120, trust_proxy: bool = False) -> None:
        super().__init__(app)
        self._rpm = rpm
        self._rate = rpm / 60.0
        self._trust_proxy = trust_proxy
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(rpm))

    def _client_ip(self, request: Request) -> str:
        if self._trust_proxy:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if self._rpm <= 0:
            return await call_next(request)

        path = request.url.path
        if path in self._SKIP_PATHS or any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)

        ip = self._client_ip(request)
        bucket = self._buckets[ip]
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self._rpm, bucket.tokens + elapsed * self._rate)
        bucket.last_refill = now

        if bucket.tokens < 1.0:
            retry_after = int((1.0 - bucket.tokens) / self._rate) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        bucket.tokens -= 1.0
        return await call_next(request)


def install_rate_limiter(app: FastAPI) -> None:
    """Attach rate limiter middleware if RATE_LIMIT_RPM > 0."""
    settings = get_settings()
    rpm = getattr(settings, "rate_limit_rpm", 120)
    trust_proxy = getattr(settings, "rate_limit_trust_proxy", False)
    if rpm and rpm > 0:
        app.add_middleware(RateLimiterMiddleware, rpm=int(rpm), trust_proxy=bool(trust_proxy))
