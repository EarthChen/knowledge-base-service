"""Tests for WikiStore Cypher delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.wiki_store import WikiStore


@pytest.fixture
def mock_base() -> MagicMock:
    s = MagicMock()
    s.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    return s


@pytest.fixture
def wiki_store(mock_base: MagicMock) -> WikiStore:
    return WikiStore(mock_base)


@pytest.mark.asyncio
class TestWikiStore:
    async def test_neighbor_names(self, mock_base: MagicMock, wiki_store: WikiStore) -> None:
        await wiki_store.neighbor_names("OrderService")
        cypher, params = mock_base.execute_query.call_args[0]
        assert "CALLS|INHERITS|IMPORTS" in cypher
        assert params == {"name": "OrderService"}

    async def test_graph_path_search(self, mock_base: MagicMock, wiki_store: WikiStore) -> None:
        await wiki_store.graph_path_search("r1", ["A", "B"], 20)
        cypher, params = mock_base.execute_query.call_args[0]
        assert "UNWIND $terms" in cypher
        assert params["repository"] == "r1" and params["limit"] == 20

    async def test_vector_wiki_search(self, mock_base: MagicMock, wiki_store: WikiStore) -> None:
        await wiki_store.vector_wiki_search(5, [0.1, 0.2], "r1", 10)
        cypher, params = mock_base.execute_query.call_args[0]
        assert "vector.queryNodes('WikiPage'" in cypher
        assert params["k"] == 5 and params["limit"] == 10

    async def test_lint_stale_entity_refs(self, mock_base: MagicMock, wiki_store: WikiStore) -> None:
        await wiki_store.lint_stale_entity_refs("myrepo")
        cypher, params = mock_base.execute_query.call_args[0]
        assert "stale_uid" in cypher
        assert params == {"repository": "myrepo"}

    async def test_ask_query_one_hop(self, mock_base: MagicMock, wiki_store: WikiStore) -> None:
        await wiki_store.ask_query_one_hop(["a", "b"])
        cypher, params = mock_base.execute_query.call_args[0]
        assert "CALLS|INHERITS|IMPORTS" in cypher
        assert params == {"names": ["a", "b"]}

    async def test_list_all_wiki_pages(self, mock_base: MagicMock, wiki_store: WikiStore) -> None:
        await wiki_store.list_all_wiki_pages("r1")
        cypher, params = mock_base.execute_query.call_args[0]
        assert "WikiPage" in cypher
        assert params == {"repo": "r1"}
