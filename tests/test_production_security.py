"""Tests for production fail-closed startup checks."""

from __future__ import annotations

import pytest

from core.config import get_settings


@pytest.fixture
def production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_ENV", "production")


def test_enforce_production_skips_when_not_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_ENV", "development")
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    get_settings.cache_clear()
    from main import _enforce_production_security

    _enforce_production_security(get_settings())


def test_enforce_production_raises_without_require_auth(
    production_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    get_settings.cache_clear()
    from main import _enforce_production_security

    with pytest.raises(RuntimeError, match="require_auth=true"):
        _enforce_production_security(get_settings())


def test_enforce_production_raises_without_tokens(
    production_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    # Override any project ``.env`` token values (pydantic-settings falls back to env file).
    monkeypatch.setenv("API_TOKEN", "")
    monkeypatch.setenv("API_TOKENS", "")
    missing = tmp_path / "no-tokens-here.yaml"
    monkeypatch.setenv("TOKENS_FILE", str(missing))
    get_settings.cache_clear()
    from main import _enforce_production_security

    with pytest.raises(RuntimeError, match="at least one API token"):
        _enforce_production_security(get_settings())


def test_enforce_production_ok_with_api_token(
    production_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.setenv("API_TOKEN", "secret-prod-token")
    missing = tmp_path / "no-tokens-here.yaml"
    monkeypatch.setenv("TOKENS_FILE", str(missing))
    get_settings.cache_clear()
    from main import _enforce_production_security

    _enforce_production_security(get_settings())
