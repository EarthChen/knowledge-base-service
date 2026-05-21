from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.graph_call_query import _MODULE_CALLS_CYPHER, _MODULE_DEPENDS_ON_CYPHER, fetch_module_call_edges


class TestFetchModuleCallEdges:
    @pytest.mark.asyncio
    async def test_returns_filtered_edges(self):
        """Only edges where both endpoints are in valid_modules are returned."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo1", "target": "ModB", "weight": 5},
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo1", "target": "ModC", "weight": 3},
            {"source_repo": "repo1", "source": "ModX", "target_repo": "repo1", "target": "ModY", "weight": 10},
        ]
        empty_result = MagicMock()
        empty_result.data = []
        mock_store.execute_query = AsyncMock(side_effect=[mock_result, empty_result])

        valid = {("repo1", "ModA"), ("repo1", "ModB"), ("repo1", "ModC")}
        edges = await fetch_module_call_edges(mock_store, ["repo1"], valid)

        assert len(edges) == 2
        assert (("repo1", "ModA"), ("repo1", "ModB"), 5) in edges
        assert (("repo1", "ModA"), ("repo1", "ModC"), 3) in edges

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self):
        """Empty query result returns empty edge list."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_store.execute_query = AsyncMock(return_value=mock_result)

        edges = await fetch_module_call_edges(mock_store, ["repo1"], set())
        assert edges == []
        assert mock_store.execute_query.call_count == 2  # Both queries run

    @pytest.mark.asyncio
    async def test_cross_repo_edges_included(self):
        """Edges between different repos are included when both in valid_modules."""
        mock_store = MagicMock()
        calls_result = MagicMock()
        calls_result.data = [
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo2", "target": "ModB", "weight": 7},
        ]
        empty_result = MagicMock()
        empty_result.data = []
        mock_store.execute_query = AsyncMock(side_effect=[calls_result, empty_result])

        valid = {("repo1", "ModA"), ("repo2", "ModB")}
        edges = await fetch_module_call_edges(mock_store, ["repo1", "repo2"], valid)

        assert len(edges) == 1
        assert edges[0] == (("repo1", "ModA"), ("repo2", "ModB"), 7)

    @pytest.mark.asyncio
    async def test_query_failure_returns_empty(self):
        """If both graph_store queries raise, return empty list (logged warning)."""
        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(side_effect=Exception("DB down"))

        edges = await fetch_module_call_edges(mock_store, ["repo1"], {("repo1", "A")})
        assert edges == []

    def test_cypher_queries_contain_repos_param(self):
        """Both Cypher queries use $repos parameter for cross-repo support."""
        assert "$repos" in _MODULE_CALLS_CYPHER
        assert "$repos" in _MODULE_DEPENDS_ON_CYPHER
        assert "CALLS" in _MODULE_CALLS_CYPHER
        assert "DEPENDS_ON" in _MODULE_DEPENDS_ON_CYPHER

    @pytest.mark.asyncio
    async def test_combines_calls_and_depends_on_edges(self):
        """Edges from both CALLS and DEPENDS_ON queries are combined with summed weights."""
        mock_store = MagicMock()
        calls_result = MagicMock()
        calls_result.data = [
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo2", "target": "ModB", "weight": 3},
        ]
        depends_result = MagicMock()
        depends_result.data = [
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo2", "target": "ModB", "weight": 2},
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo2", "target": "ModC", "weight": 1},
        ]
        mock_store.execute_query = AsyncMock(side_effect=[calls_result, depends_result])

        valid = {("repo1", "ModA"), ("repo2", "ModB"), ("repo2", "ModC")}
        edges = await fetch_module_call_edges(mock_store, ["repo1", "repo2"], valid)

        edge_dict = {(s, d): w for s, d, w in edges}
        assert edge_dict[(("repo1", "ModA"), ("repo2", "ModB"))] == 5  # 3+2
        assert edge_dict[(("repo1", "ModA"), ("repo2", "ModC"))] == 1
