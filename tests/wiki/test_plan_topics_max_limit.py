from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan


@pytest.mark.asyncio
async def test_plan_topics_max_limit():
    """When outline has 6 topics, truncate to max_topics_per_domain (default 4)."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="large-domain",
        domain_display_name="Large Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = [f"Mod{i}" for i in range(12)]
    memory = MagicMock()
    memory.final_overview = ""

    topics = [TopicPlan(title=f"Topic {i}", modules=[f"Mod{i}"], description=f"desc {i}") for i in range(6)]
    outline = DomainTopicOutline(should_split=True, topics=topics)
    agent._plan_topics = AsyncMock(return_value=outline)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.min_overview_len_for_topics = 4000
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(memory, module_names)

    assert result is not None
    assert len(result) == 4
    assert [t.title for t in result] == ["Topic 0", "Topic 1", "Topic 2", "Topic 3"]
    assert agent._topic_outline is not None
    assert len(agent._topic_outline.topics) == 4


@pytest.mark.asyncio
async def test_plan_topics_max_limit_force_split_path():
    """Force-split fallback also truncates topics to max_topics_per_domain."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="large-domain",
        domain_display_name="Large Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = [f"Mod{i}" for i in range(30)]
    llm_declined = DomainTopicOutline(
        should_split=False,
        topics=[TopicPlan(title="All", modules=module_names, description="single topic")],
    )
    agent._plan_topics = AsyncMock(return_value=llm_declined)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.min_overview_len_for_topics = 4000
        mock_settings.return_value.wiki.topic_force_split_threshold = 6
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(MagicMock(), module_names)

    assert result is not None
    assert len(result) == 4
    assert len(agent._topic_outline.topics) == 4
