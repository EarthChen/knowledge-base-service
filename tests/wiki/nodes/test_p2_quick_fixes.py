"""Tests for Batch P backend quick P2 fixes."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.business_pipeline_runner import BusinessPipelineRunner
from wiki.persistence import WikiPagePersistence


def _biz_wiki_mock(**overrides):
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
    m.incremental_enabled = overrides.get("incremental_enabled", False)
    m.llm_global_rpm_limit = 0
    m.llm_global_tpm_limit = 0
    return m


@pytest.mark.asyncio
async def test_round2_gap_fill_skips_compound_keys():
    """Round-2 gap-fill should only process bare module names, not repo|name keys."""
    from wiki.nodes.compose import compose_leaf_modules_node

    state = {
        "modules": {
            "repo_a": [
                {
                    "properties": {"name": "UserService", "repository": "repo_a", "path": "a/user.py"},
                    "labels": ["Module"],
                },
            ],
        },
        "entity_roles": {},
    }
    r2_calls: list[str] = []

    async def mock_gen(name, *args, **kwargs):
        if kwargs.get("neighbor_summaries"):
            r2_calls.append(name)
            return (name, {"summary_text": "Filled summary " * 10, "key_methods": []})
        return (name, {"summary_text": "CONTEXT_GAP", "key_methods": []})

    configurable = {"llm": AsyncMock(), "graph_store": None}

    with patch("wiki.nodes.compose._generate_single_module_summary", side_effect=mock_gen):
        with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            await compose_leaf_modules_node(state, {"configurable": configurable})

    assert r2_calls == ["UserService"]
    assert "repo_a|UserService" not in r2_calls


@pytest.mark.asyncio
async def test_heal_cycles_always_increments():
    """All pages entering heal should increment heal_cycles for safety valve."""
    from wiki.nodes.heal import heal_pages_node

    page_path = "/__domains__/d/page/_topic"
    page = {
        "path": page_path,
        "title": "Page",
        "content": "short",
        "page_type": "topic",
        "domain": "test-domain",
    }

    async def mock_heal_one_page(**kwargs):
        kwargs["page_dict"]["content"] = (
            "## Overview\nDetailed description of the business domain and responsibilities.\n\n"
            "## Key components\n- CoreService — handles primary workflows\n\n"
            "## Relationships\n- Depends on downstream APIs.\n\n"
            "```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
            "## 业务概述\nDetailed Chinese summary.\n\n"
            "## 核心业务流程\nOperational flow.\n\n"
            "## 核心服务详情\n### Service\nHandles core logic.\n\n"
            "## 关联主题\n- [[other-domain]]\n"
        )
        return True

    state = {
        "pages_to_heal": [page_path],
        "pages": [page],
        "config": {"importance_tiers": {page_path: "standard"}},
        "heal_attempts": {},
        "heal_cycles": {},
        "heal_hints": {},
        "domain_tree": [],
    }

    with patch("core.config.get_settings") as mock_settings:
        mock_settings.return_value.wiki.heal_max_rounds_core = 3
        mock_settings.return_value.wiki.heal_max_rounds_standard = 1
        with patch("wiki.nodes.heal._heal_one_page", side_effect=mock_heal_one_page):
            result = await heal_pages_node(state, {"configurable": {"llm": AsyncMock(), "graph_store": None}})

    assert result.get("heal_cycles", {}).get(page_path, 0) >= 1


@pytest.mark.asyncio
async def test_business_runner_respects_incremental_enabled_false():
    """When incremental_enabled=False, pipeline should not run in incremental mode."""
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(
        return_value=[{"repository": "test-repo", "module_count": 1}],
    )
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
            wiki_cfg=_biz_wiki_mock(incremental_enabled=False),
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
        await runner.run("test-biz", incremental=True)

    mock_pipeline.assert_awaited_once()
    assert mock_pipeline.call_args.kwargs["is_incremental"] is False


def test_domain_agent_timeout_config_alignment():
    """Inner agent budget must not exceed outer wrapper timeout from config."""
    from core.config import AppWikiFlags
    from wiki.domain_doc_agent import _domain_agent_total_budget_sec

    cfg = AppWikiFlags(domain_agent_timeout_sec=600)
    margin = 30
    inner_budget = max(1, cfg.domain_agent_timeout_sec - margin)
    assert inner_budget <= cfg.domain_agent_timeout_sec
    assert inner_budget == 570

    with patch("core.config.get_settings") as mock_settings:
        mock_settings.return_value.wiki.domain_agent_timeout_sec = 600
        assert _domain_agent_total_budget_sec() == 570


@pytest.mark.asyncio
async def test_domain_compose_module_tree_defaults_to_list():
    """Empty state without module_tree should not crash domain compose."""
    from wiki.nodes.domain_compose import compose_domain_agents_node

    state = {
        "domain_tree": [{"name": "order", "display_name": "Order", "modules": ["OrderService"]}],
        "module_summaries": {"OrderService": {"summary_text": "Handles orders"}},
        "modules": {
            "repo_a": [
                {"properties": {"name": "OrderService", "repository": "repo_a", "path": "order.py"}},
            ],
        },
    }

    mock_agent = MagicMock()
    mock_agent.generate_with_iterations = AsyncMock(return_value=[{
        "page_type": "domain_overview",
        "title": "Order",
        "path": "/wiki/domains/order",
        "content": "# Order\n\nOverview.",
        "diagrams": [],
        "metadata": {},
    }])
    mock_agent.iteration_history = []

    with patch("wiki.nodes.domain_compose.DomainDocAgent", return_value=mock_agent):
        with patch("wiki.nodes.domain_compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            with patch("wiki.nodes.domain_compose.get_settings") as mock_settings:
                mock_settings.return_value.wiki.domain_agent_timeout_sec = 600
                result = await compose_domain_agents_node(state, {"configurable": {"llm": AsyncMock()}})

    assert result["pages"]


@pytest.mark.asyncio
async def test_quality_gate_includes_compound_module_keys():
    """Citation validation should accept repo|name compound keys."""
    from wiki.nodes.quality_gate import quality_gate_node

    captured_names: list[set[str]] = []

    def mock_verify(content, names):
        captured_names.append(set(names))
        result = MagicMock()
        result.invalid_count = 0
        return result

    page = {
        "path": "wiki/page",
        "title": "Page",
        "content": "See [[repo_a|UserService]] for details.\n\n" + "x" * 200,
        "page_type": "topic",
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "config": {"quality_levels": ["L1"], "importance_tiers": {"wiki/page": "core"}},
        "heal_attempts": {},
        "_structural_check_cache": {},
        "modules": {
            "repo_a": [
                {"properties": {"name": "UserService", "repository": "repo_a"}},
            ],
            "repo_b": [
                {"properties": {"name": "UserService", "repository": "repo_b"}},
            ],
        },
    }

    with patch("wiki.nodes.quality_gate.verify_citations", side_effect=mock_verify):
        with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
            mock_settings.return_value.wiki.quality_gate_levels = "L1"
            mock_settings.return_value.wiki.heal_l2_threshold = 0.0
            mock_settings.return_value.wiki.overview_min_content_chars = 2000
            mock_settings.return_value.wiki.topic_min_content_chars = 1000
            await quality_gate_node(state, {"configurable": {}})

    assert captured_names
    names = captured_names[0]
    assert "UserService" in names
    assert "repo_a|UserService" in names
    assert "repo_b|UserService" in names


@pytest.mark.asyncio
async def test_domain_compose_sanitize_passes_module_entities():
    """Domain compose should build known_entities from state modules for sanitize."""
    from wiki.nodes.domain_compose import compose_domain_agents_node

    state = {
        "domain_tree": [{"name": "order", "display_name": "Order", "modules": ["OrderService"]}],
        "module_summaries": {"OrderService": {"summary_text": "Handles orders"}},
        "module_tree": [],
        "modules": {
            "repo_a": [
                {
                    "properties": {
                        "name": "OrderService",
                        "repository": "repo_a",
                        "path": "repo_a/order.py",
                    },
                },
            ],
        },
    }

    mock_agent = MagicMock()
    mock_agent.generate_with_iterations = AsyncMock(return_value=[{
        "page_type": "domain_overview",
        "title": "Order",
        "path": "/wiki/domains/order",
        "content": "# Order\n\nOverview.",
        "diagrams": [],
        "metadata": {},
    }])
    mock_agent.iteration_history = []

    captured_entities: list = []

    def mock_sanitize(content, known_entities):
        captured_entities.append(known_entities)
        return content

    with patch("wiki.nodes.domain_compose.DomainDocAgent", return_value=mock_agent):
        with patch("wiki.nodes.domain_compose.sanitize_wiki_content", side_effect=mock_sanitize):
            with patch("wiki.nodes.domain_compose.PipelineConcurrency") as mock_pc:
                mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
                with patch("wiki.nodes.domain_compose.get_settings") as mock_settings:
                    mock_settings.return_value.wiki.domain_agent_timeout_sec = 600
                    await compose_domain_agents_node(state, {"configurable": {"llm": AsyncMock()}})

    assert captured_entities
    entities = captured_entities[0]
    assert entities
    names = {e.get("name") for e in entities if isinstance(e, dict)}
    assert "OrderService" in names
