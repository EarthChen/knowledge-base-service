import pytest
from unittest.mock import AsyncMock, MagicMock

from store.graph_queries import GraphQueryRepository


@pytest.mark.asyncio
async def test_shortest_path_uses_store_execute() -> None:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"path": [], "depth": 0, "nodes": ["A", "B"], "rels": ["CALLS"]}])
    )
    repo = GraphQueryRepository(store)
    result = await repo.shortest_path_between_names(
        repository="r1", from_name="A", to_name="B", max_depth=5
    )
    assert result["ok"] is True
    assert store.execute_query.await_count >= 1


@pytest.mark.asyncio
async def test_shortest_path_fallback_on_error() -> None:
    store = MagicMock()
    call_count = 0

    async def side_effect(cypher, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("shortestPath not supported")
        return MagicMock(data=[{"depth": 2, "nodes": ["A", "C", "B"], "rels": ["CALLS", "IMPORTS"]}])

    store.execute_query = AsyncMock(side_effect=side_effect)
    repo = GraphQueryRepository(store)
    result = await repo.shortest_path_between_names(
        repository="r1", from_name="A", to_name="B"
    )
    assert result["used"] == "variable_length_fallback"
