"""Query-param token is accepted only on SSE/WebSocket-oriented wiki routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import auth as auth_mod
from auth import TokenInfo


def _request(path: str, *, token: str | None = None) -> object:
    qp: dict[str, str] = {}
    if token is not None:
        qp["token"] = token
    return SimpleNamespace(query_params=qp, url=SimpleNamespace(path=path))


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_mod,
        "_token_registry",
        {"tok-viewer": TokenInfo(role=auth_mod.Role.VIEWER, business_id=None)},
    )


def test_require_role_accepts_query_token_on_ask_stream_path() -> None:
    dep = auth_mod.require_role(auth_mod.Role.VIEWER)
    info = dep(_request("/api/v1/wiki/ask/stream", token="tok-viewer"), None)
    assert info is not None
    assert int(info.role) == int(auth_mod.Role.VIEWER)


def test_require_role_rejects_query_token_on_non_sse_path() -> None:
    """Token in ?token= must not authenticate on ordinary API routes."""
    dep = auth_mod.require_role(auth_mod.Role.VIEWER)
    with pytest.raises(HTTPException) as ei:
        dep(_request("/api/v1/wiki/pages", token="tok-viewer"), None)
    assert ei.value.status_code == 401
