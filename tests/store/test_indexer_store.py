"""Tests for IndexerStore Cypher delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.indexer_store import IndexerStore


@pytest.fixture
def mock_base() -> MagicMock:
    s = MagicMock()
    s.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    return s


@pytest.fixture
def idx_store(mock_base: MagicMock) -> IndexerStore:
    return IndexerStore(mock_base)


@pytest.mark.asyncio
class TestIndexerStore:
    async def test_entry_points_semantic_functions(self, mock_base: MagicMock, idx_store: IndexerStore) -> None:
        await idx_store.entry_points_semantic_functions()
        args = mock_base.execute_query.call_args[0]
        cypher = args[0]
        assert "http_endpoint" in cypher
        assert "RETURN f" in cypher

    async def test_enrich_set_function_http_props(self, mock_base: MagicMock, idx_store: IndexerStore) -> None:
        await idx_store.enrich_set_function_http_props("u1", "GET", "/api/x")
        cypher, params = mock_base.execute_query.call_args[0]
        assert "SET f.http_method" in cypher
        assert params == {"uid": "u1", "method": "GET", "path": "/api/x"}

    async def test_cross_repo_merge_rpc_edge(self, mock_base: MagicMock, idx_store: IndexerStore) -> None:
        await idx_store.cross_repo_merge_rpc_edge("c1", "p1", "ra", "rb", "Iface")
        cypher, params = mock_base.execute_query.call_args[0]
        assert "CROSS_REPO_CALLS" in cypher
        assert params["consumer_uid"] == "c1" and params["provider_uid"] == "p1"

    async def test_di_merge_depends_on(self, mock_base: MagicMock, idx_store: IndexerStore) -> None:
        await idx_store.di_merge_depends_on("s", "t", "field", "myField")
        cypher, params = mock_base.execute_query.call_args[0]
        assert "DEPENDS_ON" in cypher
        assert params["field_name"] == "myField"
