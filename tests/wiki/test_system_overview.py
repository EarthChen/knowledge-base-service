"""tests/wiki/test_system_overview.py — Sprint 2 tests for System Architecture Overview."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGetRepoStats:
    @pytest.mark.asyncio
    async def test_get_repo_stats_returns_counts(self):
        """get_repo_stats should return module/class/function counts."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        # Simulate results for Module, Class, Function count queries
        module_result = MagicMock()
        module_result.result_set = [[5]]
        class_result = MagicMock()
        class_result.result_set = [[20]]
        func_result = MagicMock()
        func_result.result_set = [[100]]

        mock_graph.query.side_effect = [module_result, class_result, func_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                stats = await store.get_repo_stats("test-repo")

        assert isinstance(stats, dict)
        assert stats["module_count"] == 5
        assert stats["class_count"] == 20
        assert stats["function_count"] == 100

    @pytest.mark.asyncio
    async def test_get_repo_stats_empty_repo(self):
        """Empty/nonexistent repo should return zero counts."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        empty_result = MagicMock()
        empty_result.result_set = [[0]]
        mock_graph.query.side_effect = [empty_result, empty_result, empty_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                stats = await store.get_repo_stats("nonexistent_repo")

        assert stats["module_count"] == 0
        assert stats["class_count"] == 0
        assert stats["function_count"] == 0

    @pytest.mark.asyncio
    async def test_get_repo_stats_handles_query_failure(self):
        """If a query fails, that count should be 0."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        module_result = MagicMock()
        module_result.result_set = [[3]]
        # Second query fails, third returns normally
        func_result = MagicMock()
        func_result.result_set = [[10]]
        mock_graph.query.side_effect = [module_result, Exception("DB error"), func_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                stats = await store.get_repo_stats("partial-repo")

        assert stats["module_count"] == 3
        assert stats["class_count"] == 0
        assert stats["function_count"] == 10
