"""Pagination and sorting for hybrid search (TDD)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler
from query.hybrid_query import HybridQueryService


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_semantic():
    svc = AsyncMock()
    result = MagicMock()
    result.matches = []
    svc.search_all = AsyncMock(return_value=result)
    return svc


@pytest.fixture
def mock_graph():
    svc = AsyncMock()
    svc.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_class_methods = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))
    svc.find_file_entities = AsyncMock(return_value=MagicMock(data=[]))
    return svc


@pytest.mark.asyncio
async def test_hybrid_search_returns_pagination_metadata(mock_store, mock_semantic, mock_graph):
    mock_store.keyword_search = AsyncMock(return_value=[
        {"name": "AbcFn", "file": "a.py", "line": 1, "score": 1.0, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
    ])
    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    result = await svc.search_with_context("AbcFn", k=5, offset=0, limit=10, sort_by="score", use_query_expansion=False)
    assert result["total"] == 1
    assert result["offset"] == 0
    assert result["limit"] == 10
    assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_hybrid_search_offset_slices(mock_store, mock_semantic, mock_graph):
    mock_store.keyword_search = AsyncMock(return_value=[])
    mock_semantic.search_all = AsyncMock(return_value=MagicMock(matches=[]))

    async def fake_fuse(*_a, **_k):
        return [
            {
                "name": f"n{i}",
                "file": f"f{i}.py",
                "line": i,
                "score": 1.0 - i * 0.1,
                "confidence": 1.0 - i * 0.1,
                "type": "Function",
                "match_source": "keyword",
            }
            for i in range(5)
        ]

    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    svc._fuse_expansion_results = fake_fuse  # type: ignore[method-assign]
    result = await svc.search_with_context(
        "stub", k=10, offset=2, limit=2, sort_by="name", use_query_expansion=False,
    )
    names = [m["name"] for m in result["results"]]
    assert names == ["n2", "n3"]
    assert result["total"] == 5


@pytest.mark.asyncio
async def test_hybrid_search_sort_by_score(mock_store, mock_semantic, mock_graph):
    mock_store.keyword_search = AsyncMock(return_value=[
        {"name": "low", "file": "a.py", "line": 1, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
        {"name": "high", "file": "b.py", "line": 2, "type": "Function", "uid": "u2", "signature": "", "docstring": ""},
    ])
    mock_semantic.search_all = AsyncMock(return_value=MagicMock(matches=[]))

    async def fake_fuse(*_a, **_k):
        return [
            {"name": "low", "file": "a.py", "line": 1, "type": "Function", "score": 0.2, "confidence": 0.2, "match_source": "keyword"},
            {"name": "high", "file": "b.py", "line": 2, "type": "Function", "score": 0.9, "confidence": 0.9, "match_source": "keyword"},
        ]

    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    svc._fuse_expansion_results = fake_fuse  # type: ignore[method-assign]

    result = await svc.search_with_context(
        "stub", k=10, offset=0, limit=10, sort_by="score", use_query_expansion=False,
    )
    assert [m["name"] for m in result["results"]] == ["high", "low"]


@pytest.mark.asyncio
async def test_hybrid_search_sort_by_name(mock_store, mock_semantic, mock_graph):
    mock_store.keyword_search = AsyncMock(return_value=[
        {"name": "zebra", "file": "z.py", "line": 1, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
        {"name": "alpha", "file": "a.py", "line": 2, "type": "Function", "uid": "u2", "signature": "", "docstring": ""},
    ])
    mock_semantic.search_all = AsyncMock(return_value=MagicMock(matches=[]))

    async def fake_fuse(*_a, **_k):
        return [
            {"name": "zebra", "file": "z.py", "line": 1, "type": "Function", "score": 0.9, "confidence": 0.9, "match_source": "keyword"},
            {"name": "alpha", "file": "a.py", "line": 2, "type": "Function", "score": 0.5, "confidence": 0.5, "match_source": "keyword"},
        ]

    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    svc._fuse_expansion_results = fake_fuse  # type: ignore[method-assign]

    result = await svc.search_with_context(
        "stub", k=10, offset=0, limit=10, sort_by="name", use_query_expansion=False,
    )
    assert [m["name"] for m in result["results"]] == ["alpha", "zebra"]


@pytest.mark.asyncio
async def test_hybrid_search_sort_by_path(mock_store, mock_semantic, mock_graph):
    mock_store.keyword_search = AsyncMock(return_value=[
        {"name": "a", "file": "z.py", "line": 1, "type": "Function", "uid": "u1", "signature": "", "docstring": ""},
        {"name": "b", "file": "a.py", "line": 2, "type": "Function", "uid": "u2", "signature": "", "docstring": ""},
    ])
    mock_semantic.search_all = AsyncMock(return_value=MagicMock(matches=[]))

    async def fake_fuse(*_a, **_k):
        return [
            {"name": "a", "file": "z.py", "line": 1, "type": "Function", "score": 0.9, "confidence": 0.9, "match_source": "keyword"},
            {"name": "b", "file": "a.py", "line": 2, "type": "Function", "score": 0.8, "confidence": 0.8, "match_source": "keyword"},
        ]

    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    svc._fuse_expansion_results = fake_fuse  # type: ignore[method-assign]

    result = await svc.search_with_context(
        "stub", k=10, offset=0, limit=10, sort_by="path", use_query_expansion=False,
    )
    assert [m["file"] for m in result["results"]] == ["a.py", "z.py"]


@pytest.mark.asyncio
async def test_mcp_rag_query_offset(mock_store, mock_semantic, mock_graph):
    hybrid = HybridQueryService(mock_store, mock_semantic, mock_graph)
    indexer = AsyncMock()
    handler = KnowledgeBaseMCPHandler(hybrid, AsyncMock(), indexer, store=mock_store)

    captured: dict = {}

    async def capture_search(*args, **kwargs):
        captured.update(kwargs)
        return {
            "results": [],
            "total": 0,
            "offset": kwargs.get("offset", 0),
            "limit": kwargs.get("limit", 20),
            "graph_context": [],
            "query_text": "",
            "confidence": 0.0,
            "no_results_reason": "",
        }

    hybrid.search_with_context = capture_search  # type: ignore[method-assign]

    await handler.handle_rag_query({"query": "hello", "k": 5, "offset": 15})
    assert captured.get("offset") == 15


@pytest.mark.asyncio
async def test_mcp_rag_query_response_has_total(mock_store, mock_semantic, mock_graph):
    hybrid = HybridQueryService(mock_store, mock_semantic, mock_graph)
    indexer = AsyncMock()
    handler = KnowledgeBaseMCPHandler(hybrid, AsyncMock(), indexer, store=mock_store)

    async def fake_search(*_a, **_k):
        return {
            "results": [{"name": "x", "file": "f.py", "line": 1, "type": "Function", "score": 1.0, "confidence": 1.0}],
            "total": 42,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "hello",
            "confidence": 0.5,
            "no_results_reason": "",
        }

    hybrid.search_with_context = fake_search  # type: ignore[method-assign]

    out = await handler.handle_rag_query({"query": "hello", "k": 5})
    assert "total" in out
    assert out["total"] == 42
