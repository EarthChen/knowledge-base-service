from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_orchestrator(
    *,
    max_iterations: int = 4,
    coverage: float = 0.75,
    is_acceptable_fn=None,
):
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

    class TestOrchestrator(DocOrchestrator):
        async def pre_fill(self, memory, module_names):
            pass

        async def evaluate(self, content, module_names):
            return QualityResult(
                coverage=coverage,
                citation_density=0.1,
                context_gap_count=1,
                uncovered_modules=["ModA"],
            )

        def is_acceptable(self, quality, iteration):
            if is_acceptable_fn is not None:
                return is_acceptable_fn(self, quality, iteration)
            if quality.coverage >= 0.95:
                return True
            if iteration >= 3:
                if quality.coverage >= 0.7:
                    self._last_accept_was_forced = True
                return quality.coverage >= 0.7
            return False

        def post_process(self, content, module_names, memory):
            return [{"content": content, "path": "wiki/test"}]

    mock_agent = MagicMock()
    mock_memory = MagicMock()
    mock_memory.code_snippets = []
    mock_agent.create_memory = MagicMock(return_value=mock_memory)
    mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
    mock_agent.run_generation = AsyncMock(return_value="# Test Content")
    mock_agent.memory_to_prompt = MagicMock(return_value="memory text")

    return TestOrchestrator(agent=mock_agent, name="test-domain", max_iterations=max_iterations)


class TestDocOrchestratorQualityFlags:
    @pytest.mark.asyncio
    async def test_forced_accept_adds_quality_flag(self):
        """iteration>=3 with coverage=0.75 should add FORCED_ACCEPT."""
        orch = _make_orchestrator(max_iterations=4, coverage=0.75)
        result = await orch.generate(module_names=["ModA"], baseline_context="baseline")
        assert "FORCED_ACCEPT" in result[0].get("quality_flags", [])

    @pytest.mark.asyncio
    async def test_exhausted_iterations_adds_low_quality_flag(self):
        """max_iterations reached with coverage=0.5 should add FORCED_LOW_QUALITY."""
        orch = _make_orchestrator(max_iterations=4, coverage=0.5)
        result = await orch.generate(module_names=["ModA"], baseline_context="baseline")
        assert "FORCED_LOW_QUALITY" in result[0].get("quality_flags", [])
        assert "FORCED_ACCEPT" not in result[0].get("quality_flags", [])

    @pytest.mark.asyncio
    async def test_normal_accept_no_flag(self):
        """coverage=0.95 at iteration=0 should not add forced flags."""
        orch = _make_orchestrator(max_iterations=4, coverage=0.95)
        result = await orch.generate(module_names=["ModA"], baseline_context="baseline")
        flags = result[0].get("quality_flags", [])
        assert "FORCED_ACCEPT" not in flags
        assert "FORCED_LOW_QUALITY" not in flags


class TestQualityGateForcedLowQuality:
    @pytest.mark.asyncio
    async def test_quality_gate_routes_forced_low_quality_to_heal(self, monkeypatch):
        """Page with FORCED_LOW_QUALITY should always be routed to heal."""
        from wiki.nodes.quality_gate import quality_gate_node

        mock_eval = MagicMock()
        mock_eval.structural_check.return_value = MagicMock(overall=0.95, issues=[])
        mock_eval.bench_score.return_value = MagicMock(overall=0.9)
        monkeypatch.setattr("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval)
        monkeypatch.setattr(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        )

        long_content = (
            "## 概述\n\n"
            + ("这是一段足够长的中文内容。" * 80)
            + "\n\n## 核心逻辑\n\n"
            + ("这是第二部分的中文内容。" * 80)
            + "\n\n## 使用示例\n\n"
            + ("这是第三部分的中文内容。" * 40)
            + "\n\n```java\npublic class Example {}\n```\n"
        )
        state = {
            "pages": [
                {
                    "path": "wiki/good_page",
                    "title": "Good Page",
                    "content": long_content,
                    "page_type": "topic",
                    "diagrams": [],
                    "source_locations": [],
                    "metadata": {},
                    "quality_flags": ["FORCED_LOW_QUALITY"],
                }
            ],
            "config": {"quality_levels": ["L1"], "importance_tiers": {"wiki/good_page": "core"}},
            "heal_attempts": {},
            "heal_cycles": {},
            "_structural_check_cache": {},
            "modules": {},
        }

        result = await quality_gate_node(state, {"configurable": {}})
        assert "wiki/good_page" in result["pages_to_heal"]

        state["pages"][0]["quality_flags"] = []
        result_without_flag = await quality_gate_node(state, {"configurable": {}})
        assert "wiki/good_page" not in result_without_flag["pages_to_heal"]


class TestFinalizeForcedLowQuality:
    @pytest.mark.asyncio
    async def test_finalize_adds_banner_for_forced_low_quality(self):
        """Page with FORCED_LOW_QUALITY should get skeleton warning banner."""
        from wiki.nodes.finalize import finalize_node

        long_content = "## 概述\n\n" + ("这是一段足够长的中文内容。" * 200)
        state = {
            "pages": [
                {
                    "title": "Test",
                    "path": "/__domains__/test/_overview",
                    "page_type": "domain_overview",
                    "content": long_content,
                    "quality_flags": ["FORCED_LOW_QUALITY"],
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert page["content"].startswith("> ⚠️ 本域文档待完善，内容可能不完整。")
