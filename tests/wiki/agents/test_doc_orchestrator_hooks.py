from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult


class ConcreteOrchestrator(DocOrchestrator):
    """Minimal concrete subclass for testing hook defaults."""

    async def pre_fill(self, memory, module_names):
        pass

    async def evaluate(self, content, module_names):
        return QualityResult(coverage=1.0, citation_density=1.0, context_gap_count=0, uncovered_modules=[])

    def is_acceptable(self, quality, iteration):
        return True

    def post_process(self, content, module_names, memory):
        return [{"title": "test", "content": content}]


def _make_orchestrator() -> ConcreteOrchestrator:
    agent = MagicMock()
    return ConcreteOrchestrator(agent=agent, name="test-domain")


class TestDocOrchestratorHookInterfaces:
    def test_has_plan_topics_hook(self):
        assert hasattr(DocOrchestrator, "plan_topics")

    def test_has_get_phase_timeout_hook(self):
        assert hasattr(DocOrchestrator, "get_phase_timeout")

    def test_has_run_guardrails_hook(self):
        assert hasattr(DocOrchestrator, "run_guardrails")

    def test_has_build_iteration_trace_hook(self):
        assert hasattr(DocOrchestrator, "build_iteration_trace")

    @pytest.mark.asyncio
    async def test_default_plan_topics_returns_none(self):
        orch = _make_orchestrator()
        result = await orch.plan_topics(MagicMock(), ["ModA"])
        assert result is None

    def test_default_get_phase_timeout_returns_none(self):
        orch = _make_orchestrator()
        assert orch.get_phase_timeout("explore") is None
        assert orch.get_phase_timeout("write") is None

    @pytest.mark.asyncio
    async def test_default_run_guardrails_returns_none(self):
        orch = _make_orchestrator()
        result = await orch.run_guardrails("content", 0, {})
        assert result is None

    def test_default_build_iteration_trace_returns_none(self):
        orch = _make_orchestrator()
        result = orch.build_iteration_trace(0, MagicMock())
        assert result is None
