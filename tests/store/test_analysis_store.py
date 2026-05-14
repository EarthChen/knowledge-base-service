"""Unit tests for store.analysis_store.AnalysisStore (Cypher wiring)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.analysis_store import AnalysisStore, _Q_STATS
from store.falkordb_store import QueryResultWrapper


@pytest.fixture
def mock_base() -> MagicMock:
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=QueryResultWrapper(data=[{"x": 1}], raw=[]),
    )
    return store


@pytest.mark.asyncio
class TestAnalysisStoreCypher:
    async def test_resolve_entity_params(self, mock_base: MagicMock) -> None:
        a = AnalysisStore(mock_base)
        await a.resolve_entity("foo.Bar#baz", "myrepo")
        call = mock_base.execute_query.call_args
        assert "n:Function OR n:Class OR n:Module" in call[0][0]
        assert call[0][1]["repository"] == "myrepo"

    async def test_community_nodes_includes_marker(self, mock_base: MagicMock) -> None:
        a = AnalysisStore(mock_base)
        await a.fetch_community_nodes("r1")
        q = mock_base.execute_query.call_args[0][0]
        assert "community_nodes" in q

    async def test_graph_stats_query_tag(self, mock_base: MagicMock) -> None:
        a = AnalysisStore(mock_base)
        await a.collect_graph_stats(["repo_a"])
        q = mock_base.execute_query.call_args[0][0]
        assert _Q_STATS in q
        assert mock_base.execute_query.call_args[0][1] == {"repos": ["repo_a"]}

    async def test_analyze_impact_interpolates_depth(self, mock_base: MagicMock) -> None:
        a = AnalysisStore(mock_base)
        await a.analyze_impact_callers(4, ["x", "y"])
        q = mock_base.execute_query.call_args[0][0]
        assert "CALLS*1..4" in q
        assert mock_base.execute_query.call_args[0][1] == {"names": ["x", "y"]}

    async def test_agent_find_changed_entities_repo_filter(self, mock_base: MagicMock) -> None:
        a = AnalysisStore(mock_base)
        await a.agent_find_changed_entities("src/a.py", "repo1")
        q = mock_base.execute_query.call_args[0][0]
        assert "ENDS WITH $file_suffix" in q
        assert "n.repository = $repo" in q

    async def test_endpoint_http_with_repo(self, mock_base: MagicMock) -> None:
        a = AnalysisStore(mock_base)
        await a.query_http_endpoints("myrepo")
        q = mock_base.execute_query.call_args[0][0]
        assert "f.api_path IS NOT NULL" in q
        assert "f.repository = $repo" in q
