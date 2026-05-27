from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan


@pytest.mark.asyncio
async def test_plan_topics_overview_len_trigger():
    """Small module count but rich overview triggers topic planning."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="rich-overview",
        domain_display_name="Rich Overview",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB", "ModC"]
    memory = MagicMock()
    memory.final_overview = "x" * 5000

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
async def test_plan_topics_skip_small_domain():
    """≤2 modules and short overview skips topic planning."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="small-domain",
        domain_display_name="Small Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = ["ModA", "ModB"]
    memory = MagicMock()
    memory.final_overview = "x" * 2000

    agent._plan_topics = AsyncMock()

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.min_overview_len_for_topics = 4000
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(memory, module_names)

    assert result is None
    agent._plan_topics.assert_not_awaited()
