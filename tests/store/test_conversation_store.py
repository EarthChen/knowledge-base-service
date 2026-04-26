# tests/store/test_conversation_store.py
import asyncio

import pytest

from store.conversation_store import (
    ConversationHistory,
    ConversationTurn,
    SqliteConversationStore,
)


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "conv.db")


@pytest.mark.asyncio
async def test_create_and_get(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db)
    await store.initialize()
    history = await store.create("repo-a", scope="module")
    assert history.repository == "repo-a"
    assert history.conversation_id

    fetched = await store.get(history.conversation_id)
    assert fetched is not None
    assert fetched.repository == "repo-a"
    await store.close()


@pytest.mark.asyncio
async def test_save_turns_and_retrieve(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db)
    await store.initialize()
    history = await store.create("repo-b")
    history.turns.append(ConversationTurn(role="user", content="hello"))
    history.turns.append(ConversationTurn(role="assistant", content="hi"))
    await store.save(history)

    fetched = await store.get(history.conversation_id)
    assert fetched is not None
    assert len(fetched.turns) == 2
    assert fetched.turns[0].content == "hello"
    await store.close()


@pytest.mark.asyncio
async def test_ttl_expiration(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db, ttl_seconds=0)
    await store.initialize()
    history = await store.create("repo-c")
    await asyncio.sleep(0.05)
    fetched = await store.get(history.conversation_id)
    assert fetched is None
    await store.close()


@pytest.mark.asyncio
async def test_lru_eviction(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db, max_conversations=2)
    await store.initialize()
    h1 = await store.create("repo-1")
    h2 = await store.create("repo-2")
    h3 = await store.create("repo-3")

    assert await store.get(h1.conversation_id) is None
    assert await store.get(h2.conversation_id) is not None
    assert await store.get(h3.conversation_id) is not None
    await store.close()


@pytest.mark.asyncio
async def test_max_turns_truncation(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db, max_turns=2)
    await store.initialize()
    history = await store.create("repo-trunc")
    history.turns.append(ConversationTurn(role="user", content="q1"))
    history.turns.append(ConversationTurn(role="assistant", content="a1"))
    history.turns.append(ConversationTurn(role="user", content="q2"))
    history.turns.append(ConversationTurn(role="assistant", content="a2"))
    await store.save(history)

    fetched = await store.get(history.conversation_id)
    assert fetched is not None
    assert len(fetched.turns) == 2
    assert fetched.turns[0].content == "q2"
    assert fetched.turns[1].content == "a2"
    await store.close()
