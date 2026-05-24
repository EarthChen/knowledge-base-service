"""Tests for get_domain_architecture_layers on WikiTreeStoreMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore


@pytest.fixture
def wiki_store() -> WikiStore:
    base = MagicMock()
    base.execute_query = AsyncMock()
    return WikiStore(base)


@pytest.mark.asyncio
async def test_get_domain_architecture_layers(wiki_store: WikiStore) -> None:
    """Mock query result → proper aggregation by domain and layer."""
    wiki_store._store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"domain": "payment", "layer": "api", "cnt": 2},
                {"domain": "payment", "layer": "service", "cnt": 3},
                {"domain": "orders", "layer": "data", "cnt": 1},
            ],
        ),
    )

    result = await wiki_store.get_domain_architecture_layers("test-biz")

    assert result == {
        "payment": {"api": 2, "service": 3},
        "orders": {"data": 1},
    }
    wiki_store._store.execute_query.assert_awaited_once()
