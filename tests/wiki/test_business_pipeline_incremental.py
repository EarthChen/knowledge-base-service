"""Tests for Batch U: existing_summaries preload and no_content_changes short-circuit."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.business_pipeline_runner import BusinessPipelineRunner
from wiki.models import PageType
from wiki.persistence import WikiPagePersistence
from wiki.pipeline_orchestrator import PipelineResult, load_existing_module_summaries


def _biz_wiki_mock(*, incremental_enabled: bool = True):
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
    m.incremental_enabled = incremental_enabled
    m.llm_global_rpm_limit = 60
    m.llm_global_tpm_limit = 100000
    return m


def _runner(**kwargs) -> BusinessPipelineRunner:
    defaults = dict(
        store=AsyncMock(),
        graph=AsyncMock(),
        wiki_cfg=_biz_wiki_mock(),
        wiki_store=AsyncMock(),
        persistence=MagicMock(spec=WikiPagePersistence),
        llm_factory=None,
        embedding_cfg=inject_wiki_embedding()[1],
        budget_resolver=MagicMock(),
        flow_writer=MagicMock(),
        tree_linker=MagicMock(),
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
    defaults.update(kwargs)
    return BusinessPipelineRunner(**defaults)


@pytest.mark.asyncio
async def test_load_existing_module_summaries_from_graph_fallback() -> None:
    """When checkpoint is empty, fall back to Module.business_summary on graph nodes."""
    all_modules = {
        "repo-a": [
            GraphNode(
                uid="Module:repo-a:OrderService",
                label=NodeLabel.MODULE,
                properties={
                    "name": "OrderService",
                    "business_summary": "Handles order lifecycle",
                },
            ),
        ],
    }
    with patch(
        "wiki.pipeline_orchestrator._load_summaries_from_checkpoint",
        new_callable=AsyncMock,
        return_value={},
    ):
        summaries = await load_existing_module_summaries("test-biz", all_modules)

    assert "repo-a|OrderService" in summaries
    assert summaries["repo-a|OrderService"]["summary_text"] == "Handles order lifecycle"
    assert summaries["OrderService"]["summary_text"] == "Handles order lifecycle"


@pytest.mark.asyncio
async def test_compose_reuses_existing_summaries_field() -> None:
    """compose_leaf_modules_node should honor existing_summaries when module_summaries is empty."""
    from wiki.nodes.compose import compose_leaf_modules_node

    long_summary = "A detailed module summary. " * 5

    state = {
        "modules": {
            "repo_a": [
                {
                    "properties": {"name": "UserService", "repository": "repo_a", "path": "a/user.py"},
                    "labels": ["Module"],
                },
                {
                    "properties": {"name": "OrderService", "repository": "repo_a", "path": "a/order.py"},
                    "labels": ["Module"],
                },
            ],
        },
        "entity_roles": {},
        "is_incremental": True,
        "affected_modules": {"UserService"},
        "existing_summaries": {
            "OrderService": {"summary_text": long_summary + " Handles orders", "key_methods": ["create_order"]},
        },
    }

    call_count = 0

    async def mock_gen(name, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return (name, {"summary_text": long_summary + f" Summary of {name}", "key_methods": []})

    configurable = {"llm": AsyncMock(), "graph_store": None}

    with patch("wiki.nodes.compose._generate_single_module_summary", side_effect=mock_gen):
        with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            result = await compose_leaf_modules_node(state, {"configurable": configurable})

    summaries = result.get("module_summaries", {})
    assert call_count == 1
    assert "OrderService" in summaries
    assert "Handles orders" in summaries["OrderService"]["summary_text"]


@pytest.mark.asyncio
async def test_runner_passes_existing_summaries_to_pipeline() -> None:
    """BusinessPipelineRunner should preload summaries and pass them to run_langgraph_pipeline."""
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "test-repo", "module_count": 1},
        ]
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

    persistence = MagicMock(spec=WikiPagePersistence)
    persistence.list_pinned_modules = AsyncMock(return_value=[])
    persistence.cleanup_stale_domain_edges = AsyncMock()
    persistence.cleanup_stale_domain_sections = AsyncMock()
    persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)

    tree_linker = MagicMock()
    tree_linker.link_pages_to_tree = AsyncMock()

    pipeline_result = PipelineResult(
        domain_mapping={"infra": [("test-repo", "mod")]},
        domain_tree=None,
        pages=[],
        resolved_links={},
        entity_roles={},
    )

    preloaded = {"test-repo|mod": {"summary_text": "Cached summary", "key_methods": []}}

    with patch(
        "wiki.pipeline_orchestrator.load_existing_module_summaries",
        new_callable=AsyncMock,
        return_value=preloaded,
    ):
        with patch(
            "wiki.pipeline_orchestrator.run_langgraph_pipeline",
            new_callable=AsyncMock,
            return_value=pipeline_result,
        ) as mock_pipeline:
            with patch("wiki.incremental_diff.compute_domain_diff", new_callable=AsyncMock) as mock_diff:
                from wiki.incremental_diff import DomainDiff

                mock_diff.return_value = DomainDiff([], [], 0)
                runner = _runner(
                    store=mock_store,
                    graph=graph,
                    wiki_store=mock_wiki_store,
                    persistence=persistence,
                    tree_linker=tree_linker,
                )
                await runner.run("test-biz", language="en", incremental=True)

    mock_pipeline.assert_awaited_once()
    call_kwargs = mock_pipeline.call_args.kwargs
    assert call_kwargs.get("existing_summaries") == preloaded


@pytest.mark.asyncio
async def test_no_content_changes_skips_pipeline() -> None:
    """When no_content_changes=True, run_langgraph_pipeline must not be called."""
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "test-repo", "module_count": 1},
        ]
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(
        return_value={
            "test-repo": {"last_indexed": "2026-01-02T00:00:00", "last_generated": "2026-01-02T00:00:00"},
        }
    )
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(
        return_value=[
            {
                "uid": "WikiPage:test-biz:domains/payment",
                "title": "Payment",
                "path": "domains/payment",
                "content": "# Payment\n\nCached content",
                "page_type": PageType.DOMAIN_OVERVIEW.value,
                "repository": "test-biz",
                "importance_tier": "core",
                "content_hash": "abc",
                "entity_uid": "",
            },
        ]
    )
    mock_wiki_store.get_pipeline_domain_tree_snapshot = AsyncMock(
        return_value={
            "tree": [{"name": "payment", "modules": ["mod"], "children": []}],
        }
    )

    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(
        return_value=[
            GraphNode(
                uid="Module:test-repo:mod",
                label=NodeLabel.MODULE,
                properties={"name": "mod", "path": "mod", "business_domain": "payment"},
            ),
        ],
    )
    graph.update_node_property = AsyncMock()
    graph.find_descendants = AsyncMock(return_value=[])

    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = MagicMock(spec=WikiPagePersistence)
    persistence.list_pinned_modules = AsyncMock(return_value=[])
    persistence.cleanup_stale_domain_edges = AsyncMock()
    persistence.cleanup_stale_domain_sections = AsyncMock()
    persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)

    tree_linker = MagicMock()
    tree_linker.link_pages_to_tree = AsyncMock()
    tree_linker.link_pages_to_nested_tree = AsyncMock()

    with patch(
        "wiki.pipeline_orchestrator.load_existing_module_summaries",
        new_callable=AsyncMock,
        return_value={},
    ):
        with patch(
            "wiki.pipeline_orchestrator.run_langgraph_pipeline",
            new_callable=AsyncMock,
        ) as mock_pipeline:
            with patch("wiki.incremental_diff.compute_domain_diff", new_callable=AsyncMock) as mock_diff:
                from wiki.incremental_diff import DomainDiff

                mock_diff.return_value = DomainDiff([], [], 0)
                runner = _runner(
                    store=mock_store,
                    graph=graph,
                    wiki_store=mock_wiki_store,
                    persistence=persistence,
                    tree_linker=tree_linker,
                )
                result = await runner.run("test-biz", language="en", incremental=True)

    mock_pipeline.assert_not_awaited()
    assert result["pages_count"] == 1
    assert result["business_id"] == "test-biz"


@pytest.mark.asyncio
async def test_force_full_run_bypasses_short_circuit() -> None:
    """force_full_run=True should run the pipeline even when no_content_changes."""
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[
            {"repository": "test-repo", "module_count": 1},
        ]
    )
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(
        return_value={
            "test-repo": {"last_indexed": "2026-01-02T00:00:00", "last_generated": "2026-01-02T00:00:00"},
        }
    )
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

    persistence = MagicMock(spec=WikiPagePersistence)
    persistence.list_pinned_modules = AsyncMock(return_value=[])
    persistence.cleanup_stale_domain_edges = AsyncMock()
    persistence.cleanup_stale_domain_sections = AsyncMock()
    persistence.cleanup_stale_wiki_pages = AsyncMock(return_value=0)

    tree_linker = MagicMock()
    tree_linker.link_pages_to_tree = AsyncMock()

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
                runner = _runner(
                    store=mock_store,
                    graph=graph,
                    wiki_store=mock_wiki_store,
                    persistence=persistence,
                    tree_linker=tree_linker,
                )
                await runner.run("test-biz", incremental=True, force_full_run=True)

    mock_pipeline.assert_awaited_once()
