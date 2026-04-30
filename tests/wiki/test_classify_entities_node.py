"""Unit tests for classify_entities_node edge_count derivation."""
from __future__ import annotations

import pytest

from wiki.entity_role_classifier import WikiEntityRole
from wiki.pipeline_nodes import classify_entities_node


@pytest.mark.asyncio
async def test_classify_entities_uses_calls_for_edge_count() -> None:
    """dim_graph uses len(calls)+len(imports); high edge count pushes score to HAS_BUSINESS_LOGIC."""
    state = {
        "modules": {
            "repo": [
                {
                    "uid": "Module::A:0",
                    "label": "Module",
                    "properties": {
                        "name": "A",
                        "annotations": ["@Component"],
                        "methods_count": 3,
                        "start_line": 0,
                        "end_line": 50,
                        "calls": [
                            "B", "C", "D", "E", "F", "G", "H", "I", "J", "K",
                            "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U",
                        ],
                    },
                },
            ],
        },
    }
    result = await classify_entities_node(state)
    assert result["entity_roles"]["Module::A:0"] == WikiEntityRole.HAS_BUSINESS_LOGIC
