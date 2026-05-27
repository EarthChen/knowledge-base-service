from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult


class _ConcreteOrchestrator(DocOrchestrator):
    """Minimal concrete subclass for testing orchestrator hooks."""

    async def pre_fill(self, memory, module_names):
        pass

    async def evaluate(self, content, module_names):
        return QualityResult(coverage=1.0, citation_density=1.0, context_gap_count=0, uncovered_modules=[])

    def is_acceptable(self, quality, iteration):
        return True

    def post_process(self, content, module_names, memory):
        return [{"title": "Single"}]


@pytest.fixture
def mock_outline():
    outline = MagicMock()
    outline.should_split = True
    outline.topics = [
        MagicMock(title="Topic A", modules=["ModA", "ModB"]),
        MagicMock(title="Topic B", modules=["ModC", "ModD"]),
    ]
    return outline


class TestOrchestratorWriteTopicsHook:
    @pytest.mark.asyncio
    async def test_write_topics_default_returns_none(self):
        """Default _write_topics hook returns None."""
        orch = _ConcreteOrchestrator(MagicMock(), name="test")
        result = await orch._write_topics(None, "", MagicMock(), [])
        assert result is None

    @pytest.mark.asyncio
    async def test_orchestrator_calls_write_topics_when_plan_exists(self):
        """When plan_topics returns topics, _write_topics is called and its result returned."""
        orch = _ConcreteOrchestrator(MagicMock(), name="test")
        orch._max_iterations = 1
        orch.iteration_history = []

        fake_pages = [{"title": "Overview", "page_type": "domain_overview"}]
        orch._write_topics = AsyncMock(return_value=fake_pages)
        orch.plan_topics = AsyncMock(return_value=["topic1", "topic2"])
        orch.get_phase_timeout = MagicMock(return_value=None)
        orch.pre_fill = AsyncMock()

        memory = MagicMock()
        memory.topic_outline = None
        orch._agent.create_memory = MagicMock(return_value=memory)
        orch._agent.run_tool_loop = AsyncMock(return_value=memory)

        result = await orch.generate(["ModA", "ModB"], "baseline")
        orch._write_topics.assert_awaited_once()
        assert result == fake_pages

    @pytest.mark.asyncio
    async def test_orchestrator_fallback_when_no_plan(self):
        """When plan_topics returns None, single-body write loop is used."""
        orch = _ConcreteOrchestrator(MagicMock(), name="test")
        orch._max_iterations = 1
        orch.iteration_history = []
        orch._write_system_prompt = "sys"
        orch._build_write_prompt = MagicMock(return_value="prompt")

        orch._write_topics = AsyncMock(return_value=None)
        orch.plan_topics = AsyncMock(return_value=None)
        orch.get_phase_timeout = MagicMock(return_value=None)
        orch.pre_fill = AsyncMock()
        orch._verify_code_blocks = AsyncMock(side_effect=lambda c, m: c)
        orch.evaluate = AsyncMock(return_value=MagicMock(uncovered_modules=[]))
        orch.run_guardrails = AsyncMock(return_value=None)
        orch.build_iteration_trace = MagicMock()
        orch.is_acceptable = MagicMock(return_value=True)
        orch.post_process = MagicMock(return_value=[{"title": "Single"}])

        memory = MagicMock()
        orch._agent.create_memory = MagicMock(return_value=memory)
        orch._agent.run_tool_loop = AsyncMock(return_value=memory)
        orch._agent.run_generation = AsyncMock(return_value="content")

        result = await orch.generate(["ModA"], "baseline")
        orch._agent.run_generation.assert_awaited_once()
        assert result == [{"title": "Single"}]


class TestDomainDocAgentWriteTopics:
    @pytest.mark.asyncio
    async def test_write_topics_calls_write_with_outline(self, mock_outline):
        """DomainDocAgent._write_topics calls _write_with_outline with stored outline."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._topic_outline = mock_outline
        agent._write_with_outline = AsyncMock(return_value=[
            {"title": "Overview", "page_type": "domain_overview"},
            {"title": "Topic A", "page_type": "topic"},
        ])

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = True
            mock_settings.return_value.wiki.topic_split_quality_check = False
            result = await agent._write_topics(
                mock_outline.topics, "baseline", MagicMock(), ["ModA", "ModB"]
            )

        assert result is not None
        assert len(result) == 2
        agent._write_with_outline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_topics_disabled_by_config(self, mock_outline):
        """When enable_topic_pages=False, returns None."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._topic_outline = mock_outline

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = False
            result = await agent._write_topics(
                mock_outline.topics, "baseline", MagicMock(), ["ModA"]
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_plan_topics_stores_outline(self):
        """plan_topics() stores full DomainTopicOutline in _topic_outline."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._topic_split_done = False

        outline = MagicMock()
        outline.should_split = True
        outline.topics = [MagicMock(), MagicMock(), MagicMock()]
        agent._plan_topics = AsyncMock(return_value=outline)

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = True
            mock_settings.return_value.wiki.min_overview_len_for_topics = 4000
            mock_settings.return_value.wiki.max_topics_per_domain = 4
            mock_settings.return_value.wiki.plan_topics_min_modules = 3
            result = await agent.plan_topics(MagicMock(), ["A", "B", "C", "D", "E", "F"])

        assert result is not None
        assert agent._topic_outline is outline
        assert agent._topic_split_done is True

    @pytest.mark.asyncio
    async def test_plan_topics_skipped_when_disabled(self):
        """plan_topics returns None immediately when enable_topic_pages=False."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent._page_agent = MagicMock()

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = False
            result = await agent.plan_topics(MagicMock(), ["a", "b", "c", "d", "e", "f"])
        assert result is None
