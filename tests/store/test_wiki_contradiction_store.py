"""Tests for wiki contradiction Cypher in WikiStore."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore


@pytest.mark.asyncio
async def test_upsert_contradiction_query_contains_model() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock()
    store = WikiStore(base)
    await store.upsert_wiki_contradiction(
        uid="WikiContradiction:u1:u2",
        page_uid_a="WikiPage:r:a.md",
        page_uid_b="WikiPage:r:b.md",
        description="test",
        severity="medium",
        status="detected",
    )
    assert base.execute_query.await_count == 1
    call = base.execute_query.await_args
    cypher = str(call[0][0])
    assert "WikiContradiction" in cypher
    assert "HAS_CONTRADICTION" in cypher


@pytest.mark.asyncio
async def test_list_contradictions_for_page() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"uid": "c1", "status": "detected", "page_uid_a": "a", "page_uid_b": "b"}]),
    )
    store = WikiStore(base)
    rows = await store.list_wiki_contradictions_for_page("WikiPage:r:p.md", include_resolved=False)
    assert len(rows) == 1
    q = str(base.execute_query.await_args[0][0])
    assert "WikiContradiction" in q
    assert "HAS_CONTRADICTION" in q
