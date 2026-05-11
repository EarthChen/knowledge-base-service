"""Coverage for LangGraph node–phase mapping used for wiki pipeline progress."""

from __future__ import annotations

from wiki.pipeline_graph import _NODE_PHASE_MAP


def test_node_phase_map_covers_all_pipeline_nodes() -> None:
    expected_nodes = {
        "classify_entity_roles",
        "detect_reorg",
        "graph_decompose",
        "assign_canonical_keys",
        "classify_domains",
        "decompose_hierarchy",
        "generate_titles",
        "set_review_status",
        "compose_leaf_modules",
        "compose_bottomup",
        "compose_domain_agents",
        "quality_gate",
        "heal_pages",
        "create_links",
        "finalize",
    }
    assert set(_NODE_PHASE_MAP.keys()) == expected_nodes


def test_node_phase_percentages_ascending() -> None:
    pcts = [v[1] for v in _NODE_PHASE_MAP.values()]
    assert pcts == sorted(pcts)


def test_node_phase_map_pcts_in_range() -> None:
    for node, (phase, pct) in _NODE_PHASE_MAP.items():
        assert 0.0 <= pct <= 1.0, f"{node}: pct {pct} out of range"
        assert phase, f"{node}: empty phase name"
