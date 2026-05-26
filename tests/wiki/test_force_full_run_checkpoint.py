"""Tests that force_full_run clears LangGraph checkpoint before pipeline execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.business_pipeline_runner import BusinessPipelineRunner
from wiki.persistence import WikiPagePersistence
from wiki.pipeline_orchestrator import PipelineResult


def _biz_wiki_mock() -> MagicMock:
    m = MagicMock()
    m.cross_repo_domain_enabled = True
    m.business_domain_enabled = True
    m.business_domain_infrastructure_label = "__infrastructure__"
    m.enrichment_enabled = False
    m.code_budget_enabled = False
    m.rag_enabled = False
    m.business_wiki_batch_threshold = 100
    m.business_domain_sub_batch_size = 80
    m.business_domain_classify_timeout = 600
    m.business_domain_max_concurrency = 3
    m.business_domain_cache_ttl = 3600
    m.business_wiki_skip_repo_pages = True
    m.business_repo_concurrency = 2
    m.incremental_enabled = True
    m.llm_global_rpm_limit = 60
    m.llm_global_tpm_limit = 100000
    m.auto_cleanup_checkpoint = False
    return m


def _make_runner(persistence: MagicMock) -> BusinessPipelineRunner:
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[{"repository": "test-repo", "module_count": 1}],
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
    mock_wiki_store.get_pipeline_domain_tree_snapshot = AsyncMock(return_value={"tree": []})

    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(
        return_value=[
            GraphNode(
                uid="Module:test-repo:mod",
                label=NodeLabel.MODULE,
                properties={"name": "mod", "path": "mod"},
            ),
        ],
    )
    graph.update_node_property = AsyncMock()
    graph.find_descendants = AsyncMock(return_value=[])

    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence.list_pinned_modules = AsyncMock(return_value=[])
    persistence.cleanup_stale_domain_edges = AsyncMock()
    persistence.cleanup_stale_domain_sections = AsyncMock()
    persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)

    tree_linker = MagicMock()
    tree_linker.link_pages_to_tree = AsyncMock()

    return BusinessPipelineRunner(
        store=mock_store,
        graph=graph,
        wiki_cfg=_biz_wiki_mock(),
        wiki_store=mock_wiki_store,
        persistence=persistence,
        llm_factory=None,
        embedding_cfg=inject_wiki_embedding()[1],
        budget_resolver=MagicMock(),
        flow_writer=MagicMock(),
        tree_linker=tree_linker,
        memory_loop=None,
        community_service=None,
        llm_resolver=lambda _p: None,
        redis_conn=None,
        task_supervisor=None,
        repo_generator=AsyncMock(),
        persist_pages=AsyncMock(),
        bulk_set_wiki_code_hashes=AsyncMock(),
        persist_resolved_wikilinks=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_force_full_run_deletes_checkpoint_before_pipeline() -> None:
    """force_full_run=True should clear checkpoint before LangGraph pipeline runs."""
    persistence = MagicMock(spec=WikiPagePersistence)
    persistence.delete_checkpoint = AsyncMock()
    runner = _make_runner(persistence)

    pipeline_result = PipelineResult(
        domain_mapping={"infra": [("test-repo", "mod")]},
        domain_tree=None,
        pages=[],
        resolved_links={},
        entity_roles={},
    )

    with patch(
        "wiki.pipeline_orchestrator.load_existing_module_summaries",
        new_callable=AsyncMock,
        return_value={},
    ):
        with patch(
            "wiki.pipeline_orchestrator.run_langgraph_pipeline",
            new_callable=AsyncMock,
            return_value=pipeline_result,
        ) as mock_pipeline:
            with patch("wiki.incremental_diff.compute_domain_diff", new_callable=AsyncMock) as mock_diff:
                from wiki.incremental_diff import DomainDiff

                mock_diff.return_value = DomainDiff([], [], 0)
                await runner.run("test", force_full_run=True)

    persistence.delete_checkpoint.assert_awaited_once_with("test")
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_full_run_false_does_not_delete_checkpoint() -> None:
    """force_full_run=False should not clear checkpoint."""
    persistence = MagicMock(spec=WikiPagePersistence)
    persistence.delete_checkpoint = AsyncMock()
    runner = _make_runner(persistence)

    pipeline_result = PipelineResult(
        domain_mapping={"infra": [("test-repo", "mod")]},
        domain_tree=None,
        pages=[],
        resolved_links={},
        entity_roles={},
    )

    with patch(
        "wiki.pipeline_orchestrator.load_existing_module_summaries",
        new_callable=AsyncMock,
        return_value={},
    ):
        with patch(
            "wiki.pipeline_orchestrator.run_langgraph_pipeline",
            new_callable=AsyncMock,
            return_value=pipeline_result,
        ):
            with patch("wiki.incremental_diff.compute_domain_diff", new_callable=AsyncMock) as mock_diff:
                from wiki.incremental_diff import DomainDiff

                mock_diff.return_value = DomainDiff([], [], 0)
                await runner.run("test", force_full_run=False)

    persistence.delete_checkpoint.assert_not_awaited()


class TestAutoCleanupCheckpoint:
    @pytest.mark.asyncio
    async def test_auto_cleanup_deletes_checkpoint_after_success(self):
        """When auto_cleanup_checkpoint=True, checkpoint should be deleted after pipeline success."""
        from unittest.mock import AsyncMock, MagicMock

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        mock_persistence = MagicMock()
        mock_persistence.delete_checkpoint = AsyncMock()

        mock_cfg = MagicMock()
        mock_cfg.auto_cleanup_checkpoint = True

        runner = BusinessPipelineRunner(
            store=MagicMock(),
            graph=MagicMock(),
            wiki_cfg=mock_cfg,
            wiki_store=MagicMock(),
            persistence=mock_persistence,
            llm_factory=None,
            embedding_cfg=MagicMock(),
            budget_resolver=MagicMock(),
            flow_writer=MagicMock(),
            tree_linker=MagicMock(),
            memory_loop=None,
            community_service=None,
            llm_resolver=lambda x: MagicMock(),
            redis_conn=None,
            task_supervisor=None,
            repo_generator=AsyncMock(),
            persist_pages=AsyncMock(),
            bulk_set_wiki_code_hashes=AsyncMock(),
            persist_resolved_wikilinks=AsyncMock(),
        )

        await runner._post_run_cleanup("test-biz")
        mock_persistence.delete_checkpoint.assert_called_once_with("test-biz")

    @pytest.mark.asyncio
    async def test_auto_cleanup_skipped_when_disabled(self):
        """When auto_cleanup_checkpoint=False, checkpoint should NOT be deleted."""
        from unittest.mock import AsyncMock, MagicMock

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        mock_persistence = MagicMock()
        mock_persistence.delete_checkpoint = AsyncMock()

        mock_cfg = MagicMock()
        mock_cfg.auto_cleanup_checkpoint = False

        runner = BusinessPipelineRunner(
            store=MagicMock(),
            graph=MagicMock(),
            wiki_cfg=mock_cfg,
            wiki_store=MagicMock(),
            persistence=mock_persistence,
            llm_factory=None,
            embedding_cfg=MagicMock(),
            budget_resolver=MagicMock(),
            flow_writer=MagicMock(),
            tree_linker=MagicMock(),
            memory_loop=None,
            community_service=None,
            llm_resolver=lambda x: MagicMock(),
            redis_conn=None,
            task_supervisor=None,
            repo_generator=AsyncMock(),
            persist_pages=AsyncMock(),
            bulk_set_wiki_code_hashes=AsyncMock(),
            persist_resolved_wikilinks=AsyncMock(),
        )

        await runner._post_run_cleanup("test-biz")
        mock_persistence.delete_checkpoint.assert_not_called()
