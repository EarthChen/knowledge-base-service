from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.page_agent import WorkingMemory
from wiki.domain_doc_agent import (
    DomainDocAgent,
    DomainTopicOutline,
    OutlineTopicItem,
    _maybe_split,
    _parse_topic_outline,
)


def test_working_memory_has_topic_outline():
    wm = WorkingMemory()
    assert wm.topic_outline is None


def test_working_memory_topic_outline_assignment():
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(title="任务系统", modules=["TaskService", "RewardHandler"], description="任务管理"),
            OutlineTopicItem(title="成员管理", modules=["MemberService"], description="成员管理"),
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
    """Domains with ≤2 modules skip the LLM call entirely."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="small-domain",
        llm=llm,
        graph_store=MagicMock(),
    )
    module_names = ["ModA", "ModB"]
    memory = WorkingMemory()
    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        outline = await agent._plan_topics(module_names, memory)
    assert outline.should_split is False
    assert len(outline.topics) == 1
    assert set(outline.topics[0].modules) == {"ModA", "ModB"}
    # LLM should NOT have been called
    if hasattr(llm, "complete_json"):
        llm.complete_json.assert_not_called()


@pytest.mark.asyncio
async def test_write_with_outline_produces_topic_pages():
    """When topic_outline has multiple topics, produce overview + topic pages."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## 业务概述\n家族任务系统概述...")
    agent = DomainDocAgent(
        domain_name="family-tasks",
        domain_display_name="家族任务",
        llm=llm,
        graph_store=MagicMock(),
    )
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(title="任务创建", modules=["TaskCreate"], description="创建任务"),
            OutlineTopicItem(title="任务奖励", modules=["RewardService"], description="奖励发放"),
        ],
    )
    memory = WorkingMemory()
    pages = await agent._write_with_outline(outline, "baseline context", memory, ["TaskCreate", "RewardService"])
    assert len(pages) >= 3  # 1 overview + 2 topics
    page_types = [p.get("page_type") for p in pages]
    assert "domain_overview" in page_types
    assert page_types.count("topic") == 2


@pytest.mark.asyncio
async def test_write_with_outline_single_topic_no_split():
    """When outline says should_split=False, produce single page."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="# Small Domain\n内容...")
    agent = DomainDocAgent(
        domain_name="small-domain",
        domain_display_name="小域",
        llm=llm,
        graph_store=MagicMock(),
    )
    outline = DomainTopicOutline(
        should_split=False,
        topics=[OutlineTopicItem(title="小域", modules=["A", "B"], description="all")],
    )
    memory = WorkingMemory()
    pages = await agent._write_with_outline(outline, "context", memory, ["A", "B"])
    assert len(pages) == 1
    assert pages[0]["page_type"] == "domain_overview"


def test_maybe_split_parent_has_overview_content():
    """Parent page must contain at least some overview content, not just links."""
    content = (
        "## Section A\nContent A paragraph.\n\n"
        "## Section B\nContent B paragraph.\n\n"
    )
    # Artificially exceed MAX_PAGE_TOKENS (5000 tokens = ~20000 chars)
    content = content * 200
    pages = _maybe_split(content, "test", "Test")
    parent = pages[0]
    assert parent["page_type"] == "domain_overview"
    assert len(parent["content"]) > 50
