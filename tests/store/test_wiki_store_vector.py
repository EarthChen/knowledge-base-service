import pytest
from unittest.mock import AsyncMock, MagicMock

from store.wiki_store import WikiStore


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[]))
    return WikiStore(store)


@pytest.mark.asyncio
async def test_vector_search_chunks(mock_store):
    await mock_store.vector_search_chunks(
        k=5, vec=[0.1] * 1024, repository="my-repo", limit=10
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "vector" in cypher.lower() or "vecf32" in cypher.lower()
    assert "repository" in cypher


@pytest.mark.asyncio
async def test_count_chunks_without_embedding(mock_store):
    await mock_store.count_chunks_without_embedding("my-repo")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "embedding" in cypher.lower()


@pytest.mark.asyncio
async def test_batch_get_chunks_for_embedding(mock_store):
    await mock_store.batch_get_chunks_for_embedding("my-repo", batch_size=64, offset=0)
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "text" in cypher
    assert "SKIP" in cypher
    assert "LIMIT" in cypher
