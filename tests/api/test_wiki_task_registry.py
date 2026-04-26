"""WikiTaskRegistry TTL and pruning."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import auth as auth_mod
from api.routes.wiki_routes import WIKI_TASK_TTL_SEC, WikiTaskRegistry
from auth import TokenInfo


def test_get_returns_none_for_expired_task(monkeypatch: pytest.MonkeyPatch) -> None:
    clock: list[float] = [0.0]

    def fake_mono() -> float:
        return clock[0]

    monkeypatch.setattr("api.routes.wiki_routes.time.monotonic", fake_mono)

    reg = WikiTaskRegistry()
    reg.put_task("t1", {"task_id": "t1", "status": "pending"})

    clock[0] = WIKI_TASK_TTL_SEC + 1.0
    assert reg.get_task("t1") is None
    assert "t1" not in reg.tasks


def test_prune_runs_on_put(monkeypatch: pytest.MonkeyPatch) -> None:
    clock: list[float] = [0.0]

    def fake_mono() -> float:
        return clock[0]

    monkeypatch.setattr("api.routes.wiki_routes.time.monotonic", fake_mono)

    reg = WikiTaskRegistry()
    reg.put_task("stale", {"task_id": "stale", "status": "pending"})

    clock[0] = WIKI_TASK_TTL_SEC + 1.0
    reg.put_task("fresh", {"task_id": "fresh", "status": "pending"})

    assert "stale" not in reg.tasks
    assert reg.get_task("fresh") is not None


def test_require_role_resolves_bearer_from_token_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """EventSource and similar clients can pass the API token as a query param."""
    monkeypatch.setattr(
        auth_mod,
        "_token_registry",
        {"tok-viewer": TokenInfo(role=auth_mod.Role.VIEWER, business_id=None)},
    )
    dep = auth_mod.require_role(auth_mod.Role.VIEWER)
    info = dep(SimpleNamespace(query_params={"token": "tok-viewer"}), None)
    assert info is not None
    assert int(info.role) == int(auth_mod.Role.VIEWER)
