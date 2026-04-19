"""Unit tests for TraversalStore Cypher delegation (execute_query wiring)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from store.traversal_store import TraversalStore


@pytest.fixture
def mock_store() -> MagicMock:
    s = MagicMock()
    s.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    return s


@pytest.fixture
def traversal(mock_store: MagicMock) -> TraversalStore:
    return TraversalStore(mock_store)


@pytest.mark.asyncio
class TestTraversalStoreQueries:
    async def test_find_call_chain_downstream_pattern(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.find_call_chain("foo", 3, "downstream")
        mock_store.execute_query.assert_awaited_once()
        cypher, _params = mock_store.execute_query.call_args[0]
        assert "MATCH (f:Function)" in cypher
        assert "(f)-[:CALLS*1..3]->(callee:Function)" in cypher

    async def test_find_call_chain_upstream_pattern(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.find_call_chain("foo", 2, "upstream")
        cypher, _ = mock_store.execute_query.call_args[0]
        assert "(caller:Function)-[:CALLS*1..2]->(f)" in cypher

    async def test_find_inheritance_tree_pattern(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.find_inheritance_tree("Bar", "children")
        cypher, _ = mock_store.execute_query.call_args[0]
        assert "(child:Class)-[:INHERITS*1..10]->(c)" in cypher

    async def test_find_class_methods_pattern(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.find_class_methods("Bar")
        cypher, params = mock_store.execute_query.call_args[0]
        assert "MATCH (c)-[:CONTAINS]->(m:Function)" in cypher
        assert "ORDER BY start_line" in cypher
        assert "simple_name" in params and "fqn" in params

    async def test_find_entity_any_pattern(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.find_entity("x", "any")
        cypher, _ = mock_store.execute_query.call_args[0]
        assert "n:Function OR n:Class OR n:Module" in cypher
        assert "labels(n)[0] AS type" in cypher

    async def test_expand_node_neighbors_pattern(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.expand_node_neighbors("uid-1", [], 10, 2)
        cypher, params = mock_store.execute_query.call_args[0]
        assert "MATCH path = (center)-[:" in cypher
        assert "CALLS|INHERITS|IMPORTS|CONTAINS|PART_OF|REFERENCES" in cypher
        assert params["center_uid"] == "uid-1"
        assert params["limit"] == 10

    async def test_get_code_entity_for_snippet(self, mock_store: MagicMock, traversal: TraversalStore) -> None:
        await traversal.get_code_entity_for_snippet("uid-x")
        cypher, params = mock_store.execute_query.call_args[0]
        assert "MATCH (n) WHERE n.uid = $uid AND (n:Function OR n:Class)" in cypher
        assert "code_snippet" in cypher
        assert params["uid"] == "uid-x"
