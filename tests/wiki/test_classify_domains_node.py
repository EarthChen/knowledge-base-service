from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import classify_domains_node


@pytest.mark.asyncio
async def test_classify_domains_returns_domain_mapping():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"payment": [["repo-1", "PaymentService"]], "user": [["repo-1", "UserService"]]}')

    state = {
        "business_id": "test-biz",
        "repositories": ["repo-1"],
        "config": {},
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService", "annotations": ["@Service"], "methods_count": 10, "start_line": 0, "end_line": 200}},
                {"uid": "Module::UserService:0", "label": "Module", "properties": {"name": "UserService", "annotations": ["@Service"], "methods_count": 8, "start_line": 0, "end_line": 150}},
            ]
        },
        "entity_roles": {
            "Module::PaymentService:0": "has_business_logic",
            "Module::UserService:0": "has_business_logic",
        },
        "llm": mock_llm,
    }
    result = await classify_domains_node(state)
    assert "domain_mapping" in result
    assert isinstance(result["domain_mapping"], dict)


@pytest.mark.asyncio
async def test_classify_domains_filters_non_biz():
    """Only HAS_BUSINESS_LOGIC entities should be classified."""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"payment": [["repo-1", "PaymentService"]]}')

    state = {
        "business_id": "test-biz",
        "repositories": ["repo-1"],
        "config": {},
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService", "annotations": ["@Service"], "methods_count": 10, "start_line": 0, "end_line": 200}},
                {"uid": "Module::UserDTO:0", "label": "Module", "properties": {"name": "UserDTO", "annotations": ["@Data"], "methods_count": 0, "start_line": 0, "end_line": 20}},
            ]
        },
        "entity_roles": {
            "Module::PaymentService:0": "has_business_logic",
            "Module::UserDTO:0": "data_model",
        },
        "llm": mock_llm,
    }
    result = await classify_domains_node(state)
    assert "domain_mapping" in result
