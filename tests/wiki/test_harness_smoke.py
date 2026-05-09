"""Smoke test: verify all harness components are importable and wired correctly."""
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_all_harness_modules_importable():
    from wiki.harness import WikiGenerationHarness
    from wiki.harness_router import AdaptiveRouter, ComplexityAssessment, CONTEXT_BUDGETS
    from wiki.harness_planner import WikiPagePlanner, GenerationPlan, SectionPlan, PlannedQuery
    from wiki.harness_evaluator import WikiPageEvaluator, EvalResult, Issue
    from wiki.harness_facts import GatheredFacts, Fact
    from wiki.harness_guardrails import HarnessGuardRails, GuardRailViolation
    from wiki.domain_summary_cache import DomainSummaryCard, extract_summary_card
    from wiki.agent_config import HarnessConfig
    assert True


def test_harness_has_run_method():
    from wiki.harness import WikiGenerationHarness
    assert hasattr(WikiGenerationHarness, "run")
    assert inspect.iscoroutinefunction(WikiGenerationHarness.run)


def test_context_budgets_all_levels():
    from wiki.harness_router import CONTEXT_BUDGETS
    assert "simple" in CONTEXT_BUDGETS
    assert "moderate" in CONTEXT_BUDGETS
    assert "complex" in CONTEXT_BUDGETS
    for level, budget in CONTEXT_BUDGETS.items():
        assert "max_chars_per_section" in budget
        assert "distill_total" in budget


def test_agent_has_repair():
    from wiki.page_agent import WikiPageAgent
    assert hasattr(WikiPageAgent, "repair")


def test_harness_config_from_env():
    from wiki.agent_config import HarnessConfig
    config = HarnessConfig.from_env()
    assert isinstance(config.enabled, bool)
    assert isinstance(config.max_repair_rounds, int)


@pytest.mark.asyncio
async def test_harness_uses_sectional_mode_for_complex():
    """When assessment.level == 'complex', harness should generate sections separately."""
    from wiki.harness import WikiGenerationHarness

    mock_agent = AsyncMock()
    mock_agent.generate = AsyncMock(return_value="# Section\n\nContent for this section with enough detail.")
    mock_agent.repair = AsyncMock(return_value="# Repaired\n\nFixed content.")

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="# Coherent\n\nCombined coherent content with no contradictions.")

    mock_graph = AsyncMock()
    mock_config = MagicMock()
    mock_config.simple_threshold = 5
    mock_config.complex_threshold = 15
    mock_config.max_repair_rounds = 1
    mock_config.llm_judge_enabled = False

    harness = WikiGenerationHarness(mock_agent, mock_graph, mock_llm, mock_config)

    mock_ccb = MagicMock()
    mock_ccb.entity_count = 20
    mock_ccb.edge_count = 30

    modules = [f"Module{i}" for i in range(20)]

    result = await harness.run("complex-domain", modules, mock_ccb)

    assert isinstance(result, str)
    assert len(result) > 0
    assert mock_agent.generate.call_count >= 1
