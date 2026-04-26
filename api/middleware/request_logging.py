"""Request timing and ID middleware using structlog."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from api.request_context import reset_current_request_id, set_current_request_id

log = structlog.get_logger(__name__)

# Public health lives under ``/api/v1/health``; ``/api/health`` kept for compatibility.
_SKIP_REQUEST_LOG_PATHS = frozenset({"/api/health", "/api/v1/health"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
        rid_token = set_current_request_id(request_id)
        start = time.monotonic()

        try:
            response = await call_next(request)
            duration_ms = round((time.monotonic() - start) * 1000, 1)

            if request.url.path not in _SKIP_REQUEST_LOG_PATHS:
                log.info(
                    "request_completed",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=duration_ms,
                    request_id=request_id,
                )

            response.headers["X-Request-Id"] = request_id
            response.headers["X-Response-Time"] = f"{duration_ms}ms"
            return response
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                request_id=request_id,
            )
            raise
        finally:
            reset_current_request_id(rid_token)
