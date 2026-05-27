from __future__ import annotations

from unittest.mock import AsyncMock
import pytest


class TestStaleSoftDelete:
    """Tests for F9-C1: soft-delete + purge."""

    @pytest.mark.asyncio
    async def test_stale_pages_marked_not_deleted(self):
        """Stale pages should be marked with stale=true, not physically deleted."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = AsyncMock()

        query_results = [
            {"uid": "uid1", "path": "/__domains__/old-domain/_overview"},
            {"uid": "uid2", "path": "/__domains__/current-domain/_overview"},
        ]
        runner._wiki_store.query = AsyncMock(side_effect=[query_results, None])

        current_slugs = {"current-domain"}
        count = await runner._cleanup_stale_domain_pages("biz1", current_slugs)

        assert count == 1
        last_call = runner._wiki_store.query.call_args_list[-1]
        query_str = last_call[0][0]
        assert "SET wp.stale = true" in query_str
        assert "DETACH DELETE" not in query_str

    @pytest.mark.asyncio
    async def test_user_anchored_not_stale(self):
        """User-anchored domains should never be marked stale."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = AsyncMock()
        runner._wiki_store.query = AsyncMock(return_value=[
            {"uid": "uid1", "path": "/__domains__/user-pinned-domain/_overview"},
        ])

        current_slugs: set[str] = set()
        anchored_slugs = {"user-pinned-domain"}
        count = await runner._cleanup_stale_domain_pages(
            "biz1", current_slugs, anchored_slugs=anchored_slugs,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_after_retention(self):
        """Pages stale for > retention_days should be permanently deleted."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = AsyncMock()
        runner._wiki_store.query = AsyncMock(return_value=[{"cnt": 3}])

        count = await runner._purge_stale_pages("biz1", retention_days=7)
        assert count == 3
        query_str = runner._wiki_store.query.call_args[0][0]
        assert "DETACH DELETE" in query_str
        assert "wp.stale = true" in query_str
