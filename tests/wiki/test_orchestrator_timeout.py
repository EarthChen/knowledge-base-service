from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestExploreTimeout:
    @pytest.mark.asyncio
    async def test_explore_timeout_skips_topic_planning(self):
        """When explore times out, topic planning is skipped."""
        from wiki.agents.doc_orchestrator import DocOrchestrator

        class TestOrchestrator(DocOrchestrator):
            async def pre_fill(self, memory, module_names, **kwargs):
                pass

            async def evaluate(self, content, module_names):
                from wiki.agents.doc_orchestrator import QualityResult
                return QualityResult(coverage=0.9, citation_density=0.5, context_gap_count=0, uncovered_modules=[])

            def is_acceptable(self, quality, iteration):
                return True

            def post_process(self, content, module_names, memory):
                return [{"title": "test", "content": content}]

        mock_agent = MagicMock()
        mock_memory = MagicMock(
            code_snippets=[],
            topic_outline=None,
            discovered_call_chains=[],
            discovered_implementations=[],
            search_findings=[],
        )
        mock_agent.create_memory.return_value = mock_memory

        async def slow_explore(*args, **kwargs):
            await asyncio.sleep(10)
            return mock_memory

        mock_agent.run_tool_loop = AsyncMock(side_effect=slow_explore)
        mock_agent.run_generation = AsyncMock(return_value="# Generated Content\n\nSome text.")
        mock_agent.memory_to_prompt = MagicMock(return_value="")

        orchestrator = TestOrchestrator(
            agent=mock_agent,
            name="test",
            max_iterations=1,
        )

        # Mock plan_topics to track if called
        plan_topics_called = False
        original_plan_topics = orchestrator.plan_topics

        async def tracking_plan_topics(memory, module_names):
            nonlocal plan_topics_called
            plan_topics_called = True
            return await original_plan_topics(memory, module_names)

        orchestrator.plan_topics = tracking_plan_topics
        orchestrator.get_phase_timeout = lambda phase: 0.01 if phase == "explore" else None

        result = await orchestrator.generate(["m1", "m2"], "baseline")

        assert not plan_topics_called
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_explore_success_allows_topic_planning(self):
        """When explore succeeds, topic planning runs normally."""
        from wiki.agents.doc_orchestrator import DocOrchestrator

        class TestOrchestrator(DocOrchestrator):
            async def pre_fill(self, memory, module_names, **kwargs):
                pass

            async def evaluate(self, content, module_names):
                from wiki.agents.doc_orchestrator import QualityResult
                return QualityResult(coverage=0.9, citation_density=0.5, context_gap_count=0, uncovered_modules=[])

            def is_acceptable(self, quality, iteration):
                return True

            def post_process(self, content, module_names, memory):
                return [{"title": "test", "content": content}]

        mock_agent = MagicMock()
        mock_memory = MagicMock(code_snippets=[], topic_outline=None)
        mock_agent.create_memory.return_value = mock_memory
        mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
        mock_agent.run_generation = AsyncMock(return_value="# Content")
        mock_agent.memory_to_prompt = MagicMock(return_value="")

        orchestrator = TestOrchestrator(
            agent=mock_agent,
            name="test",
            max_iterations=1,
        )

        plan_topics_called = False

        async def tracking_plan_topics(memory, module_names):
            nonlocal plan_topics_called
            plan_topics_called = True
            return None

        orchestrator.plan_topics = tracking_plan_topics

        result = await orchestrator.generate(["m1", "m2"], "baseline")

        assert plan_topics_called
        assert len(result) > 0
