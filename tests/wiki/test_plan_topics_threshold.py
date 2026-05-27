from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan
from wiki.page_agent import WorkingMemory


@pytest.mark.asyncio
async def test_plan_topics_allows_3_modules():
    """A domain with 3 modules should attempt LLM planning (not blocked by hard gate)."""
    llm = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value={
            "should_split": True,
            "topics": [
                {"title": "Topic A", "modules": ["ModA"], "description": "a"},
                {"title": "Topic B", "modules": ["ModB", "ModC"], "description": "b"},
            ],
        }
    )
    agent = DomainDocAgent(
        domain_name="three-modules",
        domain_display_name="Three Modules",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB", "ModC"]
    memory = WorkingMemory()

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        outline = await agent._plan_topics(module_names, memory)

    llm.complete_json.assert_awaited_once()
    assert outline.should_split is True
    assert len(outline.topics) == 2


@pytest.mark.asyncio
async def test_plan_topics_blocks_2_or_fewer_modules():
    """A domain with ≤2 modules should return no-split outline without LLM."""
    llm = AsyncMock()
    llm.complete_json = AsyncMock()
    agent = DomainDocAgent(
        domain_name="tiny-domain",
        domain_display_name="Tiny Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB"]
    memory = WorkingMemory()

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        outline = await agent._plan_topics(module_names, memory)

    llm.complete_json.assert_not_called()
    assert outline.should_split is False
    assert len(outline.topics) == 1
    assert set(outline.topics[0].modules) == {"ModA", "ModB"}


@pytest.mark.asyncio
async def test_plan_topics_trigger_with_3_modules():
    """plan_topics() with 3 modules should set should_plan=True and call _plan_topics."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="three-modules",
        domain_display_name="Three Modules",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB", "ModC"]
    memory = MagicMock()
    memory.final_overview = ""

    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            TopicPlan(title="Topic A", modules=["ModA"], description="a"),
            TopicPlan(title="Topic B", modules=["ModB", "ModC"], description="b"),
        ],
    )
    agent._plan_topics = AsyncMock(return_value=outline)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.min_overview_len_for_topics = 4000
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(memory, module_names)

    assert result is not None
    agent._plan_topics.assert_awaited_once_with(module_names, memory)


@pytest.mark.asyncio
async def test_plan_topics_trigger_with_long_overview():
    """plan_topics() with a long overview should trigger regardless of module count."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="rich-overview",
        domain_display_name="Rich Overview",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB"]
    memory = MagicMock()
    memory.final_overview = "x" * 5000

    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            TopicPlan(title="Topic A", modules=["ModA"], description="a"),
            TopicPlan(title="Topic B", modules=["ModB"], description="b"),
        ],
    )
    agent._plan_topics = AsyncMock(return_value=outline)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.min_overview_len_for_topics = 4000
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(memory, module_names)

    assert result is not None
    agent._plan_topics.assert_awaited_once_with(module_names, memory)
