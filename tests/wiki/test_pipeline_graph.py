"""Tests for wiki pipeline graph definition."""
import pytest


def test_build_wiki_pipeline_returns_compiled_graph():
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_should_heal_returns_synthesize_when_no_pages_to_heal():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": [],
        "heal_attempts": {},
    }
    assert should_heal(state) == "synthesize_overviews"


def test_should_heal_returns_heal_when_pages_need_healing():
    from wiki.pipeline_graph import should_heal
    state = {
        "pages_to_heal": ["page/a"],
        "heal_attempts": {"page/a": 0},
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
        "collect_modules", "detect_reorg", "classify_domains", "decompose_hierarchy",
        "plan_structure", "compose_pages", "quality_gate",
        "heal_pages", "synthesize_overviews", "create_links",
        "finalize", "__start__", "__end__",
    }
    assert expected.issubset(node_ids)


def test_pipeline_has_all_expected_nodes():
    """Pipeline should include all Phase 1-4 nodes plus detect_reorg."""
    from wiki.pipeline_graph import build_wiki_pipeline
    pipeline = build_wiki_pipeline()
    graph_data = pipeline.get_graph()
    node_names = set(graph_data.nodes.keys())
    expected = {
        "collect_modules", "detect_reorg", "classify_domains",
        "decompose_hierarchy", "plan_structure", "compose_pages",
        "synthesize_overviews", "create_links",
        "quality_gate", "heal_pages", "finalize",
    }
    missing = expected - node_names
    assert not missing, f"Missing nodes: {missing}"
