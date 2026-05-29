from __future__ import annotations

from unittest.mock import MagicMock

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
