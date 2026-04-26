"""Shared test fixtures for the knowledge-base-service test suite."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear cached settings between tests to avoid state leakage."""
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_falkordb_store() -> AsyncMock:
    """Create a mock FalkorDBStore for testing without a real database."""
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[], data=[]))
    store.connect = AsyncMock()
    store.close = AsyncMock()
    return store


@pytest.fixture
def temp_settings(tmp_path: object, monkeypatch: pytest.MonkeyPatch):
    """Create temporary settings with a temp directory for data."""
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8199")
    from config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    return settings
