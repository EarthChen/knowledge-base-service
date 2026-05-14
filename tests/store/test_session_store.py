import asyncio

import pytest

from store.session_store import Session, SessionTurn, SqliteSessionStore


@pytest.fixture
async def store(tmp_path):
    s = SqliteSessionStore(db_path=str(tmp_path / "test_sessions.db"), ttl_seconds=60)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_save_and_get(store):
    session = Session(session_id="s1", session_type="ask")
    session.turns.append(SessionTurn(role="user", content="hello"))
    await store.save(session)
    loaded = await store.get("s1")
    assert loaded is not None
    assert loaded.session_id == "s1"
    assert loaded.session_type == "ask"
    assert len(loaded.turns) == 1
    assert loaded.turns[0].content == "hello"


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_delete(store):
    await store.save(Session(session_id="s2", session_type="edit"))
    await store.delete("s2")
    assert await store.get("s2") is None


@pytest.mark.asyncio
async def test_ttl_expiration(tmp_path):
    store = SqliteSessionStore(db_path=str(tmp_path / "ttl.db"), ttl_seconds=1)
    await store.initialize()
    await store.save(Session(session_id="s3", session_type="ask"))
    await asyncio.sleep(1.5)
    assert await store.get("s3") is None
    await store.close()


@pytest.mark.asyncio
async def test_list_by_type(store):
    await store.save(Session(session_id="a1", session_type="ask"))
    await store.save(Session(session_id="a2", session_type="ask"))
    await store.save(Session(session_id="e1", session_type="edit"))
    asks = await store.list_by_type("ask")
    assert len(asks) == 2
    edits = await store.list_by_type("edit")
    assert len(edits) == 1


@pytest.mark.asyncio
async def test_max_turns_truncation(tmp_path):
    store = SqliteSessionStore(db_path=str(tmp_path / "trunc.db"), max_turns=3)
    await store.initialize()
    session = Session(session_id="s4", session_type="ask")
    for i in range(10):
        session.turns.append(SessionTurn(role="user", content=f"msg{i}"))
    await store.save(session)
    loaded = await store.get("s4")
    assert len(loaded.turns) == 3
    assert loaded.turns[0].content == "msg7"
    await store.close()


@pytest.mark.asyncio
async def test_metadata_roundtrip(store):
    session = Session(
        session_id="s5",
        session_type="edit",
        metadata={"page_uid": "p1", "original_content": "# Title"},
    )
    await store.save(session)
    loaded = await store.get("s5")
    assert loaded.metadata["page_uid"] == "p1"


@pytest.mark.asyncio
async def test_cleanup_expired(tmp_path):
    store = SqliteSessionStore(db_path=str(tmp_path / "cleanup.db"), ttl_seconds=1)
    await store.initialize()
    await store.save(Session(session_id="old", session_type="ask"))
    await asyncio.sleep(1.5)
    count = await store.cleanup_expired()
    assert count >= 1
    await store.close()


@pytest.mark.asyncio
async def test_upsert_updates_existing(store):
    session = Session(session_id="s6", session_type="ask")
    session.turns.append(SessionTurn(role="user", content="first"))
    await store.save(session)
    session.turns.append(SessionTurn(role="assistant", content="reply"))
    await store.save(session)
    loaded = await store.get("s6")
    assert len(loaded.turns) == 2
