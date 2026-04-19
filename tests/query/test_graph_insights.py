"""Tests for GraphInsightsService — graph architecture anomaly detection."""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import pytest

from query.graph_insights import (
    GraphInsightsService,
    InsightItem,
    InsightsReport,
)
from store.falkordb_store import QueryResultWrapper


def _wrap(rows: list[dict]) -> QueryResultWrapper:
    return QueryResultWrapper(data=rows, raw=[])


def _store_with_router(router) -> MagicMock:
    store = MagicMock()
    store.graph = MagicMock()

    async def execute_query(cypher: str, params: dict | None = None):
        return await router(cypher, params or {})

    store.execute_query = AsyncMock(side_effect=execute_query)
    return store


@pytest.mark.asyncio
class TestGraphInsightsService:
    async def test_empty_graph_returns_no_insights(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 0,
                    "module_count": 0,
                    "calls_same_repo": 0,
                    "imports_same_repo": 0,
                }])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("myrepo")
        assert report.insights == []
        assert report.graph_stats["class_count"] == 0
        assert report.graph_stats["module_count"] == 0
        assert report.analyzed_at

    async def test_isolated_entity_detection(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 2,
                    "module_count": 1,
                    "calls_same_repo": 0,
                    "imports_same_repo": 0,
                }])
            if "__GRAPH_INSIGHTS_Q_ISOLATED__" in cypher:
                return _wrap([{"name": "Orphan", "fqn": "com.example.Orphan"}])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("myrepo")
        isolated = [i for i in report.insights if i.category == "isolated"]
        assert len(isolated) == 1
        assert isolated[0].severity == "warning"
        assert "Orphan" in isolated[0].title or "Orphan" in isolated[0].description
        assert any("com.example.Orphan" in e for e in isolated[0].entities)

    async def test_circular_dependency_detection(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 1,
                    "module_count": 3,
                    "calls_same_repo": 0,
                    "imports_same_repo": 3,
                }])
            if "__GRAPH_INSIGHTS_Q_CYCLES__" in cypher:
                return _wrap([{"module_path": ["a", "b", "a"]}])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("myrepo")
        cycles = [i for i in report.insights if i.category == "circular_dep"]
        assert len(cycles) == 1
        assert cycles[0].severity == "critical"
        assert "import" in cycles[0].title.lower() or "cycle" in cycles[0].title.lower()

    async def test_cross_layer_violation(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 5,
                    "module_count": 1,
                    "calls_same_repo": 2,
                    "imports_same_repo": 0,
                }])
            if "__GRAPH_INSIGHTS_Q_CROSS_LAYER__" in cypher:
                return _wrap([{
                    "ctrl_name": "UserController",
                    "repo_name": "UserRepository",
                    "ctrl_fqn": "x.UserController",
                    "repo_fqn": "x.UserRepository",
                }])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("myrepo")
        xs = [i for i in report.insights if i.category == "cross_layer"]
        assert len(xs) == 1
        assert xs[0].severity == "warning"
        assert "UserController" in xs[0].entities[0] or "UserController" in xs[0].description

    async def test_module_cohesion_low(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 4,
                    "module_count": 1,
                    "calls_same_repo": 1,
                    "imports_same_repo": 0,
                }])
            if "__GRAPH_INSIGHTS_Q_COHESION__" in cypher:
                return _wrap([{
                    "module_name": "weak",
                    "module_path": "src/weak",
                    "internal_calls": 1,
                    "class_count": 4,
                    "cohesion": 0.08,
                }])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("myrepo")
        low = [i for i in report.insights if i.category == "low_cohesion"]
        assert len(low) == 1
        assert low[0].severity == "info"
        assert "0.08" in low[0].description or "cohesion" in low[0].description.lower()

    async def test_bridge_node_detection(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 3,
                    "module_count": 1,
                    "calls_same_repo": 5,
                    "imports_same_repo": 0,
                }])
            if "__GRAPH_INSIGHTS_Q_BRIDGE__" in cypher:
                return _wrap([{
                    "name": "Hub",
                    "fqn": "com.Hub",
                    "layers": ["presentation", "business", "data_access"],
                }])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("myrepo")
        bridges = [i for i in report.insights if i.category == "bridge"]
        assert len(bridges) == 1
        assert bridges[0].severity == "info"
        assert "Hub" in bridges[0].title or "Hub" in bridges[0].entities[0]

    async def test_insights_report_structure(self) -> None:
        async def router(cypher: str, params: dict) -> QueryResultWrapper:
            if "__GRAPH_INSIGHTS_Q_STATS__" in cypher:
                return _wrap([{
                    "class_count": 0,
                    "module_count": 0,
                    "calls_same_repo": 0,
                    "imports_same_repo": 0,
                }])
            return _wrap([])

        svc = GraphInsightsService(_store_with_router(router))
        report = await svc.analyze("r1")
        d = report.to_dict()
        assert set(d.keys()) == {"insights", "graph_stats", "analyzed_at"}
        assert isinstance(d["insights"], list)
        assert isinstance(d["graph_stats"], dict)
        assert isinstance(d["analyzed_at"], str)

        item = InsightItem(
            category="isolated",
            severity="warning",
            title="t",
            description="d",
            entities=["e"],
            suggestion="s",
        )
        idict = item.to_dict()
        assert set(idict.keys()) == {f.name for f in fields(InsightItem)}
