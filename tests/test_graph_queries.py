"""Unit tests for store.graph_queries GraphQueryRepository (architecture layer search)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.graph_queries import GraphQueryRepository


@pytest.mark.asyncio
class TestSearchClassesByArchitectureLayer:
    async def test_search_with_name_filter(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(
            return_value=QueryResultWrapper(
                [
                    {
                        "uid": "c1",
                        "name": "UserService",
                        "fqn": "x.UserService",
                        "file": "a.java",
                        "repository": "r",
                        "semantic_roles": [],
                        "architecture_layer": "business",
                        "m_uid": None,
                    }
                ]
            )
        )
        repo = GraphQueryRepository(store)
        await repo.search_classes_by_architecture_layer(
            "business", None, 50, search="User", offset=0
        )
        store.execute_query.assert_awaited_once()
        _cypher, params = store.execute_query.call_args[0]
        assert params is not None
        assert params.get("search") == "user"
        assert "AND toLower(c.name) CONTAINS $search" in _cypher

    async def test_search_with_offset(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(return_value=QueryResultWrapper([]))
        repo = GraphQueryRepository(store)
        await repo.search_classes_by_architecture_layer(
            "presentation", None, 25, offset=100
        )
        _cypher, params = store.execute_query.call_args[0]
        assert params["offset"] == 100
        assert params["limit"] == 25
        assert params["layer"] == "presentation"
        assert "SKIP $offset LIMIT $limit" in _cypher

    async def test_search_with_all_params(self) -> None:
        store = MagicMock()
        store.execute_query = AsyncMock(return_value=QueryResultWrapper([]))
        repo = GraphQueryRepository(store)
        await repo.search_classes_by_architecture_layer(
            "data_access",
            "my-repo",
            20,
            search="Dao",
            offset=5,
        )
        _cypher, params = store.execute_query.call_args[0]
        assert params == {
            "layer": "data_access",
            "limit": 20,
            "offset": 5,
            "repo": "my-repo",
            "search": "dao",
        }
        assert "c.repository = $repo" in _cypher
        assert "toLower(c.name) CONTAINS $search" in _cypher
