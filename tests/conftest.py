"""Shared test fixtures for the knowledge-base-service test suite."""

from __future__ import annotations

import gc
import warnings

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear cached settings between tests to avoid state leakage."""
    from core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _gc_after_test() -> None:
    """Force GC after each test to reclaim async resources deterministically.

    The ``ResourceWarning`` filter is scoped to the ``gc.collect()`` call only:
    warnings emitted by *test code itself* are **not** suppressed.  Without this,
    stale event-loop teardown warnings leak into unrelated tests, producing
    confusing noise.
    """
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        gc.collect()


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
    from core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    return settings
