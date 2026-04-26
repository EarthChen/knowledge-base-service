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


@pytest.mark.asyncio
async def test_no_duplicate_claims_on_regen() -> None:
    """Reusing the same claim text should not create a second active WikiClaimHistory node."""
    base = MagicMock()
    find_count = 0
    create_calls: list[dict[str, object]] = []

    async def execute_query(q: str, params: dict[str, object] | None = None) -> MagicMock:
        nonlocal find_count
        p = params or {}
        if "RETURN h.uid AS uid" in str(q) and "LIMIT 1" in str(q):
            find_count += 1
            if find_count == 1:
                return MagicMock(data=[])
            return MagicMock(data=[{"uid": "existing-uid"}])
        if "MERGE (h:WikiClaimHistory" in str(q):
            create_calls.append(p)
            return MagicMock()
        return MagicMock(data=[])

    base.execute_query = execute_query
    store = WikiStore(base)
    u1 = await store.find_or_create_wiki_claim(
        "WikiPage:repo:src/Foo.md",
        "The module handles auth",
        1,
        new_claim_uid="WikiClaimHistory:WikiPage:repo:src/Foo.md:1",
        created_at=1000,
    )
    u2 = await store.find_or_create_wiki_claim(
        "WikiPage:repo:src/Foo.md",
        "The module handles auth",
        2,
        new_claim_uid="WikiClaimHistory:WikiPage:repo:src/Foo.md:2",
        created_at=2000,
    )
    assert u1 == "WikiClaimHistory:WikiPage:repo:src/Foo.md:1"
    assert u2 == "existing-uid"
    assert len(create_calls) == 1
