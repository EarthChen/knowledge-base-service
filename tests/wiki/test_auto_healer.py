import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.auto_healer import AutoHealer


@pytest.mark.asyncio
async def test_removes_broken_refs() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=3)

    healer = AutoHealer(mock_store)
    result = await healer.remove_broken_references("test-repo")
    assert result["refs_removed"] == 3
    mock_store.delete_broken_wiki_references.assert_awaited_once_with("test-repo")


@pytest.mark.asyncio
async def test_removes_broken_refs_returns_zero_on_error() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(side_effect=RuntimeError("db error"))

    healer = AutoHealer(mock_store)
    result = await healer.remove_broken_references("test-repo")
    assert result["refs_removed"] == 0


@pytest.mark.asyncio
async def test_run_all_only_cleans_refs() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=1)

    healer = AutoHealer(mock_store)
    result = await healer.run_all("test-repo")
    assert result["refs_removed"] == 1
    assert "pages_marked" not in result
    assert "pages_deprecated" not in result
