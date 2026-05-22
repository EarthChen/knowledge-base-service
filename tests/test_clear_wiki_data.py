"""Tests for wiki-only data clearing."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from store.graph_queries import GraphQueryRepository


class TestDeleteWikiData:
    @pytest.mark.asyncio
    async def test_delete_wiki_data_calls_correct_labels(self):
        """Should delete only wiki labels, not code index."""
        mock_store = MagicMock()
        # One query per wiki label; summed delete count should be 42.
        side_effects = []
        for i in range(8):
            mr = MagicMock()
            mr.data = [{"deleted": 42 if i == 0 else 0}]
            side_effects.append(mr)
        mock_store.execute_query = AsyncMock(side_effect=side_effects)

        repo = GraphQueryRepository(mock_store)
        deleted = await repo.delete_wiki_data("test-business")

        assert deleted == 42
        # Verify each call targets a wiki label only (eight label-specific queries)
        assert mock_store.execute_query.call_count == 8
        combined = " ".join(c[0][0] for c in mock_store.execute_query.call_args_list)
        assert "WikiPage" in combined
        assert "WikiSpace" in combined
        assert "WikiSection" in combined
        assert "WikiQA" in combined
        # Should NOT touch code index
        assert "Function" not in combined
        assert "Module" not in combined
        assert "Class" not in combined

    @pytest.mark.asyncio
    async def test_delete_wiki_data_filters_by_business_id(self):
        """Should scope deletion to a specific business_id."""
        mock_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"deleted": 10}]
        mock_store.execute_query = AsyncMock(return_value=mock_result)

        repo = GraphQueryRepository(mock_store)
        await repo.delete_wiki_data("my-biz-123")

        all_params = [c[0][1] for c in mock_store.execute_query.call_args_list]
        has_biz_id = any(p.get("business_id") == "my-biz-123" for p in all_params)
        has_prefix = any("my-biz-123" in str(p.get("prefix", "")) for p in all_params)
        assert has_biz_id or has_prefix, f"No call scoped to my-biz-123: {all_params}"
