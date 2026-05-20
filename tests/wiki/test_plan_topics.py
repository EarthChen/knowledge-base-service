from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.page_agent import WorkingMemory
from wiki.domain_doc_agent import (
    DomainDocAgent,
    DomainTopicOutline,
    TopicPlan,
    _parse_topic_outline,
)


def test_working_memory_has_topic_outline():
    wm = WorkingMemory()
    assert wm.topic_outline is None


def test_working_memory_topic_outline_assignment():
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            TopicPlan(title="任务系统", modules=["TaskService", "RewardHandler"], description="任务管理"),
            TopicPlan(title="成员管理", modules=["MemberService"], description="成员管理"),
        ],
    )
    wm = WorkingMemory()
    wm.topic_outline = outline
    assert wm.topic_outline.should_split is True
    assert len(wm.topic_outline.topics) == 2
    assert wm.topic_outline.topics[0].title == "任务系统"


def test_parse_topic_outline_valid_json():
    raw = '{"should_split": true, "topics": [{"title": "A", "modules": ["M1"], "description": "d1"}]}'
    outline = _parse_topic_outline(raw)
    assert outline is not None
    assert outline.should_split is True
    assert len(outline.topics) == 1
    assert outline.topics[0].title == "A"
    assert outline.topics[0].modules == ["M1"]


def test_parse_topic_outline_invalid_json():
    outline = _parse_topic_outline("not json at all")
    assert outline is None


def test_parse_topic_outline_missing_fields():
    raw = '{"should_split": true}'
    outline = _parse_topic_outline(raw)
    assert outline is None


def test_parse_topic_outline_small_domain_skip():
    raw = '{"should_split": false, "topics": [{"title": "All", "modules": ["A","B","C"], "description": "all"}]}'
    outline = _parse_topic_outline(raw)
    assert outline is not None
    assert outline.should_split is False


@pytest.mark.asyncio
async def test_plan_topics_small_domain_skips_llm():
    """Domains with ≤5 modules skip the LLM call entirely."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="small-domain",
        llm=llm,
        graph_store=MagicMock(),
    )
    module_names = ["ModA", "ModB", "ModC"]
    memory = WorkingMemory()
    outline = await agent._plan_topics(module_names, memory)
    assert outline.should_split is False
    assert len(outline.topics) == 1
    assert set(outline.topics[0].modules) == {"ModA", "ModB", "ModC"}
    # LLM should NOT have been called
    if hasattr(llm, "complete_json"):
        llm.complete_json.assert_not_called()
