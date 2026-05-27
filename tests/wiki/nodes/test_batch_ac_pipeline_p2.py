"""Tests for Batch AC — Pipeline Quality P2 remaining fixes."""
from __future__ import annotations

import asyncio
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from core.config import AppWikiFlags
from wiki.domain_doc_agent import DomainDocAgent
from wiki.page_agent import WorkingMemory
from wiki.token_budget import TokenBudgetResolver


def _make_state(modules: dict):
    all_uids = []
    for repo, mods in modules.items():
        for m in mods:
            all_uids.append(m["uid"])
    return {
        "business_id": "test-biz",
        "repositories": list(modules.keys()),
        "modules": modules,
        "entity_roles": {uid: "has_business_logic" for uid in all_uids},
        "is_incremental": False,
        "domain_mapping": {},
        "domain_tree": None,
        "affected_domains": [],
    }


def _make_module_dict(repo_id: str, name: str) -> dict:
    return {
        "uid": f"Module::{name}:0",
        "label": "Module",
        "properties": {
            "name": name,
            "path": f"src/main/{name}.java",
            "repository": repo_id,
        },
    }


def _mock_corrector():
    corrector = MagicMock()
    corrector.review_global_consistency = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return corrector


@pytest.mark.asyncio
async def test_recursive_split_sub_communities_run_in_parallel():
    """Multiple sub-communities at the same depth should be processed concurrently."""
    from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node

    modules_list = [(f"repo1", f"Mod{i}") for i in range(36)]
    big_community = set(modules_list)
    depth0_subs = [set(modules_list[i : i + 12]) for i in range(0, 36, 12)]
    depth1_subs = [
        set(sorted(group)[i : i + 4])
        for group in depth0_subs
        for i in range(0, 12, 4)
    ]

    cluster_calls = [0]
    in_flight = [0]
    max_in_flight = [0]

    async def mock_embedding_clustering(*_args, **_kwargs):
        return [[big_community], np.zeros((36, 8))]

    def cluster_sub_domains(_embeddings, sub_modules, _edges):
        cluster_calls[0] += 1
        mod_set = set(sub_modules)
        if len(sub_modules) == 36:
            return depth0_subs
        for idx, group in enumerate(depth0_subs):
            if mod_set == group:
                return depth1_subs[idx * 3 : (idx + 1) * 3]
        return [mod_set]

    async def name_community(**kwargs):
        used_names = kwargs.get("used_names")
        if used_names is not None:
            in_flight[0] += 1
            max_in_flight[0] = max(max_in_flight[0], in_flight[0])
            await asyncio.sleep(0.03)
            in_flight[0] -= 1
            mod_name = kwargs["module_infos"][0]["name"]
            return {"slug": f"sub-{mod_name.lower()}", "display_name": f"Domain {mod_name}"}
        return {"slug": "big-domain", "display_name": "Big Domain"}

    modules = {
        "repo1": [_make_module_dict("repo1", f"Mod{i}") for i in range(36)],
    }
    state = _make_state(modules)

    mock_graph_store = MagicMock()
    mock_result = MagicMock()
    mock_result.data = [
        {
            "source_repo": "repo1",
            "source": f"Mod{i}",
            "target_repo": "repo1",
            "target": f"Mod{i + 1}",
            "weight": 10,
        }
        for i in range(35)
    ]
    mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

    mock_namer = MagicMock()
    mock_namer.name_community = AsyncMock(side_effect=name_community)
    mock_clusterer = MagicMock()
    mock_clusterer.cluster_sub_domains.side_effect = cluster_sub_domains

    config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
    with patch(
        "wiki.nodes.graph_domain_decompose._get_split_params",
        return_value=(10, 3),
    ), patch(
        "wiki.nodes.graph_domain_decompose._embedding_clustering",
        side_effect=mock_embedding_clustering,
    ), patch(
        "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer",
        return_value=mock_clusterer,
    ), patch(
        "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
        return_value=mock_namer,
    ), patch(
        "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
        return_value=_mock_corrector(),
    ):
        result = await graph_driven_domain_decompose_node(state, config)

    assert cluster_calls[0] >= 4, "Expected recursive splits at depth 0 and depth 1"
    assert max_in_flight[0] > 3, "Sub-community processing should exceed serial per-branch concurrency"
    assert result["domain_tree"]


