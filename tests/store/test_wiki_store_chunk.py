from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[]))
    return WikiStore(store)


@pytest.mark.asyncio
async def test_find_chunks_by_parent_uid(mock_store):
    await mock_store.find_chunks_by_parent_uid("Function:src/main.py:hello:1")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "PART_OF" in cypher
    assert "parent_uid" in cypher


@pytest.mark.asyncio
async def test_score_all_entities(mock_store):
    await mock_store.score_all_entities("my-repo")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "repository" in cypher
    assert "in_deg" in cypher or "in_degree" in cypher
    assert "out_deg" in cypher or "out_degree" in cypher
    assert "children" in cypher
