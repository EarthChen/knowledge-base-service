"""Tests for REQUIRE_AUTH safety net when no tokens are configured."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import auth


def _req(params: dict[str, str] | None = None) -> object:
    return SimpleNamespace(query_params=dict(params) if params else {})


@pytest.fixture(autouse=True)
def _clear_auth_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_token_registry", None)
    yield


def test_settings_default_require_auth_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUIRE_AUTH", raising=False)
    from config import Settings

    assert Settings().require_auth is False


@pytest.mark.parametrize(
    ("require_auth_env", "expected"),
    [
        ("true", True),
        ("1", True),
        ("false", False),
        ("0", False),
    ],
)
def test_settings_require_auth_from_env(
    monkeypatch: pytest.MonkeyPatch,
    require_auth_env: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", require_auth_env)
    from config import Settings

    assert Settings().require_auth is expected


def test_require_role_blocks_when_require_auth_true_and_no_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.setattr(auth, "_build_token_registry", lambda _s: {})
    auth._token_registry = None

    import config as config_module

    config_module.get_settings.cache_clear()

    dep = auth.require_role(auth.Role.VIEWER)
    with pytest.raises(HTTPException) as ei:
        dep(_req(), None)
    assert ei.value.status_code == 403

    config_module.get_settings.cache_clear()


def test_startup_auth_gate_raises_when_require_auth_without_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.setattr(auth, "_build_token_registry", lambda _s: {})
    auth._token_registry = None

    import config as config_module

    config_module.get_settings.cache_clear()

    from main import _startup_auth_gate

    settings = config_module.get_settings()
    with pytest.raises(RuntimeError, match="API tokens"):
        _startup_auth_gate(settings)

    config_module.get_settings.cache_clear()


def test_require_role_allows_none_when_require_auth_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUIRE_AUTH", raising=False)
    monkeypatch.setattr(auth, "_build_token_registry", lambda _s: {})
    auth._token_registry = None

    import config as config_module

    config_module.get_settings.cache_clear()

    dep = auth.require_role(auth.Role.VIEWER)
    assert dep(_req(), None) is None

    config_module.get_settings.cache_clear()
