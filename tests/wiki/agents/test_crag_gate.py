from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _crag_orchestrator_stub(**kwargs):
    """Minimal concrete DocOrchestrator for CRAG coverage unit tests."""
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

    class StubOrch(DocOrchestrator):
        async def pre_fill(self, memory, module_names):
            pass

        async def evaluate(self, content, module_names):
            return QualityResult(
                coverage=1.0,
                citation_density=1.0,
                context_gap_count=0,
                uncovered_modules=[],
            )

        def is_acceptable(self, quality, iteration):
            return True

        def post_process(self, content, module_names, memory):
            return [{"content": content}]

    return StubOrch(agent=MagicMock(), name="test", **kwargs)


@pytest.mark.asyncio
async def test_crag_gate_passes_when_coverage_sufficient():
    """CRAG gate should pass when WorkingMemory covers all target modules."""
    orch = _crag_orchestrator_stub(enable_crag_gate=True)

    memory = MagicMock()
    memory.relevant_modules = ["module_a", "module_b", "module_c"]

    target_modules = ["module_a", "module_b"]
    result = orch._check_crag_coverage(memory, target_modules)
    assert result["pass"] is True
    assert result["coverage"] >= 1.0


@pytest.mark.asyncio
async def test_crag_gate_fails_when_coverage_insufficient():
    """CRAG gate should fail when WorkingMemory misses modules."""
    orch = _crag_orchestrator_stub(enable_crag_gate=True)

    memory = MagicMock()
    memory.relevant_modules = ["module_a"]

    target_modules = ["module_a", "module_b", "module_c"]
    result = orch._check_crag_coverage(memory, target_modules)
    assert result["pass"] is False
    assert result["coverage"] < 1.0
    assert "module_b" in result["missing"]
    assert "module_c" in result["missing"]


@pytest.mark.asyncio
async def test_crag_gate_disabled_skips():
    """When CRAG gate is disabled, it should always pass."""
    orch = _crag_orchestrator_stub(enable_crag_gate=False)

    memory = MagicMock()
    memory.relevant_modules = []

    result = orch._check_crag_coverage(memory, ["module_a"])
    assert result["pass"] is True


def test_crag_gate_empty_targets():
    """With no target modules, CRAG should pass."""
    orch = _crag_orchestrator_stub(enable_crag_gate=True)

    memory = MagicMock()
    memory.relevant_modules = []

    result = orch._check_crag_coverage(memory, [])
    assert result["pass"] is True


def test_crag_coverage_with_threshold():
    """CRAG should pass when coverage >= threshold (default 0.6)."""
    orch = _crag_orchestrator_stub(enable_crag_gate=True, crag_coverage_threshold=0.6)

    memory = MagicMock()
    memory.relevant_modules = ["a", "b", "c"]  # 3 of 4 = 0.75 >= 0.6

    result = orch._check_crag_coverage(memory, ["a", "b", "c", "d"])
    assert result["pass"] is True
    assert 0.6 <= result["coverage"] <= 1.0


@pytest.mark.asyncio
async def test_crag_fail_triggers_re_explore_and_updates_memory():
    """CRAG failure should run focused re-explore once and merge supplemental memory."""
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult
    from wiki.page_agent import WorkingMemory

    supplemental = WorkingMemory()
    supplemental.relevant_modules = {"module_b", "module_c"}
    supplemental.search_findings.append("found module_b flow")

    memory = WorkingMemory()
    memory.relevant_modules = {"module_a"}

    agent = MagicMock()
    agent.create_memory.return_value = memory
    agent.run_generation = AsyncMock(return_value="# Doc\n\nContent.")
    agent.memory_to_prompt.return_value = ""

    class StubOrch(DocOrchestrator):
        async def pre_fill(self, memory, module_names):
            pass

        async def evaluate(self, content, module_names):
            return QualityResult(
                coverage=1.0,
                citation_density=1.0,
                context_gap_count=0,
                uncovered_modules=[],
            )

        def is_acceptable(self, quality, iteration):
            return True

        def post_process(self, content, module_names, memory):
            return [{"content": content, "title": "test"}]

    orch = StubOrch(
        agent=agent,
        name="test",
        enable_crag_gate=True,
        crag_coverage_threshold=0.6,
        crag_max_re_explore=1,
    )
    agent.run_tool_loop = AsyncMock(side_effect=[memory, supplemental])

    pages = await orch.generate(
        ["module_a", "module_b", "module_c"],
        "baseline context",
    )

    assert agent.run_tool_loop.await_count == 2
    assert "module_b" in memory.relevant_modules
    assert "module_c" in memory.relevant_modules
    assert memory.search_findings
    assert "CRAG_WARNING" not in pages[0].get("quality_flags", [])


@pytest.mark.asyncio
async def test_crag_still_insufficient_sets_warning_flag():
    """When re-explore does not recover coverage, pages get CRAG_WARNING."""
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult
    from wiki.page_agent import WorkingMemory

    memory = WorkingMemory()
    memory.relevant_modules = {"module_a"}
    still_sparse = WorkingMemory()
    still_sparse.relevant_modules = {"module_a"}

    agent = MagicMock()
    agent.create_memory.return_value = memory
    agent.run_tool_loop = AsyncMock(side_effect=[memory, still_sparse])
    agent.run_generation = AsyncMock(return_value="# Doc\n\nContent.")
    agent.memory_to_prompt.return_value = ""

    class StubOrch(DocOrchestrator):
        async def pre_fill(self, memory, module_names):
            pass

        async def evaluate(self, content, module_names):
            return QualityResult(
                coverage=1.0,
                citation_density=1.0,
                context_gap_count=0,
                uncovered_modules=[],
            )

        def is_acceptable(self, quality, iteration):
            return True

        def post_process(self, content, module_names, memory):
            return [{"content": content}]

    orch = StubOrch(
        agent=agent,
        name="test",
        enable_crag_gate=True,
        crag_coverage_threshold=0.6,
        crag_max_re_explore=1,
    )

    pages = await orch.generate(
        ["module_a", "module_b", "module_c"],
        "baseline",
    )

    assert "CRAG_WARNING" in pages[0].get("quality_flags", [])
