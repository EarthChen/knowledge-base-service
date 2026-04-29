"""tests/wiki/test_business_domain_injection.py"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBusinessDomainProperty:
    def test_update_business_domain_allowed(self):
        """business_domain should be in allowed properties for update_node_property."""
        from store.falkordb_store import FalkorDBStore

        assert "business_domain" in FalkorDBStore._ALLOWED_PROPERTIES


class TestFindDescendants:
    @pytest.mark.asyncio
    async def test_find_descendants_returns_children(self):
        """find_descendants should return UIDs of CONTAINS descendants."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = [["child_class_uid"], ["child_func_uid"]]
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                result = await store.find_descendants(
                    "module_uid", edge_type="CONTAINS", max_depth=3
                )

        assert isinstance(result, list)
        assert "child_class_uid" in result
        assert "child_func_uid" in result

    @pytest.mark.asyncio
    async def test_find_descendants_empty_for_leaf(self):
        """Leaf node should return empty descendants list."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = []
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                result = await store.find_descendants(
                    "leaf_uid", edge_type="CONTAINS", max_depth=3
                )

        assert result == []
