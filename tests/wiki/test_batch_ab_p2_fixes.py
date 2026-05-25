"""Batch AB — Pipeline Quality P2 fixes (module coverage, explore limits)."""

from __future__ import annotations

from unittest.mock import MagicMock

from wiki.domain_doc_agent import DomainDocAgent
from wiki.quality_report import evaluate_quality


def test_module_coverage_word_boundary_no_substring_false_positive() -> None:
    """Short name 'Api' must not match content that only mentions 'ApiGateway'."""
    content = "## Overview\nThe ApiGateway handles incoming HTTP requests."
    report = evaluate_quality(content, ["Api"])
    assert report.coverage == 0.0
    assert report.uncovered_modules == ["Api"]


def test_module_coverage_word_boundary_positive_match() -> None:
    """Standalone module name should count as covered."""
    content = "## Overview\nThe Api layer routes requests to downstream services."
    report = evaluate_quality(content, ["Api"])
    assert report.coverage == 1.0
    assert report.uncovered_modules == []


def test_module_coverage_still_matches_full_module_name() -> None:
    content = "## Overview\nUserService coordinates user lifecycle operations."
    report = evaluate_quality(content, ["UserService"])
    assert report.coverage == 1.0


def test_domain_agent_explore_limits_are_reasonable() -> None:
    """Default explore limits should be bounded (not 20 rounds × 100 tool calls)."""
    agent = DomainDocAgent("payments", MagicMock(), MagicMock())
    assert agent._page_agent.max_rounds <= 10
    assert agent._page_agent.max_tool_calls <= 50
