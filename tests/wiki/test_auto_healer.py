import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.auto_healer import AutoHealer


@pytest.mark.asyncio
async def test_removes_broken_refs() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=3)
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(return_value=0)

    healer = AutoHealer(mock_store)
    result = await healer.remove_broken_references("test-repo")
    assert result["refs_removed"] == 3
    mock_store.delete_broken_wiki_references.assert_awaited_once_with("test-repo")


@pytest.mark.asyncio
async def test_removes_broken_refs_returns_zero_on_error() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(side_effect=RuntimeError("db error"))
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(return_value=0)

    healer = AutoHealer(mock_store)
    result = await healer.remove_broken_references("test-repo")
    assert result["refs_removed"] == 0


@pytest.mark.asyncio
async def test_deprecate_orphan_pages() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=0)
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(return_value=5)

    healer = AutoHealer(mock_store)
    result = await healer.deprecate_orphan_pages("test-repo")
    assert result["pages_deprecated"] == 5
    mock_store.deprecate_orphan_wiki_pages.assert_awaited_once_with("test-repo")


@pytest.mark.asyncio
async def test_deprecate_orphan_pages_returns_zero_on_error() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=0)
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(side_effect=RuntimeError("fail"))

    healer = AutoHealer(mock_store)
    result = await healer.deprecate_orphan_pages("test-repo")
    assert result["pages_deprecated"] == 0


@pytest.mark.asyncio
async def test_run_all_cleans_refs_and_deprecates_orphans() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=2)
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(return_value=3)

    healer = AutoHealer(mock_store)
    result = await healer.run_all("test-repo")
    assert result["refs_removed"] == 2
    assert result["pages_deprecated"] == 3
    assert "pages_marked" not in result


@pytest.mark.asyncio
async def test_heal_delegates_to_run_all() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=1)
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(return_value=2)
    healer = AutoHealer(mock_store)
    result = await healer.heal("my-repo")
    assert result["refs_removed"] == 1
    assert result["pages_deprecated"] == 2
