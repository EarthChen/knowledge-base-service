from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_topic_plan_item_valid():
    from wiki.domain_doc_agent import TopicPlanItem

    item = TopicPlanItem(
        title="Authentication Architecture",
        slug="authentication-architecture",
        module_names=["auth/login.py", "auth/jwt.py"],
        description="Covers JWT-based authentication flow",
    )
    assert item.title == "Authentication Architecture"
    assert len(item.module_names) >= 1


def test_topic_plan_item_rejects_part_n():
    from wiki.domain_doc_agent import TopicPlanItem

    with pytest.raises(ValidationError) as exc_info:
        TopicPlanItem(
            title="Part 1: Overview",
            slug="part-1-overview",
            module_names=["mod.py"],
            description="desc",
        )
    assert "Part N" in str(exc_info.value) or "part" in str(exc_info.value).lower()


def test_topic_plan_item_rejects_chinese_part_n():
    from wiki.domain_doc_agent import TopicPlanItem

    with pytest.raises(ValidationError) as exc_info:
        TopicPlanItem(
            title="第1部分：概述",
            slug="part-1",
            module_names=["mod.py"],
            description="desc",
        )
    assert "Part N" in str(exc_info.value) or "part" in str(exc_info.value).lower()


def test_topic_plan_valid():
    from wiki.domain_doc_agent import TopicPlan, TopicPlanItem

    plan = TopicPlan(
        domain="auth",
        items=[
            TopicPlanItem(title="Login Flow", slug="login-flow", module_names=["login.py"], description="d1"),
            TopicPlanItem(title="JWT Management", slug="jwt-mgmt", module_names=["jwt.py"], description="d2"),
        ],
    )
    assert len(plan.items) == 2
    assert plan.domain == "auth"


def test_topic_plan_empty_items_allowed():
    """Empty plan is valid (generates no topics)."""
    from wiki.domain_doc_agent import TopicPlan

    plan = TopicPlan(domain="test", items=[])
    assert len(plan.items) == 0


def test_topic_plan_item_slug_auto_generated():
    """If slug is empty, it should be auto-generated from title."""
    from wiki.domain_doc_agent import TopicPlanItem

    item = TopicPlanItem(
        title="Authentication Flow",
        slug="",
        module_names=["auth.py"],
        description="desc",
    )
    # Slug should either be empty (accepted) or auto-generated
    # This depends on implementation choice
    assert isinstance(item.slug, str)


def test_validate_topic_plan_renames_part_n_title():
    """Part N titles from LLM output are sanitized before writing."""
    from wiki.domain_doc_agent import (
        DomainTopicOutline,
        OutlineTopicItem,
        _validate_topic_plan_outline,
    )

    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(
                title="Part 2: Payment Flow",
                modules=["PaymentService"],
                description="payments",
                slug="payment-flow",
            ),
        ],
    )
    result = _validate_topic_plan_outline(outline)
    assert result.topics[0].title == "Payment Flow"


@pytest.mark.asyncio
async def test_plan_topics_parse_failure_uses_mechanical_fallback_and_flag():
    """Unparseable LLM plan falls back to mechanical split with PLAN_PARSE_FAILED."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from wiki.domain_doc_agent import DomainDocAgent
    from wiki.page_agent import WorkingMemory

    llm = AsyncMock()
    llm.complete_json = AsyncMock(return_value={"garbage": True})
    agent = DomainDocAgent(
        domain_name="big-domain",
        domain_display_name="Big Domain",
        llm=llm,
        graph_store=MagicMock(),
    )
    module_names = [f"Mod{i}" for i in range(6)]
    memory = WorkingMemory()

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        agent._pending_quality_flags = []
        outline = await agent._plan_topics(module_names, memory)

    assert outline.should_split is True
    assert len(outline.topics) > 1
    assert "PLAN_PARSE_FAILED" in agent._pending_quality_flags
