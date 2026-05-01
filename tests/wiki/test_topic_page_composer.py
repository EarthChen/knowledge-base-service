from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock

from wiki.topic_page_composer import TopicPageComposer


def _wiki_json(content: str, summary: str = "Short exec summary for tests.") -> str:
    return json.dumps({"executive_summary": summary, "content": content}, ensure_ascii=False)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_wiki_json(
        "# Payment Service\n\n## 业务概述\nPayment handling.\n\n"
        "## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: call\n```\n\n"
        "## 核心服务详情\n### PaymentService\nHandles payments.\n\n"
        "## 数据模型\n| 类名 | 类型 | 字段 |\n|---|---|---|\n| PayDTO | DTO | id, amount |\n\n"
        "## 关联主题\n- [[用户系统]]",
        summary="Payment domain handles transactions and refunds.",
    ))
    return llm


@pytest.mark.asyncio
async def test_simple_domain_single_page(mock_llm):
    """Domain with ≤5 BIZ entities generates 1 page."""
    composer = TopicPageComposer(mock_llm, token_budget=8000)
    domain = {
        "name": "payment",
        "parent": "root",
        "biz_entities": [
            {"uid": "Module::PaymentService:0", "name": "PaymentService", "summary": "Handles payments", "methods": ["pay", "refund"], "calls": ["UserService"]},
        ],
        "data_models": [
            {"uid": "Module::PayDTO:0", "name": "PayDTO", "fields": ["id", "amount"]},
        ],
        "sibling_summaries": [{"name": "user", "description": "User management"}],
    }
    pages = await composer.compose_leaf_domain(domain)
    assert len(pages) == 1
    assert "payment" in pages[0]["title"].lower() or "Payment" in pages[0]["title"]
    assert pages[0]["content"]
    assert pages[0]["page_type"] == "topic"
    assert pages[0].get("metadata", {}).get("executive_summary")


@pytest.mark.asyncio
async def test_complex_domain_multiple_pages(mock_llm):
    """Domain with >5 BIZ entities generates overview + sub-pages."""
    composer = TopicPageComposer(mock_llm, token_budget=8000)
    domain = {
        "name": "messaging",
        "parent": "communication",
        "biz_entities": [
            {"uid": f"Module::Svc{i}:0", "name": f"Svc{i}", "summary": f"Service {i}", "methods": [f"m{j}" for j in range(3)], "calls": []}
            for i in range(8)
        ],
        "data_models": [],
        "sibling_summaries": [],
    }
    pages = await composer.compose_leaf_domain(domain)
    assert len(pages) >= 2
    assert any(p["page_type"] == "domain_overview" for p in pages)


@pytest.mark.asyncio
async def test_very_complex_domain_grouped(mock_llm):
    """Domain with >15 BIZ entities uses LLM grouping first."""
    mock_llm.generate = AsyncMock(side_effect=[
        '[{"name": "group-a", "entities": ["Svc0","Svc1","Svc2","Svc3","Svc4"]}, {"name": "group-b", "entities": ["Svc5","Svc6","Svc7","Svc8","Svc9","Svc10","Svc11","Svc12","Svc13","Svc14","Svc15"]}]',
        _wiki_json("# messaging overview\n\n## 域概览\nOverview content.", "Messaging domain overview."),
        _wiki_json("# group-a content\n\nSub-page A.", "Group A slice."),
        _wiki_json("# group-b content\n\nSub-page B.", "Group B slice."),
    ])
    composer = TopicPageComposer(mock_llm, token_budget=8000)
    domain = {
        "name": "messaging",
        "parent": "communication",
        "biz_entities": [
            {"uid": f"Module::Svc{i}:0", "name": f"Svc{i}", "summary": f"Service {i}", "methods": ["m1", "m2", "m3"], "calls": []}
            for i in range(16)
        ],
        "data_models": [],
        "sibling_summaries": [],
    }
    pages = await composer.compose_leaf_domain(domain)
    assert len(pages) >= 3


def test_data_model_inline_format():
    """DATA_MODEL entities should be formatted as inline tables."""
    result = TopicPageComposer.format_data_model_table([
        {"name": "UserDTO", "type": "DTO", "fields": ["id", "name", "avatar"]},
        {"name": "StatusEnum", "type": "Enum", "fields": ["ONLINE", "OFFLINE"]},
    ])
    assert "UserDTO" in result
    assert "StatusEnum" in result
    assert "|" in result
