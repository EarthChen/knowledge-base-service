"""Confidence signal (no-results) and graph_context line references for hybrid search."""

from unittest.mock import AsyncMock, MagicMock

import pytest

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
async def test_empty_search_has_zero_confidence_and_reason(mock_store, mock_semantic, mock_graph):
    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    result = await svc.search_with_context("nothing should match this xyz123")
    assert result["results"] == []
    assert result["confidence"] == 0.0
    assert result["no_results_reason"] == "No matching entities found for query"


@pytest.mark.asyncio
async def test_matches_have_confidence_and_clear_reason(mock_store, mock_semantic, mock_graph):
    sem_result = MagicMock()
    sem_result.matches = [
        {"name": "login", "file": "auth.py", "line": 5, "score": 0.85, "type": "Function"},
        {"name": "logout", "file": "auth.py", "line": 20, "score": 0.42, "type": "Function"},
    ]
    mock_semantic.search_all = AsyncMock(return_value=sem_result)
    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    result = await svc.search_with_context("auth")
    assert len(result["results"]) >= 1
    assert result["confidence"] > 0.0
    assert result["confidence"] > 0.5
    assert result["no_results_reason"] == ""


@pytest.mark.asyncio
async def test_graph_context_includes_location_keys(mock_store, mock_semantic, mock_graph):
    mock_store.keyword_search = AsyncMock(return_value=[
        {
            "name": "Alpha",
            "file": "a.py",
            "line": 1,
            "score": 1.0,
            "type": "Function",
            "uid": "u1",
            "signature": "",
            "docstring": "",
        },
    ])
    mock_graph.find_call_chain = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "name": "Beta",
                    "file": "b.py",
                    "line": 10,
                    "start_line": 10,
                    "end_line": 15,
                    "fqn": "x.Beta",
                },
            ],
        ),
    )
    svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
    result = await svc.search_with_context("Alpha", k=5, expand_depth=1)
    assert result["graph_context"]
    for item in result["graph_context"]:
        if item.get("type") == "business_flow":
            continue
        assert "start_line" in item
        assert "end_line" in item
        assert "file" in item
        assert item["file"] == "b.py"
        assert item["start_line"] == 10
        assert item["end_line"] == 15
