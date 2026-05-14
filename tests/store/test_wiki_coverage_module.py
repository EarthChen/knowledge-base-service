"""Test module-based coverage query."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_get_entity_coverage_stats_returns_module_counts():
    """Should return total_modules and covered_modules instead of tier counts."""
    from store.wiki_coverage_store import WikiCoverageStoreMixin

    class FakeStore(WikiCoverageStoreMixin):
        def __init__(self):
            self._store = MagicMock()
            self._store.execute_query = AsyncMock(return_value=MagicMock(
                data=[{"total_modules": 100, "covered_modules": 75}]
            ))

    store = FakeStore()
    result = await store.get_entity_coverage_stats("test-biz")

    assert "total_modules" in result
    assert "covered_modules" in result
    assert result["total_modules"] == 100
    assert result["covered_modules"] == 75
    assert "core_total" not in result
    assert "standard_total" not in result
    assert "skeleton_total" not in result


@pytest.mark.asyncio
async def test_get_entity_coverage_stats_empty():
    """Should handle zero results gracefully."""
    from store.wiki_coverage_store import WikiCoverageStoreMixin

    class FakeStore(WikiCoverageStoreMixin):
        def __init__(self):
            self._store = MagicMock()
            self._store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    store = FakeStore()
    result = await store.get_entity_coverage_stats("empty-biz")

    assert result["total_modules"] == 0
    assert result["covered_modules"] == 0
