"""Test heal_cycles vs heal_attempts separation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_quality_gate_uses_heal_cycles_not_attempts():
    """quality_gate should use heal_cycles (outer loop count) not heal_attempts (inner round count)."""
    page = {
        "path": "/wiki/test-page",
        "title": "Test Page",
        "page_type": "topic",
        "content": "short",  # will fail L1
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [page],
        "heal_attempts": {"/wiki/test-page": 5},  # inner rounds exhausted
        "heal_cycles": {"/wiki/test-page": 0},  # outer loop NOT yet run
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1"
        wiki_cfg.heal_l2_threshold = 0.0
        wiki_cfg.overview_min_content_chars = 2000
        wiki_cfg.topic_min_content_chars = 1000
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    # Page should be scheduled for heal because heal_cycles=0 < max_retries=2
    # even though heal_attempts=5
    assert "/wiki/test-page" in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_quality_gate_blocks_heal_after_cycles_exhausted():
    """quality_gate should NOT schedule heal when heal_cycles >= max_retries."""
    page = {
        "path": "/wiki/test-page",
        "title": "Test Page",
        "page_type": "topic",
        "content": "short",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [page],
        "heal_attempts": {"/wiki/test-page": 5},
        "heal_cycles": {"/wiki/test-page": 3},  # exhausted
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1"
        wiki_cfg.heal_l2_threshold = 0.0
        wiki_cfg.overview_min_content_chars = 2000
        wiki_cfg.topic_min_content_chars = 1000
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    assert "/wiki/test-page" not in result.get("pages_to_heal", [])
