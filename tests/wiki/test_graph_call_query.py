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
        edges, errors = await fetch_module_call_edges(mock_store, ["repo1"], valid)

        assert len(errors) == 0
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

        edges, errors = await fetch_module_call_edges(mock_store, ["repo1"], set())
        assert edges == []
        assert len(errors) == 0
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
        edges, errors = await fetch_module_call_edges(mock_store, ["repo1", "repo2"], valid)

        assert len(errors) == 0
        assert len(edges) == 1
        assert edges[0] == (("repo1", "ModA"), ("repo2", "ModB"), 7)

    @pytest.mark.asyncio
    async def test_query_failure_returns_errors(self):
        """If both graph_store queries raise, return empty edges and error list."""
        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(side_effect=Exception("DB down"))

        edges, errors = await fetch_module_call_edges(mock_store, ["repo1"], {("repo1", "A")})
        assert edges == []
        assert len(errors) == 2
        assert all("DB down" in e for e in errors)

    def test_cypher_queries_contain_valid_pairs_param(self):
        """Both Cypher queries use $valid_pairs composite key filter."""
        assert "$valid_pairs" in _MODULE_CALLS_CYPHER
        assert "$valid_pairs" in _MODULE_DEPENDS_ON_CYPHER
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
        edges, errors = await fetch_module_call_edges(mock_store, ["repo1", "repo2"], valid)

        assert len(errors) == 0
        edge_dict = {(s, d): w for s, d, w in edges}
        assert edge_dict[(("repo1", "ModA"), ("repo2", "ModB"))] == 5  # 3+2
        assert edge_dict[(("repo1", "ModA"), ("repo2", "ModC"))] == 1


class TestParallelQueryExecution:
    """Task 5: Both Cypher queries should execute in parallel via asyncio.gather."""

    @pytest.mark.asyncio
    async def test_queries_run_in_parallel(self):
        """Both queries must be launched concurrently, not serially."""
        import asyncio

        call_order = []
        call_times = {}

        async def tracking_execute(query, params):
            name = "calls" if "CALLS" in query else "depends"
            call_times[name] = asyncio.get_event_loop().time()
            call_order.append(name)
            await asyncio.sleep(0.05)  # simulate latency
            result = MagicMock()
            result.data = []
            return result

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(side_effect=tracking_execute)

        await fetch_module_call_edges(mock_store, ["repo1"], set())

        assert len(call_order) == 2
        # Both should start nearly simultaneously (within 10ms)
        assert abs(call_times["calls"] - call_times["depends"]) < 0.01


