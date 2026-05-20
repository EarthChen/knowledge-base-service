"""Tests for FalkorDB schema/index creation observability."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ensure_schema_logs_warning_when_index_creation_raises() -> None:
    """Index creation failures (e.g. index already exists) should emit warning logs."""

    from store.falkordb_store import FalkorDBStore

    store = FalkorDBStore.__new__(FalkorDBStore)
    store._embedding_dim = 1024
    store._graph = MagicMock()
    store._graph.query = MagicMock(side_effect=RuntimeError("Index already exists"))

    with patch("store.falkordb_store.log") as mock_log:
        await FalkorDBStore._ensure_schema(store)

    warning_events = [c.args[0] for c in mock_log.warning.call_args_list if c.args]
    assert "index_create_skipped" in warning_events
    assert "vector_index_create_skipped" in warning_events
