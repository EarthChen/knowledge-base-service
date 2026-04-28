"""Memory tier promotion in ``WikiLintService`` when ``memory_tiers_enabled`` is set."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from config import AppWikiFlags
from wiki.lint import WikiLintService


@pytest.mark.asyncio
async def test_lint_memory_promotion_skips_when_flag_off() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()
    wiki_store = MagicMock()
    lwq = AsyncMock()
    wiki_store.list_wiki_qa = lwq
    wiki_store.list_wiki_pages_for_repo = AsyncMock(return_value=[])
    up = AsyncMock()
    wiki_store.update_wiki_qa_memory = up
    cfg = AppWikiFlags(memory_tiers_enabled=False)
    svc = WikiLintService(store, wiki_store=wiki_store, wiki_config=cfg)
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
        setattr(svc, name, AsyncMock(return_value=[]))
    report = await svc.lint("r1", scope="all")
    lwq.assert_not_awaited()
    up.assert_not_awaited()
    assert report.stats.get("memory_tier_updates", 0) == 0


@pytest.mark.asyncio
async def test_lint_memory_promotion_persists_tier_and_promoted_at() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock()
    row = {
        "uid": "WikiQA:default:abc1",
        "question": "Q",
        "answer": "A",
        "source_pages": "[]",
        "quality_score": 0.4,
        "created_at": "2020-01-01T00:00:00Z",
        "tier": 0,
        "memory_status": "active",
        "confidence": 0.0,
        "access_count": 2,
        "confirmation_count": 0,
        "last_accessed": "",
        "promoted_at": "",
        "stability_factor": 7.0,
    }
    lwq = AsyncMock(return_value=MagicMock(data=[row]))
    up = AsyncMock()
    wiki_store = MagicMock()
    wiki_store.list_wiki_qa = lwq
    wiki_store.update_wiki_qa_memory = up
    wiki_store.list_wiki_pages_for_repo = AsyncMock(return_value=[])
    cfg = AppWikiFlags().model_copy(update={"memory_tiers_enabled": True})
    svc = WikiLintService(store, wiki_store=wiki_store, wiki_config=cfg)
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
        setattr(svc, name, AsyncMock(return_value=[]))
    report = await svc.lint("r1", scope="all")
    lwq.assert_awaited()
    up.assert_awaited()
    call_kw = up.await_args.kwargs
    assert call_kw.get("uid") == "WikiQA:default:abc1"
    assert call_kw.get("tier") == 1
    assert call_kw.get("promoted_at")
    assert report.stats.get("memory_tier_updates") == 1
