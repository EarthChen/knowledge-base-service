from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.agents.review_agent import QualityIssue, QualityVerdict


def _minimal_orchestrator_stub(**kwargs):
    """Build a concrete DocOrchestrator stub for unit-testing review hooks."""
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

    mock_agent = MagicMock()
    return StubOrch(agent=mock_agent, name="test", **kwargs)


@pytest.mark.asyncio
async def test_review_agent_integration_on_fail():
    """When ReviewAgent returns fail, orchestrator should trigger heal."""
    orch = _minimal_orchestrator_stub(enable_review_agent=True, review_block_on_fail=True)

    fail_verdict = QualityVerdict(
        status="fail",
        confidence=0.3,
        issues=[QualityIssue(category="naming", severity="error", description="Part N")],
        heal_instructions="Fix Part N naming",
    )

    mock_ra = AsyncMock()
    mock_ra.review = AsyncMock(return_value=fail_verdict)
    orch._review_agent = mock_ra

    result = await orch._run_review("# Part 1\nContent", {})
    assert result is not None
    assert result.status == "fail"
    assert result.heal_instructions is not None


@pytest.mark.asyncio
async def test_review_agent_pass_no_heal():
    """When ReviewAgent returns pass, no heal should be triggered."""
    orch = _minimal_orchestrator_stub(enable_review_agent=True)

    pass_verdict = QualityVerdict(status="pass", confidence=1.0, issues=[])

    mock_ra = AsyncMock()
    mock_ra.review = AsyncMock(return_value=pass_verdict)
    orch._review_agent = mock_ra

    result = await orch._run_review("# Good Content\nReal content here", {})
    assert result is not None
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_review_agent_disabled_skips():
    """When review agent is disabled, skip review."""
    orch = _minimal_orchestrator_stub(enable_review_agent=False)

    result = await orch._run_review("any content", {})
    assert result is None


def test_config_flags_default():
    """Config flags should default to disabled."""
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

    class MinimalOrch(DocOrchestrator):
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

    mock_agent = MagicMock()
    orch = MinimalOrch(agent=mock_agent, name="test")
    assert orch._enable_review_agent is False
    assert orch._review_block_on_fail is True
    assert orch._review_agent is None


@pytest.mark.asyncio
async def test_generate_review_fail_heals_and_reviews():
    """ReviewAgent fail triggers heal, re-review, and QUALITY_WARNING on persistent warn."""
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

    fail_verdict = QualityVerdict(
        status="fail",
        confidence=0.3,
        issues=[QualityIssue(category="naming", severity="error", description="Part N")],
        heal_instructions="Fix Part N naming",
    )
    warn_verdict = QualityVerdict(
        status="warn",
        confidence=0.8,
        issues=[QualityIssue(category="structure", severity="warning", description="Empty section")],
    )

    class ReviewOrch(DocOrchestrator):
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

    mock_agent = MagicMock()
    mock_memory = MagicMock()
    mock_memory.code_snippets = []
    mock_agent.create_memory = MagicMock(return_value=mock_memory)
    mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
    mock_agent.run_generation = AsyncMock(side_effect=["# Part 1\nBad", "# Fixed Content\nBody"])
    mock_agent.memory_to_prompt = MagicMock(return_value="")

    mock_ra = AsyncMock()
    mock_ra.review = AsyncMock(side_effect=[fail_verdict, warn_verdict])

    orch = ReviewOrch(
        agent=mock_agent,
        name="test",
        enable_review_agent=True,
        review_block_on_fail=True,
    )
    orch._review_agent = mock_ra

    result = await orch.generate(module_names=["M"], baseline_context="ctx")

    assert mock_ra.review.call_count == 2
    assert mock_agent.run_generation.call_count == 2  # write + heal
    assert "QUALITY_WARNING" in result[0].get("quality_flags", [])


@pytest.mark.asyncio
async def test_generate_review_warn_appends_quality_warning():
    """ReviewAgent warn appends QUALITY_WARNING without heal."""
    from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

    warn_verdict = QualityVerdict(
        status="warn",
        confidence=0.8,
        issues=[QualityIssue(category="structure", severity="warning", description="Empty section")],
    )

    class ReviewOrch(DocOrchestrator):
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

    mock_agent = MagicMock()
    mock_memory = MagicMock()
    mock_memory.code_snippets = []
    mock_agent.create_memory = MagicMock(return_value=mock_memory)
    mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
    mock_agent.run_generation = AsyncMock(return_value="# Good\nContent")
    mock_agent.memory_to_prompt = MagicMock(return_value="")

    mock_ra = AsyncMock()
    mock_ra.review = AsyncMock(return_value=warn_verdict)

    orch = ReviewOrch(
        agent=mock_agent,
        name="test",
        enable_review_agent=True,
    )
    orch._review_agent = mock_ra

    result = await orch.generate(module_names=["M"], baseline_context="ctx")

    assert mock_agent.run_generation.call_count == 1  # write only, no heal
    assert result[0]["quality_flags"] == ["QUALITY_WARNING"]
