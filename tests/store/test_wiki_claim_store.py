"""Tests for wiki claim history Cypher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore


@pytest.mark.asyncio
async def test_create_claim_history_query() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock()
    store = WikiStore(base)
    await store.create_wiki_claim_history(
        "h1",
        "WikiPage:r:a.md",
        "text",
        1,
        superseded_by=None,
        created_at=100,
        superseded_at=None,
    )
    q = str(base.execute_query.await_args[0][0])
    assert "WikiClaimHistory" in q
    assert "HAS_CLAIM" in q
