"""Unit tests for ``WikiEditingStore`` (Redis ZSET presence)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.editing_store import WikiEditingStore


@pytest.fixture
def mock_redis() -> MagicMock:
    r = MagicMock()
    r.zadd = AsyncMock()
    r.zremrangebyscore = AsyncMock()
    r.expire = AsyncMock()
    r.zrem = AsyncMock()
    r.zcard = AsyncMock(return_value=0)
    r.delete = AsyncMock()
    r.zrange = AsyncMock(return_value=[])
    return r


@pytest.fixture
def store(mock_redis: MagicMock) -> WikiEditingStore:
    return WikiEditingStore(mock_redis)


def test_editor_fingerprint_stable_for_token() -> None:
    a = WikiEditingStore.editor_fingerprint(token="tok-one", client_host="127.0.0.1")
    b = WikiEditingStore.editor_fingerprint(token="tok-one", client_host="127.0.0.1")
    c = WikiEditingStore.editor_fingerprint(token="tok-two", client_host="127.0.0.1")
    assert a == b
    assert a != c
    assert len(a) == WikiEditingStore.FINGERPRINT_LEN


@pytest.mark.asyncio
async def test_heartbeat_zadd_prune_expire(
    store: WikiEditingStore, mock_redis: MagicMock
) -> None:
    await store.heartbeat("page-uid-1", "deadbeef" * 2)
    mock_redis.zadd.assert_awaited_once()
    mock_redis.zremrangebyscore.assert_awaited_once()
    mock_redis.expire.assert_awaited_with(
        f"{WikiEditingStore.KEY_PREFIX}page-uid-1", WikiEditingStore.TTL_SEC,
    )


@pytest.mark.asyncio
async def test_stop_removes_and_deletes_empty(
    store: WikiEditingStore, mock_redis: MagicMock
) -> None:
    mock_redis.zcard = AsyncMock(return_value=0)
    await store.stop("p1", "e1")
    mock_redis.zrem.assert_awaited_once()
    mock_redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_editors_marks_other_active(
    store: WikiEditingStore, mock_redis: MagicMock
) -> None:
    e0 = "a" * 16
    e1 = "b" * 16
    mock_redis.zrange = AsyncMock(
        return_value=[(e0, 1_700_000_000.0), (e1, 1_700_000_100.0)],
    )
    out = await store.list_editors("p1", self_editor_id=e0)
    assert out["other_active"] is True
    assert len(out["editors"]) == 2
    out2 = await store.list_editors("p1", self_editor_id="nomatch" * 4)
    assert out2["other_active"] is True


@pytest.mark.asyncio
async def test_list_editors_only_self_no_other(
    store: WikiEditingStore, mock_redis: MagicMock
) -> None:
    e0 = "c" * 16
    mock_redis.zrange = AsyncMock(return_value=[(e0, 1_700_000_000.0)])
    out = await store.list_editors("p1", self_editor_id=e0)
    assert out["other_active"] is False


@pytest.mark.asyncio
async def test_list_editors_labels_include_token_prefix(
    store: WikiEditingStore, mock_redis: MagicMock
) -> None:
    e0 = "deadbeef" + "0" * 8
    mock_redis.zrange = AsyncMock(return_value=[(e0, 1_700_000_000.0)])
    out = await store.list_editors("p1", self_editor_id=e0)
    assert out["editors"][0]["token_prefix"] == "deadbeef"
    assert "deadbeef" in out["editors"][0]["label"]
