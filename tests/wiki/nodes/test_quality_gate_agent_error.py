"""Test that agent_error pages participate in healing (one attempt)."""
from __future__ import annotations

import pytest

from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_agent_error_pages_added_to_heal_once(monkeypatch):
    """Pages with generation_mode=agent_error should enter pages_to_heal once."""
    def _fake_settings():
        wiki = type("W", (), {"quality_gate_levels": "L1", "heal_l2_threshold": 0.0})()
        return type("S", (), {"wiki": wiki})()

    monkeypatch.setattr("wiki.nodes.quality_gate.get_settings", _fake_settings)

    error_page = {
        "path": "/wiki/broken-domain",
        "title": "Broken Domain",
        "page_type": "topic",
        "content": "Error generating page",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "agent_error"},
    }
    state = {
        "pages": [error_page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }
    result = await quality_gate_node(state, {"configurable": {}})
    assert "/wiki/broken-domain" in result.get("pages_to_heal", [])
    scores = result.get("quality_scores", {})
    assert scores.get("/wiki/broken-domain", {}).get("skipped_reason") == "agent_error"


@pytest.mark.asyncio
async def test_agent_error_pages_not_rehealed_after_one_cycle(monkeypatch):
    """agent_error pages should not re-enter pages_to_heal after one heal cycle."""
    def _fake_settings():
        wiki = type("W", (), {"quality_gate_levels": "L1", "heal_l2_threshold": 0.0})()
        return type("S", (), {"wiki": wiki})()

    monkeypatch.setattr("wiki.nodes.quality_gate.get_settings", _fake_settings)

    error_page = {
        "path": "/wiki/broken-domain",
        "title": "Broken Domain",
        "page_type": "topic",
        "content": "Error generating page",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0, "generation_mode": "agent_error"},
    }
    state = {
        "pages": [error_page],
        "heal_attempts": {},
        "heal_cycles": {"/wiki/broken-domain": 1},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }
    result = await quality_gate_node(state, {"configurable": {}})
    assert "/wiki/broken-domain" not in result.get("pages_to_heal", [])
