import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.auto_healer import AutoHealer


@pytest.mark.asyncio
async def test_heals_stale_pages() -> None:
    mock_graph = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [{"uid": "stale-page-1", "path": "auth.md"}]
    mock_graph.execute_query = AsyncMock(return_value=mock_result)

    healer = AutoHealer(mock_graph)
    result = await healer.heal_stale_pages("test-repo", max_age_days=30)
    assert "pages_marked" in result


@pytest.mark.asyncio
async def test_removes_broken_refs() -> None:
    mock_graph = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = []
    mock_graph.execute_query = AsyncMock(return_value=mock_result)

    healer = AutoHealer(mock_graph)
    result = await healer.remove_broken_references("test-repo")
    assert "refs_removed" in result


@pytest.mark.asyncio
async def test_deprecate_orphans() -> None:
    mock_graph = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = []
    mock_graph.execute_query = AsyncMock(return_value=mock_result)

    healer = AutoHealer(mock_graph)
    result = await healer.deprecate_orphan_pages("test-repo")
    assert "pages_deprecated" in result