@pytest.mark.asyncio
async def test_quality_gate_l3_failure_adds_pages_to_heal():
    """Page passing L1/L2 but failing L3 should be scheduled for heal."""
    from wiki.nodes.quality_gate import quality_gate_node

    page = {
        "path": "wiki/core-svc",
        "title": "Core Svc",
        "page_type": "topic",
        "content": (
            "## Overview\n"
            + "Detailed service documentation with enough content for structural checks.\n\n"
            "## Key components\n- CoreService handles workflows\n\n"
            "## Relationships\n- [[peer-service]]\n\n"
            "```mermaid\ngraph TD\nA-->B\n```\n"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "config": {
            "quality_levels": ["L1", "L2", "L3"],
            "importance_tiers": {"wiki/core-svc": "core"},
        },
        "heal_attempts": {},
        "heal_cycles": {},
        "_structural_check_cache": {},
        "modules": {},
    }
    mock_llm = AsyncMock()

    with patch("wiki.nodes.quality_gate._evaluate_l3", new_callable=AsyncMock) as mock_l3:
        mock_l3.return_value = ("wiki/core-svc", {"l3_llm_judge": 0.4})
        with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
            wiki_cfg = MagicMock()
            wiki_cfg.heal_l2_threshold = 0.0
            wiki_cfg.heal_on_l3_failure = True
            wiki_cfg.heal_l3_threshold = 0.7
            wiki_cfg.overview_min_content_chars = 2000
            wiki_cfg.topic_min_content_chars = 1000
            mock_settings.return_value = MagicMock(wiki=wiki_cfg)
            result = await quality_gate_node(state, {"configurable": {"llm": mock_llm}})

    assert "wiki/core-svc" in result.get("pages_to_heal", [])


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.asyncio
async def test_agent_no_early_exit_on_short_content():
    """Short stub content must not trigger early exit even with high quality scores."""
    mock_llm = MagicMock()
    mock_graph = MagicMock()

    agent = DomainDocAgent(
        domain_name="test-domain",
        llm=mock_llm,
        graph_store=mock_graph,
    )
    agent._page_agent = AsyncMock()
    short_content = "# test-domain\n\n" + ("x" * 180)
    agent._page_agent.explore = AsyncMock(return_value=WorkingMemory())
    agent._page_agent.write = AsyncMock(return_value=short_content)
    agent._max_iterations = 4
    agent._output_guardrail.evaluate = AsyncMock(
        return_value=MagicMock(passed=True, total_score=1.0),
    )

    mock_quality = MagicMock()
    mock_quality.coverage = 0.75
    mock_quality.citation_density = 0.5
    mock_quality.context_gap_count = 1
    mock_quality.uncovered_modules = ["ModC"]
    mock_quality.implementation_depth = 0.2

    wiki_cfg = MagicMock()
    wiki_cfg.domain_agent_early_exit_quality = 0.6
    wiki_cfg.domain_agent_early_exit_min_chars = 500
    wiki_cfg.use_orchestrator_template = False
    wiki_cfg.topic_split_quality_check = False

    with patch("core.config.get_settings") as mock_settings, patch(
        "wiki.domain_doc_agent.evaluate_quality",
        return_value=mock_quality,
    ):
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        await agent.generate_with_iterations(
            module_names=["ModA", "ModB", "ModC"],
            baseline_context="baseline",
        )

    assert agent._page_agent.write.call_count >= 2


@pytest.mark.asyncio
async def test_domain_compose_injects_mermaid_when_missing():
    """Agent pages without Mermaid should receive an Architecture diagram section."""
    from wiki.nodes.domain_compose import compose_domain_agents_node

    state = {
        "domain_tree": [{
            "name": "order",
            "display_name": "Order",
            "modules": ["OrderService", "OrderRepo"],
        }],
        "module_summaries": {
            "OrderService": {"summary_text": "Handles orders"},
            "OrderRepo": {"summary_text": "Persists orders"},
        },
        "modules": {
            "repo_a": [
                {"properties": {"name": "OrderService", "repository": "repo_a", "path": "order.py"}},
                {"properties": {"name": "OrderRepo", "repository": "repo_a", "path": "repo.py"}},
            ],
        },
    }

    mock_agent = MagicMock()
    mock_agent.generate_with_iterations = AsyncMock(return_value=[{
        "page_type": "domain_overview",
        "title": "Order",
        "path": "/wiki/domains/order",
        "content": "# Order\n\nOverview without diagrams.",
        "diagrams": [],
        "metadata": {"generation_mode": "agent"},
    }])
    mock_agent.iteration_history = []

    with patch("wiki.nodes.domain_compose.DomainDocAgent", return_value=mock_agent):
        with patch("wiki.nodes.domain_compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            with patch("wiki.nodes.domain_compose.get_settings") as mock_settings:
                mock_settings.return_value.wiki.domain_agent_timeout_sec = 600
                mock_settings.return_value.wiki.use_orchestrator_template = False
                result = await compose_domain_agents_node(state, {"configurable": {"llm": AsyncMock()}})

    content = result["pages"][0]["content"]
    assert "## Architecture" in content
    assert "```mermaid" in content


def test_budget_resolver_resolve_used_when_provided():
    """Provided budget_resolver.resolve() should supply max_tokens."""
    from wiki.token_budget import resolve_max_tokens

    resolver = MagicMock(spec=TokenBudgetResolver)
    resolver.resolve.return_value = 9999
    assert resolve_max_tokens(resolver, "topic_plan", tier="core") == 9999
    resolver.resolve.assert_called_once_with("topic_plan", tier="core")


def test_budget_resolver_fallback_without_resolver():
    """Without budget_resolver, hardcoded fallback max_tokens should be used."""
    from wiki.token_budget import resolve_max_tokens

    assert resolve_max_tokens(None, "topic_plan") == 2000
    assert resolve_max_tokens(None, "module_title") == 200


@pytest.mark.asyncio
async def test_domain_doc_agent_delegates_to_generate_when_flag_enabled():
    """With use_orchestrator_template=True, generate() replaces the legacy loop."""
    mock_llm = MagicMock()
    mock_graph = MagicMock()
    agent = DomainDocAgent(
        domain_name="test-domain",
        llm=mock_llm,
        graph_store=mock_graph,
    )
    expected_pages = [{
        "page_type": "domain_overview",
        "title": "test-domain",
        "path": "/wiki/domains/test-domain",
        "content": "# test-domain\n\n" + ("content " * 120),
        "diagrams": [],
        "metadata": {"generation_mode": "agent"},
    }]
    agent.generate = AsyncMock(return_value=expected_pages)
    agent._page_agent = AsyncMock()
    agent._page_agent.explore = AsyncMock()
    agent._page_agent.write = AsyncMock()

    wiki_cfg = MagicMock()
    wiki_cfg.use_orchestrator_template = True

    with patch("core.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pages = await agent.generate_with_iterations(
                module_names=["ModA"],
                baseline_context="baseline",
            )

    assert agent.generate.await_count == 1
    assert agent._page_agent.write.await_count == 0
    assert pages == expected_pages
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_use_orchestrator_template_config_default():
    assert AppWikiFlags().use_orchestrator_template is True


def test_heal_on_l3_failure_config_default():
    assert AppWikiFlags().heal_on_l3_failure is True
