"""Tests for get_repo_wiki_freshness — repo-level incremental skip."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_store():
    s = MagicMock()
    s.execute_query = AsyncMock()
    s._store = s
    return s


@pytest.mark.asyncio
async def test_freshness_returns_dict(mock_store):
    from store.wiki_page_store import WikiPageStoreMixin

    mixin = WikiPageStoreMixin()
    mixin._store = mock_store

    mock_store.execute_query.return_value = MagicMock(
        data=[
            {"repository": "repo1", "last_indexed": "2026-04-27T10:00:00", "last_generated": "2026-04-26T10:00:00"},
            {"repository": "repo2", "last_indexed": "2026-04-25T10:00:00", "last_generated": "2026-04-26T10:00:00"},
        ]
    )
    result = await mixin.get_repo_wiki_freshness("default")
    assert "repo1" in result
    assert result["repo1"]["last_indexed"] == "2026-04-27T10:00:00"
    assert result["repo1"]["last_generated"] == "2026-04-26T10:00:00"
    assert "repo2" in result


@pytest.mark.asyncio
async def test_freshness_null_generated(mock_store):
    from store.wiki_page_store import WikiPageStoreMixin

    mixin = WikiPageStoreMixin()
    mixin._store = mock_store

    mock_store.execute_query.return_value = MagicMock(
        data=[
            {"repository": "new-repo", "last_indexed": "2026-04-27T10:00:00", "last_generated": None},
        ]
    )
    result = await mixin.get_repo_wiki_freshness("default")
    assert result["new-repo"]["last_generated"] is None


@pytest.mark.asyncio
async def test_freshness_empty_result(mock_store):
    from store.wiki_page_store import WikiPageStoreMixin

    mixin = WikiPageStoreMixin()
    mixin._store = mock_store

    mock_store.execute_query.return_value = MagicMock(data=[])
    result = await mixin.get_repo_wiki_freshness("default")
    assert result == {}
