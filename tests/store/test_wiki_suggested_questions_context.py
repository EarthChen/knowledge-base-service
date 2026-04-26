"""Unit tests for WikiStore.get_suggested_questions_context."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.wiki_store import WikiStore


@pytest.mark.asyncio
async def test_get_suggested_questions_context_no_wiki_page() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    ws = WikiStore(store)
    assert await ws.get_suggested_questions_context("missing") is None
    assert store.execute_query.await_count == 1


@pytest.mark.asyncio
async def test_get_suggested_questions_context_no_source_entity_uses_page_title() -> None:
    store = MagicMock()
    node = MagicMock()
    node.properties = {"uid": "wp1", "title": "MyPage", "repository": "r1"}
    store.execute_query = AsyncMock(
        side_effect=[
            QueryResultWrapper(data=[{"wp": node}], raw=[]),
            QueryResultWrapper(data=[], raw=[]),
        ]
    )
    ws = WikiStore(store)
    out = await ws.get_suggested_questions_context("wp1")
    assert out is not None
    assert out["entity_name"] == "MyPage"
    assert out["domain"] == "r1"
    assert out["callers"] == []
    assert out["callees"] == []


@pytest.mark.asyncio
async def test_get_suggested_questions_context_resolves_call_graph() -> None:
    store = MagicMock()
    node = MagicMock()
    node.properties = {"uid": "wp1", "title": "Svc", "repository": "r1"}
    store.execute_query = AsyncMock(
        side_effect=[
            QueryResultWrapper(data=[{"wp": node}], raw=[]),
            QueryResultWrapper(
                data=[{"e_uid": "e1", "e_name": "Svc", "e_repo": "r1"}],
                raw=[],
            ),
            QueryResultWrapper(data=[{"domain": "mod-a"}], raw=[]),
            QueryResultWrapper(
                data=[{"name": "A", "repository": "r1"}, {"name": "B", "repository": "r2"}],
                raw=[],
            ),
            QueryResultWrapper(data=[{"name": "D1"}, {"name": "D2"}], raw=[]),
        ]
    )
    ws = WikiStore(store)
    out = await ws.get_suggested_questions_context("wp1")
    assert out is not None
    assert out["entity_name"] == "Svc"
    assert out["domain"] == "mod-a"
    assert out["callers"] == ["A", "B"]
    assert "B" in out["cross_domain_callers"]
    assert out["callees"] == ["D1", "D2"]
