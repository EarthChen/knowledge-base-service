from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import synthesize_overviews_node, create_links_node


@pytest.mark.asyncio
async def test_synthesize_overviews_creates_system_overview():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="# System Overview\n\n## 系统概览\nThis system handles payment and messaging.\n\n## 架构图\n```mermaid\ngraph TD\nA-->B\n```")

    state = {
        "domain_tree": [
            {"name": "payment", "modules": ["PaymentService"], "children": []},
            {"name": "messaging", "modules": ["MsgService"], "children": []},
        ],
        "pages": [
            {"title": "payment", "content": "Payment wiki content here...", "path": "wiki/payment", "page_type": "topic", "domain": "payment"},
            {"title": "messaging", "content": "Messaging wiki content here...", "path": "wiki/messaging", "page_type": "topic", "domain": "messaging"},
        ],
    }
    result = await synthesize_overviews_node(state, {"configurable": {"llm": mock_llm}})
    assert "pages" in result
    assert any(p.get("page_type") == "system_overview" for p in result["pages"])
    assert "system_overview_uid" in result


@pytest.mark.asyncio
async def test_synthesize_overviews_no_llm():
    state = {
        "domain_tree": [{"name": "payment", "modules": [], "children": []}],
        "pages": [],
    }
    result = await synthesize_overviews_node(state, {"configurable": {"llm": None}})
    assert result == {}


@pytest.mark.asyncio
async def test_create_links_processes_wikilinks():
    state = {
        "pages": [
            {"title": "payment", "content": "Uses [[messaging]] for notifications", "path": "wiki/payment"},
            {"title": "messaging", "content": "Called by payment", "path": "wiki/messaging"},
        ],
        "entity_roles": {},
        "modules": {},
    }
    result = await create_links_node(state)
    assert result["resolved_links"] == {
        "wiki/payment": [{"from_text": "messaging", "target_path": "wiki/messaging"}],
    }
    assert len(state["pages"]) == 2
