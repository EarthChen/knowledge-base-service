"""Unified JSON error responses and global exception handling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response

from log import get_logger

log = get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def _public_error_for_exception(exc: BaseException) -> tuple[int, str, str]:
    """Return (status_code, error_code, safe_message). Never leak exception strings."""
    if isinstance(exc, ValueError):
        return 400, "bad_request", "Bad request"

    if isinstance(exc, KeyError):
        return 404, "not_found", "Not found"

    if isinstance(exc, FileNotFoundError):
        return 404, "not_found", "Not found"

    exc_type = type(exc)
    if exc_type.__name__ == "NotFoundError":
        return 404, "not_found", "Not found"
    if exc_type.__name__ == "WikiRepoNotFoundError":
        return 404, "not_found", "Not found"

    return 500, "internal_error", "Internal server error"


def _request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id") or request.headers.get("X-Request-ID")


def register_exception_handlers(app: FastAPI) -> None:
    """Install HTTP middleware that maps unhandled exceptions to ``ErrorResponse``.

    Note: ``app.add_exception_handler(Exception, ...)`` is routed to Starlette's
    ``ServerErrorMiddleware``, which always re-raises after responding — breaking
    ``TestClient`` and client semantics. An ``http`` middleware catches failures
    inside the stack after routing handlers have run, without re-raising.
    """

    @app.middleware("http")
    async def unified_error_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            status_code, err_code, message = _public_error_for_exception(exc)
            rid = _request_id(request)

            log.error(
                "unhandled_exception",
                path=str(request.url.path),
                method=request.method,
                exc_type=type(exc).__name__,
                request_id=rid,
                exc_info=True,
            )

            payload = ErrorResponse(
                error=ErrorBody(code=err_code, message=message, request_id=rid),
            )
            return JSONResponse(
                status_code=status_code,
                content=jsonable_encoder(payload.model_dump()),
            )
