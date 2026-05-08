"""Smoke test: verify all harness components are importable and wired correctly."""
import inspect
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
