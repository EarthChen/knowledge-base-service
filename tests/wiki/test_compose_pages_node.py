from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import compose_leaf_pages_node


@pytest.mark.asyncio
async def test_compose_pages_generates_topic_pages():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="# Payment\n\n## 业务概述\nPayment service.\n\n## 核心业务流程\nflow\n\n## 核心服务详情\n### PaymentService\nDetails.")

    state = {
        "business_id": "test",
        "domain_tree": [
            {"name": "payment", "modules": ["PaymentService"], "children": []},
        ],
        "entity_roles": {
            "Module::PaymentService:0": "has_business_logic",
            "Module::PayDTO:0": "data_model",
        },
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService", "annotations": ["@Service"], "methods_count": 5, "business_summary": "Handles payments", "start_line": 0, "end_line": 200}},
                {"uid": "Module::PayDTO:0", "label": "Module", "properties": {"name": "PayDTO", "annotations": ["@Data"], "methods_count": 0, "start_line": 0, "end_line": 20}},
            ]
        },
        "config": {},
    }
    result = await compose_leaf_pages_node(state, {"configurable": {"llm": mock_llm}})
    assert "pages" in result
    assert len(result["pages"]) >= 1
    assert "generated_topic_pages" in result


@pytest.mark.asyncio
async def test_compose_pages_empty_tree():
    state = {
        "domain_tree": [],
        "entity_roles": {},
        "modules": {},
        "config": {},
    }
    result = await compose_leaf_pages_node(state, {"configurable": {"llm": AsyncMock()}})
    assert result["pages"] == []