class TestCypherWherePushdown:
    """Task 13: valid_modules filtering should be pushed to Cypher WHERE clause."""

    def test_cypher_contains_valid_pairs_param(self):
        """Both Cypher queries should reference $valid_pairs for WHERE pushdown."""
        assert "$valid_pairs" in _MODULE_CALLS_CYPHER
        assert "$valid_pairs" in _MODULE_DEPENDS_ON_CYPHER

    def test_cypher_has_where_valid_pairs_filter(self):
        """Cypher queries should filter repo|name composite keys against $valid_pairs."""
        assert "(m1.repository + '|' + m1.name) IN $valid_pairs" in _MODULE_CALLS_CYPHER
        assert "(m2.repository + '|' + m2.name) IN $valid_pairs" in _MODULE_CALLS_CYPHER
        assert "(m1.repository + '|' + m1.name) IN $valid_pairs" in _MODULE_DEPENDS_ON_CYPHER
        assert "(m2.repository + '|' + m2.name) IN $valid_pairs" in _MODULE_DEPENDS_ON_CYPHER

    @pytest.mark.asyncio
    async def test_valid_pairs_passed_to_execute_query(self):
        """execute_query should receive valid_pairs param derived from valid_modules."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_store.execute_query = AsyncMock(return_value=mock_result)

        valid = {("repo1", "ModA"), ("repo1", "ModB")}
        await fetch_module_call_edges(mock_store, ["repo1"], valid)

        for call in mock_store.execute_query.call_args_list:
            params = call[0][1]
            assert "valid_pairs" in params
            assert set(params["valid_pairs"]) == {"repo1|ModA", "repo1|ModB"}

    @pytest.mark.asyncio
    async def test_same_name_different_repos_use_composite_keys(self):
        """Same module name in different repos must not cross-match at DB level."""
        mock_store = MagicMock()
        calls_result = MagicMock()
        # Only repo1|ModA -> repo2|ModA edge should survive Python filter
        calls_result.data = [
            {
                "source_repo": "repo1",
                "source": "ModA",
                "target_repo": "repo2",
                "target": "ModA",
                "weight": 4,
            },
            {
                "source_repo": "repo1",
                "source": "ModA",
                "target_repo": "repo3",
                "target": "ModA",
                "weight": 99,
            },
        ]
        empty_result = MagicMock()
        empty_result.data = []
        mock_store.execute_query = AsyncMock(side_effect=[calls_result, empty_result])

        valid = {("repo1", "ModA"), ("repo2", "ModA")}
        edges, errors = await fetch_module_call_edges(mock_store, ["repo1", "repo2", "repo3"], valid)

        assert len(errors) == 0
        assert len(edges) == 1
        assert edges[0] == (("repo1", "ModA"), ("repo2", "ModA"), 4)

        for call in mock_store.execute_query.call_args_list:
            params = call[0][1]
            assert set(params["valid_pairs"]) == {"repo1|ModA", "repo2|ModA"}


class TestErrorReporting:
    """Task 14: fetch_module_call_edges should return (edges, errors) tuple."""

    @pytest.mark.asyncio
    async def test_return_type_is_tuple(self):
        """Return value must be a 2-tuple (list, list)."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_store.execute_query = AsyncMock(return_value=mock_result)

        result = await fetch_module_call_edges(mock_store, ["repo1"], set())
        assert isinstance(result, tuple)
        assert len(result) == 2
        edges, errors = result
        assert isinstance(edges, list)
        assert isinstance(errors, list)

    @pytest.mark.asyncio
    async def test_partial_failure_returns_partial_edges_and_errors(self):
        """If one query succeeds and one fails, return edges from success + error from failure."""
        mock_store = MagicMock()
        calls_result = MagicMock()
        calls_result.data = [
            {"source_repo": "repo1", "source": "ModA", "target_repo": "repo1", "target": "ModB", "weight": 5},
        ]

        async def mixed_execute(query, params):
            if "CALLS" in query:
                return calls_result
            raise ConnectionError("timeout")

        mock_store.execute_query = AsyncMock(side_effect=mixed_execute)

        valid = {("repo1", "ModA"), ("repo1", "ModB")}
        edges, errors = await fetch_module_call_edges(mock_store, ["repo1"], valid)

        assert len(edges) == 1
        assert len(errors) == 1
        assert "timeout" in errors[0]

    @pytest.mark.asyncio
    async def test_error_messages_include_query_identifier(self):
        """Error strings should identify which query failed."""
        mock_store = MagicMock()

        async def fail_calls(query, params):
            if "CALLS" in query:
                raise RuntimeError("calls broke")
            result = MagicMock()
            result.data = []
            return result

        mock_store.execute_query = AsyncMock(side_effect=fail_calls)

        edges, errors = await fetch_module_call_edges(mock_store, ["repo1"], set())
        assert len(errors) == 1
        assert "calls" in errors[0].lower() or "CALLS" in errors[0]


class TestContainsDepthOptimization:
    """Task 15: CONTAINS*1..3 should be changed to CONTAINS*1..2."""

    def test_contains_depth_is_at_most_2(self):
        """Both Cypher queries should use CONTAINS*1..2, not CONTAINS*1..3."""
        assert "CONTAINS*1..3" not in _MODULE_CALLS_CYPHER
        assert "CONTAINS*1..3" not in _MODULE_DEPENDS_ON_CYPHER
        assert "CONTAINS*1..2" in _MODULE_CALLS_CYPHER
        assert "CONTAINS*1..2" in _MODULE_DEPENDS_ON_CYPHER
