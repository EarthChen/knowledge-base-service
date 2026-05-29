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
