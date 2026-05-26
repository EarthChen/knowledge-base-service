"""Tests for compose_leaf_pages_node: biz_entities calls and data_models truncation logging."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wiki.pipeline_nodes import compose_leaf_pages_node


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.asyncio
async def test_compose_pages_biz_entities_include_calls_from_props() -> None:
    """TopicPageComposer receives biz_entities with calls from module properties (max 15)."""
    captured: dict = {}

    class FakeComposer:
        def __init__(self, llm: object, *, token_budget: int = 8000, **kwargs: object) -> None:
            self.llm = llm
            self.token_budget = token_budget

        async def compose_leaf_domain(self, domain: dict) -> list[dict]:
            captured["domain"] = domain
            return [
                {
                    "title": domain["name"],
                    "content": "# x",
                    "path": f"wiki/{domain['name']}",
                    "page_type": "topic",
                    "domain": domain["name"],
                }
            ]

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="")
    with patch("wiki.pipeline_nodes.TopicPageComposer", FakeComposer):
        state = {
            "domain_tree": [
                {"name": "orders", "modules": ["OrderSvc"], "children": []},
            ],
            "entity_roles": {
                "Module::OrderSvc:0": "has_business_logic",
            },
            "modules": {
                "r1": [
                    {
                        "uid": "Module::OrderSvc:0",
                        "label": "Module",
                        "properties": {
                            "name": "OrderSvc",
                            "business_summary": "Orders",
                            "methods": ["create"],
                            "calls": ["PaymentApi", "InventoryClient", "AuditLog"],
                        },
                    },
                ],
            },
        }
        await compose_leaf_pages_node(state, {"configurable": {"llm": mock_llm}})

    assert "domain" in captured
    biz = captured["domain"]["biz_entities"]
    assert len(biz) == 1
    assert biz[0]["calls"] == ["PaymentApi", "InventoryClient", "AuditLog"]


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.asyncio
async def test_compose_pages_logs_when_data_models_truncated() -> None:
    """More than 20 data_models for a domain triggers data_models_truncated log."""
    module_names = [f"Dto{i}" for i in range(21)]
    modules_list = [
        {
            "uid": f"Module::{name}:0",
            "label": "Module",
            "properties": {"name": name, "fields": ["id"]},
        }
        for name in module_names
    ]
    entity_roles = {f"Module::{name}:0": "data_model" for name in module_names}

    class FakeComposer:
        def __init__(self, llm: object, *, token_budget: int = 8000, **kwargs: object) -> None:
            pass

        async def compose_leaf_domain(self, domain: dict) -> list[dict]:
            return [
                {
                    "title": domain["name"],
                    "content": "# x",
                    "path": "wiki/m",
                    "page_type": "topic",
                    "domain": domain["name"],
                }
            ]

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="")
    with (
        patch("wiki.pipeline_nodes.TopicPageComposer", FakeComposer),
        patch("wiki.pipeline_nodes.log") as mock_log,
    ):
        state = {
            "domain_tree": [
                {"name": "bigdomain", "modules": module_names, "children": []},
            ],
            "entity_roles": entity_roles,
            "modules": {"r1": modules_list},
        }
        await compose_leaf_pages_node(state, {"configurable": {"llm": mock_llm}})

    mock_log.info.assert_any_call(
        "data_models_truncated",
        domain="bigdomain",
        total=21,
        kept=20,
    )
