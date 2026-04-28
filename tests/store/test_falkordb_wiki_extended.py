import pytest
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_persist_wiki_pages_includes_new_fields():
    """Verify the Cypher SET clause includes version, content_hash, importance_tier, repositories."""
    from store.falkordb_store import FalkorDBStore
    store = FalkorDBStore.__new__(FalkorDBStore)
    store._graph = MagicMock()

    mock_result = MagicMock()
    mock_result.result_set = [[1]]
    mock_result.data = [{"cnt": 1}]
    store._graph.query = MagicMock(return_value=mock_result)

    pages = [{
        "path": "/test/page",
        "title": "Test",
        "content": "content",
        "page_type": "class_detail",
        "generated_at": "2026-01-01T00:00:00Z",
        "version": 2,
        "content_hash": "abc123",
        "importance_tier": "core",
        "repositories": ["repo-a", "repo-b"],
    }]

    await store.persist_wiki_pages("test-repo", pages)

    call_args = store._graph.query.call_args
    cypher = call_args[0][0]
    assert "w.version" in cypher
    assert "w.content_hash" in cypher
    assert "w.importance_tier" in cypher
    assert "w.repositories" in cypher
    assert "w.confidence_score" in cypher
    assert "w.source_origin" in cypher
    assert "w.navigation_json" in cypher
