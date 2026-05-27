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


class TestAnchorLoading:
    """Tests for F9-C2: anchor loading + persist sync."""

    @pytest.mark.asyncio
    async def test_anchors_loaded_on_full_run(self):
        """Both pinned_modules and anchored_slugs should be loaded."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._persistence = AsyncMock()
        runner._persistence.list_pinned_modules = AsyncMock(return_value=[
            {"module_name": "UserService", "domain_slug": "user-auth"},
        ])
        runner._persistence.list_domain_anchors = AsyncMock(return_value=[
            {"slug": "family-core", "anchor_type": "user", "display_name": "家族核心"},
            {"slug": "payment", "anchor_type": "system", "display_name": "支付"},
        ])

        state: dict = {}
        await runner._load_anchors_into_state("biz1", state)

        assert state["pinned_modules"] == {"UserService": "user-auth"}
        assert state["anchored_slugs"] == {"family-core"}
        assert state["anchor_display_names"]["family-core"] == "家族核心"
        assert state["anchor_display_names"]["payment"] == "支付"

    @pytest.mark.asyncio
    async def test_anchors_load_failure_graceful(self):
        """Load failure should not crash, just log warning."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._persistence = AsyncMock()
        runner._persistence.list_pinned_modules = AsyncMock(side_effect=Exception("DB error"))
        runner._persistence.list_domain_anchors = AsyncMock(side_effect=Exception("DB error"))

        state: dict = {}
        await runner._load_anchors_into_state("biz1", state)

        assert state["pinned_modules"] == {}
        assert state["anchored_slugs"] == set()
        assert state["anchor_display_names"] == {}


class TestPersistSyncAnchor:
    """Tests for F9-C2: persist classification calls save_domain_classification."""

    @pytest.mark.asyncio
    async def test_persist_calls_save_domain_classification(self):
        """persist_classification_node should call save_domain_classification."""
        from wiki.nodes.persist_classification import persist_classification_node

        persistence = AsyncMock()
        persistence.save_domain_classification = AsyncMock()
        wiki_store = AsyncMock()
        wiki_store.upsert_wiki_space = AsyncMock()
        wiki_store.delete_domain_sections = AsyncMock(return_value=0)
        wiki_store.upsert_wiki_section = AsyncMock()
        wiki_store.add_has_child_edge = AsyncMock()
        graph_store = AsyncMock()
        graph_store.update_node_property = AsyncMock()

        state = {
            "business_id": "biz1",
            "domain_mapping": {"auth": [("repo", "UserService")]},
            "domain_display_names": {"auth": "认证"},
            "domain_tree": None,
            "modules": {},
            "persistence": persistence,
        }
        config = {
            "configurable": {
                "wiki_store": wiki_store,
                "graph_store": graph_store,
                "persistence": persistence,
            }
        }

        await persist_classification_node(state, config)
        persistence.save_domain_classification.assert_called_once_with("biz1", {"auth": [("repo", "UserService")]})
