from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan


@pytest.mark.asyncio
async def test_plan_topics_force_split_fallback_when_llm_declines():
    """Large domains get mechanical topic split when LLM returns should_split=False."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="large-domain",
        domain_display_name="Large Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = [f"Mod{i}" for i in range(12)]
    llm_declined = DomainTopicOutline(
        should_split=False,
        topics=[TopicPlan(title="All", modules=module_names, description="single topic")],
    )
    agent._plan_topics = AsyncMock(return_value=llm_declined)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.topic_force_split_threshold = 10
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(MagicMock(), module_names)

    assert result is not None
    assert len(result) > 1
    assert agent._topic_split_done is True
    assert agent._topic_outline is not None
    assert agent._topic_outline.should_split is True

    module_counts = sorted(len(t.modules) for t in result)
    assert sum(module_counts) == len(module_names)
    assert len(module_counts) >= 2
    assert module_counts == [3, 3, 3, 3]


@pytest.mark.asyncio
async def test_plan_topics_force_split_at_default_threshold_six():
    """Domains with 8 modules force-split when default threshold is 6."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="mid-domain",
        domain_display_name="Mid Domain",
        llm=llm,
        graph_store=MagicMock(),
    )

    module_names = [f"Mod{i}" for i in range(8)]
    llm_declined = DomainTopicOutline(
        should_split=False,
        topics=[TopicPlan(title="All", modules=module_names, description="single topic")],
    )
    agent._plan_topics = AsyncMock(return_value=llm_declined)

    with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
        mock_settings.return_value.wiki.enable_topic_pages = True
        mock_settings.return_value.wiki.topic_force_split_threshold = 6
        mock_settings.return_value.wiki.max_topics_per_domain = 4
        mock_settings.return_value.wiki.plan_topics_min_modules = 3
        result = await agent.plan_topics(MagicMock(), module_names)

    assert result is not None
    assert len(result) > 1
    assert agent._topic_split_done is True
    module_counts = sorted(len(t.modules) for t in result)
    assert sum(module_counts) == len(module_names)
    assert len(module_counts) >= 2
