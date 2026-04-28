"""WikiLintService recalculates confidence when ``confidence_scoring_enabled`` is set."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from config import AppWikiFlags
from wiki.lint import WikiLintService


@pytest.mark.asyncio
async def test_lint_includes_confidence_recalibrated_count_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()

    async def _empty_list(_repo: str) -> MagicMock:
        w = MagicMock()
        w.data = [{"path": "a.md", "generated_at": "2026-01-01T00:00:00+00:00"}]
        return w

    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_for_repo = AsyncMock(side_effect=_empty_list)
    wiki_store.list_wiki_qa = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.update_wiki_qa_memory = AsyncMock()

    cfg = AppWikiFlags().model_copy(update={"confidence_scoring_enabled": True})

    async def _fake_recalc(
        _store: object,
        _repository: str,
        *,
        wiki_store: object,
        scorer: object,
        business_id: str = "default",
    ) -> int:
        return 1

    monkeypatch.setattr(
        "wiki.confidence_inputs.recalculate_confidence_scores_for_repo",
        _fake_recalc,
    )

    svc = WikiLintService(
        store,
        wiki_store=wiki_store,
        wiki_config=cfg,
    )
    # Avoid heavy check implementations
    for name in (
        "_check_staleness",
        "_check_orphans",
        "_check_broken_links",
        "_check_coverage_gaps",
        "_check_outdated_content",
        "_check_contradictions",
        "_check_forgetting",
        "_check_schema",
    ):
        monkeypatch.setattr(svc, name, AsyncMock(return_value=[]))

    report = await svc.lint("r1", scope="all")
    assert report.stats.get("confidence_recalibrated") == 1


@pytest.mark.asyncio
async def test_lint_skips_confidence_recal_when_flag_off() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()
    wiki_store = MagicMock()
    wiki_store.list_wiki_pages_for_repo = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.list_wiki_qa = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.update_wiki_qa_memory = AsyncMock()
    cfg = AppWikiFlags(confidence_scoring_enabled=False)
    svc = WikiLintService(
        store,
        wiki_store=wiki_store,
        wiki_config=cfg,
    )
    for m in (
        "_check_staleness",
        "_check_orphans",
        "_check_broken_links",
        "_check_coverage_gaps",
        "_check_outdated_content",
        "_check_contradictions",
        "_check_forgetting",
        "_check_schema",
    ):
        setattr(svc, m, AsyncMock(return_value=[]))
    report = await svc.lint("r1", scope="all")
    assert report.stats.get("confidence_recalibrated") == 0
