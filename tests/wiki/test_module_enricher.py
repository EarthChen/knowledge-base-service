import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.module_enricher import ModuleEnricher


class TestModuleEnricher:
    @pytest.fixture
    def mock_graph_store(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        return store

    @pytest.mark.asyncio
    async def test_enrich_returns_dict(self, mock_graph_store):
        enricher = ModuleEnricher(mock_graph_store)
        result = await enricher.enrich(["r"], ["Svc"])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_enrich_merges_all_signals(self, mock_graph_store):
        mock_graph_store.execute_query = AsyncMock(side_effect=[
            MagicMock(data=[{"module_name": "Svc", "repo": "r", "key_methods": ["m1", "m2"]}]),
            MagicMock(data=[{"source": "Svc", "repo": "r", "callees": ["Dao"], "fan_out": 1}]),
            MagicMock(data=[{"target": "Svc", "repo": "r", "callers": ["Ctrl"], "fan_in": 1}]),
        ])
        enricher = ModuleEnricher(mock_graph_store)
        result = await enricher.enrich(["r"], ["Svc"])
        key = ("r", "Svc")
        assert "key_methods" in result[key]
        assert "callees" in result[key]
        assert "callers" in result[key]
        assert "fan_in" in result[key]
        assert "fan_out" in result[key]

    @pytest.mark.asyncio
    async def test_enrich_caches_results(self, mock_graph_store):
        mock_graph_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        enricher = ModuleEnricher(mock_graph_store)
        await enricher.enrich(["r"], ["Svc"])
        call_count_after_first = mock_graph_store.execute_query.call_count
        await enricher.enrich(["r"], ["Svc"])
        assert mock_graph_store.execute_query.call_count == call_count_after_first

    @pytest.mark.asyncio
    async def test_get_returns_empty_for_unknown(self, mock_graph_store):
        enricher = ModuleEnricher(mock_graph_store)
        assert enricher.get("r", "Unknown") == {}
