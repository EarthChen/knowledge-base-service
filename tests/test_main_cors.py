"""Tests for optional CORSMiddleware in create_app."""

from __future__ import annotations

import pytest
from starlette.middleware.cors import CORSMiddleware


def test_create_app_registers_cors_when_cors_origins_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://other.example")
    from config import get_settings

    get_settings.cache_clear()
    from main import create_app

    app = create_app()
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_create_app_skips_cors_when_origins_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    from main import create_app

    app = create_app()
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)
