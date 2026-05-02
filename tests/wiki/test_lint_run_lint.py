from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import AppWikiFlags
from wiki.lint import LintReport, WikiLintService


def _make_report() -> LintReport:
    return LintReport(
        issues=[],
        stats={"total": 0, "errors": 0, "warnings": 0, "info": 0},
        checked_at="t0",
        scope="all",
    )


@pytest.mark.asyncio
async def test_run_lint_merges_heal_when_auto_heal_enabled() -> None:
    mock_store = MagicMock()
    mock_store.list_wiki_pages_for_repo = AsyncMock(return_value=MagicMock(data=[]))
    cfg = MagicMock(spec=AppWikiFlags)
    cfg.auto_heal_enabled = True
    cfg.contradiction_detection_enabled = False
    cfg.confidence_scoring_enabled = False
    cfg.forgetting_enabled = False
    cfg.memory_tiers_enabled = False
    cfg.schema_validation_enabled = False

    svc = WikiLintService(
        mock_store,
        wiki_config=cfg,
    )
    with patch.object(svc, "lint", new_callable=AsyncMock) as m_lint:
        m_lint.return_value = _make_report()
        with patch("wiki.lint.AutoHealer") as m_heal_cls:
            m_heal = MagicMock()
            m_heal.heal = AsyncMock(return_value={"refs_removed": 5, "pages_deprecated": 1})
            m_heal_cls.return_value = m_heal
            out = await svc.run_lint("repo-a", scope="all")
    assert out["scope"] == "all"
    assert out["auto_heal"] == {"refs_removed": 5, "pages_deprecated": 1}
    m_heal.heal.assert_awaited_once_with("repo-a")
    m_lint.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_lint_skips_heal_when_auto_heal_disabled() -> None:
    mock_store = MagicMock()
    cfg = MagicMock(spec=AppWikiFlags)
    cfg.auto_heal_enabled = False
    cfg.contradiction_detection_enabled = False
    cfg.confidence_scoring_enabled = False
    cfg.forgetting_enabled = False
    cfg.memory_tiers_enabled = False
    cfg.schema_validation_enabled = False

    svc = WikiLintService(mock_store, wiki_config=cfg)
    with patch.object(svc, "lint", new_callable=AsyncMock) as m_lint:
        m_lint.return_value = _make_report()
        with patch("wiki.lint.AutoHealer") as m_heal_cls:
            out = await svc.run_lint("repo-b", scope="all")
    assert out.get("auto_heal") is None
    m_heal_cls.assert_not_called()
