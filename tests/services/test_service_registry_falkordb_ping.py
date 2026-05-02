"""Unit tests for ServiceRegistry.falkordb_graph_ping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Settings
from services.service_registry import ServiceRegistry


@pytest.mark.asyncio
async def test_falkordb_graph_ping_ready_when_query_succeeds() -> None:
    reg = ServiceRegistry(Settings())
    mock_store = MagicMock()
    mock_store.execute_query = AsyncMock(return_value=MagicMock())
    mock_svc = MagicMock()
    mock_svc.store = mock_store
    reg._services["default"] = mock_svc

    assert await reg.falkordb_graph_ping() == "ready"
    mock_store.execute_query.assert_awaited_once_with("RETURN 1 AS ok LIMIT 1", {})


@pytest.mark.asyncio
async def test_falkordb_graph_ping_unreachable_when_no_default_service() -> None:
    reg = ServiceRegistry(Settings())
    assert await reg.falkordb_graph_ping() == "unreachable"


@pytest.mark.asyncio
async def test_falkordb_graph_ping_unreachable_on_query_error() -> None:
    reg = ServiceRegistry(Settings())
    mock_store = MagicMock()
    mock_store.execute_query = AsyncMock(side_effect=RuntimeError("graph down"))
    mock_svc = MagicMock()
    mock_svc.store = mock_store
    reg._services["default"] = mock_svc

    assert await reg.falkordb_graph_ping() == "unreachable"
