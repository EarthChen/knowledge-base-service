import pytest
from unittest.mock import AsyncMock, MagicMock

from store.wiki_store import WikiStore


@pytest.fixture
def mock_store():
    s = AsyncMock()
    s.execute_query = AsyncMock(return_value=MagicMock(data=[{"cnt": 2}]))
    return WikiStore(s)


@pytest.mark.asyncio
async def test_prune_orphan_sections(mock_store):
    count = await mock_store.prune_orphan_sections("default", ["支付域", "__infrastructure__"])
    assert count == 2
    mock_store._store.execute_query.assert_awaited_once()
    query = mock_store._store.execute_query.call_args[0][0]
    assert "WikiSection" in query
    assert "DETACH DELETE" in query
    assert "$domains" in query
    assert "OPTIONAL MATCH" in query
    assert "IS NULL" in query


@pytest.mark.asyncio
async def test_prune_orphan_sections_no_result():
    s = AsyncMock()
    s.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    store = WikiStore(s)
    count = await store.prune_orphan_sections("x", ["active"])
    assert count == 0
