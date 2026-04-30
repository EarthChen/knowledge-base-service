# tests/wiki/test_domain_planning_nodes.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import decompose_hierarchy_node, set_review_status_node


@pytest.mark.asyncio
async def test_decompose_hierarchy_builds_tree_without_llm():
    """Without LLM, should produce flat tree from domain_mapping."""
    state = {
        "business_id": "test",
        "domain_mapping": {
            "payment": [("repo-1", "PaymentService")],
            "user": [("repo-1", "UserService")],
        },
        "entity_roles": {},
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService"}},
                {"uid": "Module::UserService:0", "label": "Module", "properties": {"name": "UserService"}},
            ]
        },
    }
    result = await decompose_hierarchy_node(state)
    assert "domain_tree" in result
    assert isinstance(result["domain_tree"], list)
    assert len(result["domain_tree"]) == 2
    names = {d["name"] for d in result["domain_tree"]}
    assert "payment" in names
    assert "user" in names


@pytest.mark.asyncio
async def test_decompose_hierarchy_with_llm():
    """With LLM, should attempt hierarchical decomposition."""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='[{"name": "payment", "description": "Payment handling", "children": [], "modules": ["PaymentService"]}]')

    state = {
        "business_id": "test",
        "domain_mapping": {
            "payment": [("repo-1", "PaymentService")],
        },
        "entity_roles": {},
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService", "path": "/src/payment", "business_summary": "Handles payments"}},
            ]
        },
    }
    result = await decompose_hierarchy_node(state, {"configurable": {"llm": mock_llm}})
    assert "domain_tree" in result
    assert result["domain_tree"] is not None


@pytest.mark.asyncio
async def test_set_review_status_marks_domain_tree_pending_review():
    state = {
        "domain_tree": [{"name": "payment", "children": []}],
        "review_status": {},
    }
    result = await set_review_status_node(state)
    assert "review_status" in result
    assert result["review_status"].get("domain_tree") == "pending_review"
