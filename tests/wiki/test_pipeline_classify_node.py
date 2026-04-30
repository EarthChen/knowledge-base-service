# tests/wiki/test_pipeline_classify_node.py
from __future__ import annotations

import pytest

from wiki.entity_role_classifier import WikiEntityRole
from wiki.pipeline_nodes import classify_entities_node


@pytest.mark.asyncio
async def test_classify_entities_returns_roles():
    """classify_entities_node should populate entity_roles in state."""
    state = {
        "business_id": "test",
        "repositories": ["test-repo"],
        "config": {},
        "modules": {
            "test-repo": [
                {
                    "uid": "Module::PaymentService:0",
                    "label": "Module",
                    "properties": {
                        "name": "PaymentService",
                        "annotations": ["@Service"],
                        "methods_count": 10,
                        "start_line": 0,
                        "end_line": 300,
                        "semantic_roles": ["http_controller"],
                    },
                },
                {
                    "uid": "Module::UserDTO:0",
                    "label": "Module",
                    "properties": {
                        "name": "UserDTO",
                        "annotations": ["@Data"],
                        "methods_count": 0,
                        "start_line": 0,
                        "end_line": 20,
                    },
                },
            ]
        },
        "entity_roles": {},
        "role_stats": {},
    }
    result = await classify_entities_node(state)
    assert "Module::PaymentService:0" in result["entity_roles"]
    assert result["entity_roles"]["Module::PaymentService:0"] == WikiEntityRole.HAS_BUSINESS_LOGIC
    assert result["entity_roles"]["Module::UserDTO:0"] == WikiEntityRole.DATA_MODEL
    assert result["role_stats"]["has_business_logic"] >= 1
    assert result["role_stats"]["data_model"] >= 1
