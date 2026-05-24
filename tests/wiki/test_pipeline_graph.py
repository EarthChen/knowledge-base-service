"""Tests for wiki pipeline graph definition."""
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_build_wiki_pipeline_returns_compiled_graph():
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_should_heal_returns_create_links_when_no_pages_to_heal():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": [],
        "heal_attempts": {},
    }
    assert should_heal(state) == "create_links"


def test_should_heal_returns_heal_when_pages_need_healing():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 0},
    }
    assert should_heal(state) == "heal_pages"


def test_should_heal_respects_global_attempt_budget():
    from wiki.pipeline_graph import should_heal

    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 10, "page/b": 1},
        "config": {},
    }
    assert should_heal(state) == "create_links"


def test_should_heal_respects_config_override():
    from wiki.pipeline_graph import should_heal

    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 3, "page/b": 3},
        "config": {"heal_loop_max_total_attempts": 5},
    }
    assert should_heal(state) == "create_links"


def test_should_heal_uses_default_when_no_config():
    from wiki.pipeline_graph import should_heal

    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 1},
        "config": {},
    }
    assert should_heal(state) == "heal_pages"


def test_should_heal_routes_to_heal_when_pages_present():
    """should_heal trusts quality_gate_node — if pages_to_heal is non-empty, route to heal."""
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 2},
    }
    assert should_heal(state) == "heal_pages"


def test_pipeline_graph_has_expected_nodes():
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline()
    drawable = graph.get_graph()
    node_ids = set(drawable.nodes.keys())
    expected = {
        "classify_entity_roles",
        "detect_reorg",
        "graph_decompose",
        "assign_canonical_keys",
        "generate_titles",
        "set_review_status",
        "compose_leaf_modules",
        "compose_domain_agents",
        "quality_gate",
        "heal_pages",
        "create_links",
        "finalize",
        "__start__",
        "__end__",
    }
    assert expected.issubset(node_ids)


def test_pipeline_has_all_expected_nodes():
    """Pipeline should include graph-decompose → agent compose stages plus linking."""
    from wiki.pipeline_graph import build_wiki_pipeline
    pipeline = build_wiki_pipeline()
    graph_data = pipeline.get_graph()
    node_names = set(graph_data.nodes.keys())
    expected = {
        "classify_entity_roles",
        "detect_reorg",
        "graph_decompose",
        "assign_canonical_keys",
        "generate_titles",
        "set_review_status",
        "compose_leaf_modules",
        "compose_domain_agents",
        "quality_gate",
        "heal_pages",
        "create_links",
        "finalize",
    }
    missing = expected - node_names
    assert not missing, f"Missing nodes: {missing}"


def _make_page(path: str, content: str) -> dict:
    return {
        "path": path,
        "title": path.split("/")[-1].replace(".md", ""),
        "content": content,
        "page_type": "topic",
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_quality_gate_l3_triggers_for_healed_standard_page(monkeypatch):
    """A STANDARD page that was healed and has L1>=0.7 should trigger L3."""
    from wiki.nodes.quality_gate import quality_gate_node
    from wiki.quality_evaluator import WikiQualityEvaluator

    mock_eval = MagicMock(spec=WikiQualityEvaluator)
    mock_eval.structural_check.return_value = MagicMock(overall=0.75, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.6)

    mock_l3_eval = MagicMock()
    mock_l3_result = MagicMock()
    mock_l3_result.dimensions = {"completeness": 4, "accuracy": 3, "readability": 4, "structure": 3}
    mock_l3_eval.evaluate_l3 = AsyncMock(return_value=mock_l3_result)

    state = {
        "pages": [_make_page("domain/auth.md", "# Auth\n" + "x" * 300)],
        "heal_attempts": {"domain/auth.md": 1},
        "quality_scores": {},
        "_structural_check_cache": {},
        "config": {
            "importance_tiers": {"domain/auth.md": "standard"},
            "quality_levels": ["L1", "L3"],
        },
    }

    config = {"configurable": {"llm": MagicMock()}}

    monkeypatch.setattr("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval)
    monkeypatch.setattr("wiki.nodes.quality_gate.WikiPageEvaluator", lambda: mock_l3_eval)

    result = await quality_gate_node(state, config)
    scores = result["quality_scores"]["domain/auth.md"]
    assert scores.get("l3_llm_judge") is not None, "L3 should be triggered for healed page"


@pytest.mark.asyncio
async def test_quality_gate_l3_not_triggered_for_unhealed_standard(monkeypatch):
    """A STANDARD page that was NOT healed should NOT trigger L3 (existing behavior)."""
    from wiki.nodes.quality_gate import quality_gate_node
    from wiki.quality_evaluator import WikiQualityEvaluator

    mock_eval = MagicMock(spec=WikiQualityEvaluator)
    mock_eval.structural_check.return_value = MagicMock(overall=0.75, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.6)

    mock_l3_eval = MagicMock()
    mock_l3_eval.evaluate_l3 = AsyncMock()

    state = {
        "pages": [_make_page("domain/order.md", "# Order\n" + "x" * 300)],
        "heal_attempts": {},
        "quality_scores": {},
        "_structural_check_cache": {},
        "config": {
            "importance_tiers": {"domain/order.md": "standard"},
            "quality_levels": ["L1", "L3"],
        },
    }

    config = {"configurable": {"llm": MagicMock()}}

    monkeypatch.setattr("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval)
    monkeypatch.setattr("wiki.nodes.quality_gate.WikiPageEvaluator", lambda: mock_l3_eval)

    result = await quality_gate_node(state, config)
    scores = result["quality_scores"]["domain/order.md"]
    assert scores.get("l3_llm_judge") is None, "L3 should NOT trigger for unhealed STANDARD"
    mock_l3_eval.evaluate_l3.assert_not_called()


@pytest.mark.asyncio
async def test_quality_gate_l3_cache_prevents_duplicate_evaluation(monkeypatch):
    """When l3_evaluated is set in cache, L3 should not be re-evaluated."""
    from wiki.nodes.quality_gate import quality_gate_node
    from wiki.quality_evaluator import WikiQualityEvaluator

    mock_eval = MagicMock(spec=WikiQualityEvaluator)
    mock_eval.structural_check.return_value = MagicMock(overall=0.75, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.6)

    mock_l3_eval = MagicMock()
    mock_l3_eval.evaluate_l3 = AsyncMock()

    page_content = "# Auth\n" + "x" * 300
    content_hash = hashlib.sha256(page_content.encode("utf-8", errors="replace")).hexdigest()

    state = {
        "pages": [_make_page("domain/auth.md", page_content)],
        "heal_attempts": {"domain/auth.md": 1},
        "quality_scores": {},
        "_structural_check_cache": {
            "domain/auth.md": {
                "score": {"l1_structural": 0.75},
                "content_hash": content_hash,
                "l3_evaluated": True,
            }
        },
        "config": {
            "importance_tiers": {"domain/auth.md": "standard"},
            "quality_levels": ["L1", "L3"],
        },
    }

    config = {"configurable": {"llm": MagicMock()}}

    monkeypatch.setattr("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval)
    monkeypatch.setattr("wiki.nodes.quality_gate.WikiPageEvaluator", lambda: mock_l3_eval)

    await quality_gate_node(state, config)
    mock_l3_eval.evaluate_l3.assert_not_called()
