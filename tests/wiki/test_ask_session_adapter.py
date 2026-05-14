"""Tests for AskSessionAdapter (SqliteSessionStore ↔ ConversationHistory)."""

import pytest

from store.session_store import SqliteSessionStore
from wiki.ask import AskSessionAdapter, ConversationTurn


@pytest.fixture
async def adapter(tmp_path):
    store = SqliteSessionStore(
        db_path=str(tmp_path / "ask.db"),
        max_turns=10,
        ttl_seconds=1800,
    )
    await store.initialize()
    yield AskSessionAdapter(store)
    await store.close()


@pytest.mark.asyncio
async def test_create_and_get(adapter):
    history = await adapter.create("test-repo", scope="/page")
    assert history.repository == "test-repo"
    assert history.scope == "/page"

    fetched = await adapter.get(history.conversation_id)
    assert fetched is not None
    assert fetched.repository == "test-repo"


@pytest.mark.asyncio
async def test_save_turns(adapter):
    history = await adapter.create("test-repo")
    history.turns.append(ConversationTurn(role="user", content="hello"))
    history.turns.append(ConversationTurn(role="assistant", content="hi"))
    await adapter.save(history)

    fetched = await adapter.get(history.conversation_id)
    assert fetched is not None
    assert len(fetched.turns) == 2


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(adapter):
    result = await adapter.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_business_id_preserved(adapter):
    history = await adapter.create("repo", business_id="biz1")
    fetched = await adapter.get(history.conversation_id)
    assert fetched is not None
    assert fetched.business_id == "biz1"
