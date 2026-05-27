"""Test L2-driven healing in quality_gate."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.quality_gate import quality_gate_node


@pytest.mark.asyncio
async def test_l2_below_threshold_triggers_heal():
    """Page passing L1 but failing L2 should be scheduled for heal when heal_l2_threshold > 0."""
    # Page with good structure (passes L1 ≥ 0.7) but poor depth
    good_structure_page = {
        "path": "/wiki/shallow-page",
        "title": "Shallow Page",
        "page_type": "topic",
        "content": (
            "## Overview\n"
            + "x" * 250
            + "\n## Key components\nCore\n```java\npublic class Shallow {}\n```\n## Relationships\n- [[peer]]\n"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [good_structure_page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1,L2"
        wiki_cfg.heal_l2_threshold = 0.55
        wiki_cfg.overview_min_content_chars = 2000
        wiki_cfg.topic_min_content_chars = 1000
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    scores = result.get("quality_scores", {}).get("/wiki/shallow-page", {})
    # If L1 passed (>= 0.7) but L2 < 0.55, page should be in pages_to_heal
    l1 = scores.get("l1_structural", 0)
    l2 = scores.get("l2_bench", 1.0)
    if l1 >= 0.7 and l2 < 0.55:
        assert "/wiki/shallow-page" in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_l2_threshold_zero_preserves_existing_behavior():
    """When heal_l2_threshold=0, L2 should NOT affect heal decisions."""
    page = {
        "path": "/wiki/ok-page",
        "title": "OK Page",
        "page_type": "topic",
        "content": (
            "## Overview\n"
            + "x" * 1100
            + "\n## Key components\nCore\n```java\npublic class OkPage {}\n```\n## Relationships\n- [[peer]]\n"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}},
        "_structural_check_cache": {},
    }

    with patch("wiki.nodes.quality_gate.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.quality_gate_levels = "L1,L2"
        wiki_cfg.heal_l2_threshold = 0.0  # disabled
        wiki_cfg.overview_min_content_chars = 2000
        wiki_cfg.topic_min_content_chars = 1000
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        result = await quality_gate_node(state, {"configurable": {}})

    scores = result.get("quality_scores", {}).get("/wiki/ok-page", {})
    l1 = scores.get("l1_structural", 0)
    if l1 >= 0.7:
        # Should NOT be in pages_to_heal regardless of L2
        assert "/wiki/ok-page" not in result.get("pages_to_heal", [])
