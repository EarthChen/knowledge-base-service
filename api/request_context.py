"""Request-scoped context propagation via contextvars."""
from __future__ import annotations

from contextvars import ContextVar, Token

_business_id: ContextVar[str] = ContextVar("business_id", default="default")
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_current_business() -> str:
    return _business_id.get()


def set_current_business(business_id: str) -> Token[str]:
    return _business_id.set(business_id)


def get_current_request_id() -> str:
    return _request_id.get()


def set_current_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)


def reset_current_business(token: Token[str]) -> None:
    _business_id.reset(token)


def reset_current_request_id(token: Token[str]) -> None:
    _request_id.reset(token)
