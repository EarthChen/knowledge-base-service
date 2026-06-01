"""Test DomainDocAgent early exit on acceptable quality."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import AppWikiFlags
from wiki.domain_doc_agent import DomainDocAgent
from wiki.page_agent import WorkingMemory


def test_domain_agent_early_exit_quality_default() -> None:
    """Config field exists with expected default threshold."""
    assert AppWikiFlags().domain_agent_early_exit_quality == 0.6


def test_domain_agent_early_exit_quality_bounds() -> None:
    cfg = AppWikiFlags(domain_agent_early_exit_quality=0.85)
    assert cfg.domain_agent_early_exit_quality == 0.85


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.asyncio
async def test_agent_exits_early_on_acceptable_quality() -> None:
    """Agent should break iteration loop when coverage >= threshold."""
    mock_llm = MagicMock()
    mock_graph = MagicMock()

    agent = DomainDocAgent(
        domain_name="test-domain",
        llm=mock_llm,
        graph_store=mock_graph,
    )

    mock_memory = WorkingMemory()
    agent._page_agent = AsyncMock()
    agent._page_agent.explore = AsyncMock(return_value=mock_memory)
    agent._page_agent.write = AsyncMock(
        return_value="# test-domain\n\nModA and ModB content.\n\n" + ("detail " * 80),
    )

    mock_quality = MagicMock()
    mock_quality.coverage = 0.7
    mock_quality.citation_density = 0.5

    wiki_cfg = MagicMock()
    wiki_cfg.domain_agent_early_exit_quality = 0.6
    wiki_cfg.domain_agent_early_exit_min_chars = 500
    wiki_cfg.use_orchestrator_template = False
    wiki_cfg.topic_split_quality_check = False

    with (
        patch("core.config.get_settings") as mock_settings,
        patch("wiki.domain_doc_agent.get_settings") as mock_settings_local,
        patch("wiki.domain_doc_agent.evaluate_quality", return_value=mock_quality) as mock_eval,
    ):
        wiki_cfg.plan_topics_min_modules = 99
        wiki_cfg.enable_topic_pages = False
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)
        mock_settings_local.return_value = MagicMock(wiki=wiki_cfg)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )

    assert len(pages) >= 1
    assert agent._page_agent.write.call_count == 1
    assert mock_eval.call_count == 1
