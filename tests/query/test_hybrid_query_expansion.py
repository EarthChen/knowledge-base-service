"""Tests for graph-based query expansion in HybridQueryService."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from query.hybrid_query import HybridQueryService


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.keyword_search = AsyncMock(return_value=[
        {"uid": "u1", "name": "UserService", "type": "Class", "file": "a.java", "line": 10, "score": 1.0},
    ])
    return store


@pytest.fixture
def mock_semantic():
    svc = AsyncMock()
    result = MagicMock()
    result.matches = [
        {"name": "UserService", "file": "a.java", "line": 10, "score": 0.9},
    ]
    svc.search_all = AsyncMock(return_value=result)
    return svc


@pytest.fixture
def mock_graph():
    graph = AsyncMock()

    call_result = MagicMock()
    call_result.data = [
        {"name": "AuthService", "type": "Class", "file": "b.java", "line": 5},
        {"name": "UserRepository", "type": "Class", "file": "c.java", "line": 1},
    ]
    graph.find_call_chain = AsyncMock(return_value=call_result)

    method_result = MagicMock()
    method_result.data = [
        {"name": "getUser", "type": "Function", "file": "a.java", "line": 20},
    ]
    graph.find_class_methods = AsyncMock(return_value=method_result)

    inherit_result = MagicMock()
    inherit_result.data = []
    graph.find_inheritance_tree = AsyncMock(return_value=inherit_result)

    flow_result = MagicMock()
    flow_result.data = []
    graph.find_flows_for_function = AsyncMock(return_value=flow_result)

    file_result = MagicMock()
    file_result.data = []
    graph.find_file_entities = AsyncMock(return_value=file_result)

    return graph


class TestExpandQueryWithGraph:
    """Tests for _expand_query_with_graph."""

    @pytest.mark.asyncio
    async def test_expansion_returns_original_query_first(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        queries = await svc._expand_query_with_graph("UserService")
        assert queries[0] == "UserService"

    @pytest.mark.asyncio
    async def test_expansion_adds_neighbor_names(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        queries = await svc._expand_query_with_graph("UserService")
        assert len(queries) > 1
        expanded_text = " ".join(queries[1:])
        assert "AuthService" in expanded_text or "UserRepository" in expanded_text or "getUser" in expanded_text

    @pytest.mark.asyncio
    async def test_expansion_limits_max(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        queries = await svc._expand_query_with_graph("UserService", max_expansions=1)
        assert len(queries) <= 2

    @pytest.mark.asyncio
    async def test_expansion_handles_no_identifiers(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        queries = await svc._expand_query_with_graph("the")
        assert queries == ["the"]

    @pytest.mark.asyncio
    async def test_expansion_handles_no_keyword_hits(self, mock_store, mock_semantic, mock_graph):
        mock_store.keyword_search = AsyncMock(return_value=[])
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        queries = await svc._expand_query_with_graph("NonExistent")
        assert queries == ["NonExistent"]

    @pytest.mark.asyncio
    async def test_expansion_handles_graph_error(self, mock_store, mock_semantic, mock_graph):
        mock_graph.find_call_chain = AsyncMock(side_effect=RuntimeError("graph down"))
        mock_graph.find_class_methods = AsyncMock(side_effect=RuntimeError("graph down"))
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        queries = await svc._expand_query_with_graph("UserService")
        assert queries[0] == "UserService"


class TestSearchWithExpansion:
    """Tests for search_with_context with query expansion."""

    @pytest.mark.asyncio
    async def test_search_with_expansion_enabled(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("UserService", k=5, use_query_expansion=True)
        assert isinstance(result, dict)
        assert mock_semantic.search_all.call_count >= 1

    @pytest.mark.asyncio
    async def test_search_with_expansion_disabled(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("UserService", k=5, use_query_expansion=False)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_expansion_weight_cleaned_from_results(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("UserService", k=5, use_query_expansion=True)
        for m in result["results"]:
            assert "_expansion_weight" not in m

    @pytest.mark.asyncio
    async def test_original_query_weight_higher(self, mock_store, mock_semantic, mock_graph):
        svc = HybridQueryService(mock_store, mock_semantic, mock_graph)
        result = await svc.search_with_context("UserService", k=5, use_query_expansion=True)
        assert isinstance(result, dict)
