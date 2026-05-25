"""Tests for quality evaluation on topic-split path in DomainDocAgent."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import AppWikiFlags
from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan
from wiki.quality_report import QualityReport


def _split_outline() -> DomainTopicOutline:
    return DomainTopicOutline(
        should_split=True,
        topics=[
            TopicPlan(title="Topic A", modules=["ModA"], description="desc A"),
            TopicPlan(title="Topic B", modules=["ModB"], description="desc B"),
        ],
    )


def _topic_pages() -> list[dict]:
    return [
        {
            "page_type": "domain_overview",
            "title": "Test Domain",
            "path": "/__domains__/test/_overview",
            "content": "Overview content.",
            "metadata": {},
        },
        {
            "page_type": "topic",
            "title": "Topic A",
            "path": "/__domains__/test/topic-a/_topic",
            "content": "Sparse content about ModA only.",
            "metadata": {},
        },
        {
            "page_type": "topic",
            "title": "Topic B",
            "path": "/__domains__/test/topic-b/_topic",
            "content": "Good coverage ModA and ModB with citations.",
            "metadata": {},
        },
    ]


def _make_agent() -> DomainDocAgent:
    agent = DomainDocAgent(
        domain_name="test-domain",
        llm=MagicMock(),
        graph_store=MagicMock(),
    )
    agent._page_agent = AsyncMock()
    agent._page_agent.explore = AsyncMock()
    agent._page_agent.write = AsyncMock()
    agent._pre_fill_snippets = AsyncMock()
    agent._plan_topics = AsyncMock(return_value=_split_outline())
    agent._write_with_outline = AsyncMock(return_value=_topic_pages())
    return agent


def _wiki_cfg(**overrides: object) -> MagicMock:
    defaults = {
        "topic_split_quality_check": True,
        "domain_agent_early_exit_quality": 0.6,
        "domain_agent_early_exit_min_chars": 500,
        "domain_agent_timeout_sec": 900,
        "use_orchestrator_template": False,
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for key, value in defaults.items():
        setattr(cfg, key, value)
    return cfg


@pytest.mark.asyncio
async def test_topic_split_low_quality_evaluates_and_re_explores() -> None:
    """Low-quality topic pages trigger evaluate_quality and a focused re-explore."""
    agent = _make_agent()
    low = QualityReport(
        coverage=0.3,
        citation_density=0.1,
        context_gap_count=2,
        uncovered_modules=["ModB", "ModC"],
        implementation_depth=0.2,
    )
    high = QualityReport(
        coverage=0.9,
        citation_density=0.5,
        context_gap_count=0,
        uncovered_modules=[],
        implementation_depth=0.8,
    )

    wiki_cfg = _wiki_cfg()
    loop_time_values = iter([0, 0, 820, 831, 831, 831])

    with (
        patch("wiki.domain_doc_agent.evaluate_quality", side_effect=[high, low, high]) as mock_eval,
        patch("core.config.get_settings") as mock_settings,
        patch("wiki.domain_doc_agent.log") as mock_log,
    ):
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=lambda: next(loop_time_values, 885))

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            pages = await agent.generate_with_iterations(
                module_names=["ModA", "ModB"],
                baseline_context="baseline",
            )

    assert len(pages) == 3
    assert mock_eval.call_count == 3
    assert agent._page_agent.explore.call_count == 2
    re_explore_call = agent._page_agent.explore.call_args_list[1]
    assert re_explore_call.kwargs["module_names"] == ["ModB", "ModC"]
    mock_log.info.assert_any_call(
        "topic_split_low_quality",
        domain="test-domain",
        topic="Topic A",
        coverage=0.3,
    )


@pytest.mark.asyncio
async def test_topic_split_quality_check_disabled_skips_eval() -> None:
    """When topic_split_quality_check=False, skip quality evaluation entirely."""
    agent = _make_agent()
    wiki_cfg = _wiki_cfg(topic_split_quality_check=False)

    with (
        patch("wiki.domain_doc_agent.evaluate_quality") as mock_eval,
        patch("core.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )

    assert len(pages) == 3
    mock_eval.assert_not_called()
    assert agent._page_agent.explore.call_count == 1


@pytest.mark.asyncio
async def test_topic_split_high_quality_no_re_explore() -> None:
    """Acceptable quality on all topic pages does not trigger re-explore."""
    agent = _make_agent()
    good = QualityReport(
        coverage=0.85,
        citation_density=0.5,
        context_gap_count=0,
        uncovered_modules=[],
        implementation_depth=0.8,
    )
    wiki_cfg = _wiki_cfg()

    with (
        patch("wiki.domain_doc_agent.evaluate_quality", return_value=good) as mock_eval,
        patch("core.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )

    assert len(pages) == 3
    assert mock_eval.call_count == 3
    assert agent._page_agent.explore.call_count == 1


@pytest.mark.asyncio
async def test_topic_split_insufficient_budget_skips_re_explore() -> None:
    """When remaining budget is too low, skip the focused re-explore pass."""
    agent = _make_agent()
    low = QualityReport(
        coverage=0.3,
        citation_density=0.1,
        context_gap_count=2,
        uncovered_modules=["ModB"],
        implementation_depth=0.2,
    )
    high = QualityReport(
        coverage=0.9,
        citation_density=0.5,
        context_gap_count=0,
        uncovered_modules=[],
        implementation_depth=0.8,
    )
    wiki_cfg = _wiki_cfg()
    # remaining > 30 at quality-check entry, but <= 20 at re-explore check
    loop_time_values = iter([0, 0, 820, 851, 851, 851])

    with (
        patch("wiki.domain_doc_agent.evaluate_quality", side_effect=[low, high, high]) as mock_eval,
        patch("core.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        mock_loop = MagicMock()
        mock_loop.time = MagicMock(side_effect=lambda: next(loop_time_values, 885))

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            pages = await agent.generate_with_iterations(
                module_names=["ModA", "ModB"],
                baseline_context="baseline",
            )

    assert len(pages) == 3
    assert mock_eval.call_count == 3
    assert agent._page_agent.explore.call_count == 1


def test_topic_split_quality_check_config_default() -> None:
    """Config flag exists with opt-out default."""
    assert AppWikiFlags().topic_split_quality_check is True
