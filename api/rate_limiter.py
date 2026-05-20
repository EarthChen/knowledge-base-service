"""Per-IP rate limiter middleware — Redis-backed with in-process fallback.

Configurable via environment variables:
  RATE_LIMIT_RPM  — max requests per minute per IP (default 120, 0 = disabled)

When FalkorDB/Redis is available the limiter uses a shared sliding-window
counter (Lua script) so limits are enforced across all workers.  If Redis is
unreachable at startup or at runtime the middleware transparently falls back to
a process-local token-bucket.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.config import get_settings
from core.log import get_logger

log = get_logger(__name__)

_LUA_RATE_LIMIT = """
local key   = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local current = redis.call("INCR", key)
if current == 1 then
    redis.call("EXPIRE", key, window)
end
if current > limit then
    return 0
end
return 1
"""


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, capacity: int) -> None:
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Token-bucket per-IP rate limiter with optional Redis backend.

    Static assets and the health endpoint are excluded so they never
    consume tokens.
    """

    _SKIP_PREFIXES = ("/assets/", "/favicon.ico")
    _SKIP_PATHS = {"/health"}
    _EVICT_INTERVAL = 60.0
    _EVICT_AGE = 600.0

    def __init__(
        self,
        app: Any,
        rpm: int = 120,
        trust_proxy: bool = False,
        redis_host: str | None = None,
        redis_port: int = 6379,
        redis_password: str = "",
    ) -> None:
        super().__init__(app)
        self._rpm = rpm
        self._rate = rpm / 60.0
        self._trust_proxy = trust_proxy

        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(rpm))
        self._last_evict = time.monotonic()

        self._redis: Any = None
        self._lua_sha: str | None = None
        self._redis_noscript_exc: type[BaseException] | None = None
        if redis_host:
            self._init_redis(redis_host, redis_port, redis_password)

    def _init_redis(self, host: str, port: int, password: str) -> None:
        try:
            import redis as _redis_pkg

            pool = _redis_pkg.ConnectionPool(
                host=host,
                port=port,
                password=password or None,
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=1,
            )
            conn = _redis_pkg.Redis(connection_pool=pool)
            conn.ping()
            self._lua_sha = conn.script_load(_LUA_RATE_LIMIT)
            self._redis = conn
            self._redis_noscript_exc = _redis_pkg.exceptions.NoScriptError
            log.info(
                "rate_limiter_redis_connected",
                host=host,
                port=port,
            )
        except Exception:
            log.warning("rate_limiter_redis_unavailable", exc_info=True)
            self._redis = None

    def _evict_stale(self, now: float) -> None:
        if now - self._last_evict < self._EVICT_INTERVAL:
            return
        self._last_evict = now
        stale = [ip for ip, b in self._buckets.items() if now - b.last_refill > self._EVICT_AGE]
        for ip in stale:
            del self._buckets[ip]

    def _client_ip(self, request: Request) -> str:
        if self._trust_proxy:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _check_redis(self, ip: str) -> bool | None:
        """Check rate limit via Redis.  Returns True=allowed, False=denied, None=fallback.

        When Redis is unavailable, callers fall back to per-process in-memory buckets
        (fail-open for availability). In multi-worker deployments each worker tracks
        its own bucket, so effective limits are multiplied by worker count.
        """
        if self._redis is None or self._lua_sha is None:
            return None
        minute_bucket = int(time.time()) // 60
        key = f"rl:{ip}:{minute_bucket}"
        try:
            result = self._redis.evalsha(self._lua_sha, 1, key, self._rpm, 60)
        except Exception as exc:
            if self._redis_noscript_exc is None or not isinstance(
                exc, self._redis_noscript_exc
            ):
                log.warning("rate_limiter_redis_error", exc_info=True)
                return None
            try:
                result = self._redis.eval(_LUA_RATE_LIMIT, 1, key, self._rpm, 60)
            except Exception:
                log.warning("rate_limiter_redis_error", exc_info=True)
                return None
            try:
                self._lua_sha = self._redis.script_load(_LUA_RATE_LIMIT)
            except Exception:
                pass
        return int(result) == 1

    def _check_local(self, ip: str) -> tuple[bool, int]:
        """Check rate limit via in-process bucket.  Returns (allowed, retry_after)."""
        now = time.monotonic()
        self._evict_stale(now)
        bucket = self._buckets[ip]
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self._rpm, bucket.tokens + elapsed * self._rate)
        bucket.last_refill = now

        if bucket.tokens < 1.0:
            retry_after = int((1.0 - bucket.tokens) / self._rate) + 1
            return False, retry_after

        bucket.tokens -= 1.0
        return True, 0

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if self._rpm <= 0:
            return await call_next(request)

        path = request.url.path
        if path in self._SKIP_PATHS or any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)

        ip = self._client_ip(request)

        redis_result = self._check_redis(ip)
        if redis_result is not None:
            if not redis_result:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={"Retry-After": "60"},
                )
            return await call_next(request)

        log.warning("rate_limiter_using_in_memory_fallback", client_ip=ip)
        allowed, retry_after = self._check_local(ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


def install_rate_limiter(app: FastAPI) -> None:
    """Attach rate limiter middleware if RATE_LIMIT_RPM > 0."""
    settings = get_settings()
    rpm = getattr(settings, "rate_limit_rpm", 120)
    trust_proxy = getattr(settings, "rate_limit_trust_proxy", False)
    if not rpm or rpm <= 0:
        return

    redis_host: str | None = None
    redis_port = 6379
    redis_password = ""
    if hasattr(settings, "falkordb"):
        redis_host = settings.falkordb.host
        redis_port = settings.falkordb.port
        redis_password = getattr(settings, "falkordb_password", "")

    app.add_middleware(
        RateLimiterMiddleware,
        rpm=int(rpm),
        trust_proxy=bool(trust_proxy),
        redis_host=redis_host,
        redis_port=redis_port,
        redis_password=redis_password,
    )
