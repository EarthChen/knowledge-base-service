"""Unit tests for extracted business pipeline and incremental generator modules."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.business_pipeline_runner import BusinessPipelineRunner
from wiki.incremental_diff import WikiDiff
from wiki.incremental_generator import IncrementalWikiGenerator
from wiki.persistence import WikiPagePersistence


def _biz_wiki_mock():
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
    return m


@pytest.mark.asyncio
async def test_business_pipeline_runner_empty_repos() -> None:
    """When no repos are indexed, return empty result immediately."""
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[])

    runner = BusinessPipelineRunner(
        store=AsyncMock(),
        graph=AsyncMock(),
        wiki_cfg=_biz_wiki_mock(),
        wiki_store=mock_wiki_store,
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

    result = await runner.run("empty-biz")
    assert result["domains"] == []
    assert result["pages_count"] == 0


@pytest.mark.asyncio
async def test_business_pipeline_runner_delegates_to_langgraph() -> None:
    """BusinessPipelineRunner.run should invoke run_langgraph_pipeline."""
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "test-repo", "module_count": 1},
    ])
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={})
    mock_wiki_store.get_wiki_pages_for_business = AsyncMock(return_value=[])

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

    tree_linker = MagicMock()
    tree_linker.link_pages_to_tree = AsyncMock()

    pipeline_result = MagicMock()
    pipeline_result.domain_mapping = {"infra": [("test-repo", "mod")]}
    pipeline_result.domain_tree = None
    pipeline_result.pages = []
    pipeline_result.domain_display_names = {"infra": "Infrastructure"}
    pipeline_result.resolved_links = {}

    with patch(
        "wiki.pipeline_orchestrator.run_langgraph_pipeline",
        new_callable=AsyncMock,
        return_value=pipeline_result,
    ) as mock_pipeline:
        runner = BusinessPipelineRunner(
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
        result = await runner.run("test-biz", language="en")

    mock_pipeline.assert_awaited_once()
    assert result["business_id"] == "test-biz"
    assert isinstance(result["domains"], list)


@pytest.mark.asyncio
async def test_incremental_generator_no_baseline() -> None:
    """When no previous generation exists, return no_baseline."""
    mock_ws = AsyncMock()
    mock_ws.get_wiki_generation_version = AsyncMock(return_value=None)

    gen = IncrementalWikiGenerator(
        store=MagicMock(),
        graph=MagicMock(),
        wiki_cfg=_biz_wiki_mock(),
        wiki_store=mock_ws,
        persistence=MagicMock(spec=WikiPagePersistence),
        collector=MagicMock(),
        page_composer=MagicMock(),
        budget_resolver=MagicMock(),
        composer_factory=MagicMock(),
        config_for=MagicMock(),
        ensure_repo=AsyncMock(),
        persist_pages=AsyncMock(),
    )

    result = await gen.generate("test-repo")
    assert result["status"] == "no_baseline"


@pytest.mark.asyncio
async def test_incremental_generator_no_changes() -> None:
    """When no code changes detected, return no_changes."""
    mock_ws = AsyncMock()
    mock_ws.get_wiki_generation_version = AsyncMock(return_value=1)

    with patch(
        "wiki.incremental_generator.compute_wiki_diff",
        new_callable=AsyncMock,
        return_value=WikiDiff(set(), set()),
    ):
        gen = IncrementalWikiGenerator(
            store=MagicMock(),
            graph=MagicMock(),
            wiki_cfg=_biz_wiki_mock(),
            wiki_store=mock_ws,
            persistence=MagicMock(spec=WikiPagePersistence),
            collector=MagicMock(),
            page_composer=MagicMock(),
            budget_resolver=MagicMock(),
            composer_factory=MagicMock(),
            config_for=MagicMock(),
            ensure_repo=AsyncMock(),
            persist_pages=AsyncMock(),
        )
        result = await gen.generate("test-repo")
        assert result["status"] == "no_changes"
