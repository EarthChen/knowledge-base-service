"""Unit tests for wiki.data_collector — T1.3b DataCollector."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.data_collector import DataCollectorPort, PageData, WikiDataCollector
from wiki.models import SourceLocation


def _fn(uid: str, name: str, start: int, file_path: str = "pkg/mod.py") -> GraphNode:
    return GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": name,
            "file": file_path,
            "start_line": start,
            "end_line": start + 2,
            "fqn": f"pkg.mod.{name}",
        },
        uid=uid,
    )


def _class_node(
    uid: str,
    name: str,
    file_path: str,
    start_line: int,
    end_line: int,
    fqn: str,
    *,
    business_summary: str | None = None,
) -> GraphNode:
    props: dict[str, str | int | float | list[str]] = {
        "name": name,
        "file": file_path,
        "start_line": start_line,
        "end_line": end_line,
        "fqn": fqn,
    }
    if business_summary is not None:
        props["business_summary"] = business_summary
    return GraphNode(label=NodeLabel.CLASS, properties=props, uid=uid)


def _module_node(uid: str, path: str, name: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.MODULE,
        properties={"path": path, "name": name},
        uid=uid,
    )


def _wdc(graph: DataCollectorPort) -> WikiDataCollector:
    w, e = inject_wiki_embedding()
    return WikiDataCollector(graph, w, e)


def _edge(
    et: EdgeType,
    src: str,
    tgt: str,
    *,
    frequency: int | None = None,
) -> GraphEdge:
    props: dict[str, str | int | float] = {}
    if frequency is not None:
        props["frequency"] = frequency
    return GraphEdge(edge_type=et, source_uid=src, target_uid=tgt, properties=props)


class TestCollectClassData:
    async def test_collect_class_data(self) -> None:
        cls = _class_node(
            "class:main.py:UserService:10",
            "UserService",
            "src/UserService.java",
            10,
            200,
            "com.example.UserService",
        )
        m1 = _fn("fn1", "getName", 20)
        m2 = _fn("fn2", "setName", 40)
        field_edge = _edge(EdgeType.USES_TYPE, cls.uid, "type:StringNode")
        inh = _edge(EdgeType.INHERITS, cls.uid, "class:Base")

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(
            return_value=[
                inh,
                field_edge,
                _edge(EdgeType.CONTAINS, cls.uid, m1.uid),
                _edge(EdgeType.CONTAINS, cls.uid, m2.uid),
            ]
        )
        graph.find_children = AsyncMock(return_value=[m1, m2])

        collector = _wdc(graph)
        page: PageData = await collector.collect("repo-a", cls)

        assert page.node == cls
        assert {m.uid for m in page.methods} == {m1.uid, m2.uid}
        assert page.children == []
        assert any(e.edge_type == EdgeType.INHERITS for e in page.edges)
        assert page.source_location.fqn == "com.example.UserService"
        assert page.source_location.file_path == "src/UserService.java"
        graph.find_children.assert_awaited_once_with("repo-a", cls.uid)


class TestCollectModuleData:
    async def test_collect_module_data(self) -> None:
        mod = _module_node("mod:pkg/service", "pkg/service.py", "service")
        c1 = _class_node("c1", "A", "a.py", 1, 10, "pkg.A")
        f1 = _fn("f1", "run", 3, file_path="pkg/run.py")

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(
            return_value=[
                _edge(EdgeType.CONTAINS, mod.uid, c1.uid),
                _edge(EdgeType.CONTAINS, mod.uid, f1.uid),
            ]
        )
        graph.find_children = AsyncMock(return_value=[c1, f1])

        collector = _wdc(graph)
        page = await collector.collect("repo-b", mod)

        assert page.node == mod
        assert {child.uid for child in page.children} == {c1.uid, f1.uid}
        assert page.methods == []


class TestEdgePrioritization:
    async def test_edge_prioritization(self) -> None:
        center = _class_node("center", "X", "f.py", 1, 2, "p.X")
        inherits = [
            _edge(EdgeType.INHERITS, center.uid, f"parent{i}")
            for i in range(3)
        ]
        calls = [
            _edge(EdgeType.CALLS, center.uid, f"callee{i}", frequency=i + 1) for i in range(30)
        ]
        imports = [
            _edge(EdgeType.IMPORTS, center.uid, f"imp{i}", frequency=i + 1) for i in range(15)
        ]
        extra = [_edge(EdgeType.USES_TYPE, center.uid, f"type{i}") for i in range(2)]

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(
            return_value=inherits + calls + imports + extra
        )
        graph.find_children = AsyncMock(return_value=[])

        collector = _wdc(graph)
        page = await collector.collect("r", center)

        types_order = [e.edge_type for e in page.edges]

        # All INHERITS first
        first_non_inherit = next(
            (i for i, t in enumerate(types_order) if t != EdgeType.INHERITS),
            len(types_order),
        )
        assert all(t == EdgeType.INHERITS for t in types_order[:first_non_inherit])
        assert first_non_inherit == 3

        # Next block: CALLS (top 10 by frequency → callees 29..20)
        calls_block = [
            e
            for e in page.edges
            if e.edge_type == EdgeType.CALLS and e.properties.get("summarized") is not True
        ]
        assert len(calls_block) == 10
        assert {e.target_uid for e in calls_block} == {f"callee{i}" for i in range(20, 30)}

        # IMPORTS next (top 10)
        after_calls_idx = next(
            i for i, e in enumerate(page.edges) if e.edge_type == EdgeType.IMPORTS
        )
        imports_in_order = [e for e in page.edges[after_calls_idx:] if e.edge_type == EdgeType.IMPORTS]
        detail_imports = [e for e in imports_in_order if e.properties.get("summarized") is not True]
        assert len(detail_imports) == 10
        assert {e.target_uid for e in detail_imports} == {f"imp{i}" for i in range(5, 15)}

        # USES_TYPE summarized as a single rollup
        summarized = [
            e
            for e in page.edges
            if e.edge_type == EdgeType.USES_TYPE and e.properties.get("summarized") is True
        ]
        assert len(summarized) == 1
        assert summarized[0].properties.get("count") == 2


class TestNeighborTruncation:
    async def test_neighbor_truncation(self) -> None:
        center = _class_node("mid", "Mid", "m.py", 1, 5, "p.Mid")
        neighbors = [f"n{i:02d}" for i in range(20)]
        edges = [_edge(EdgeType.INHERITS, center.uid, nid, frequency=1) for nid in neighbors]

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(return_value=edges)
        graph.find_children = AsyncMock(return_value=[])

        collector = _wdc(graph)
        page = await collector.collect("r", center)

        tiers = [
            e.properties.get("neighbor_tier")
            for e in page.edges
            if e.edge_type == EdgeType.INHERITS
        ]
        assert tiers.count("full") == 5
        assert tiers.count("summary") == 15


class TestMethodGrouping:
    async def test_method_grouping(self) -> None:
        cls = _class_node("big", "Big", "b.py", 1, 400, "p.Big")
        methods = []
        for i in range(30):
            cat = "accessors" if i % 3 == 0 else "workers"
            methods.append(
                GraphNode(
                    label=NodeLabel.FUNCTION,
                    properties={
                        "name": f"m{i}",
                        "file": "b.py",
                        "start_line": 10 + i,
                        "end_line": 11 + i,
                        "fqn": f"p.Big.m{i}",
                        "category": cat,
                    },
                    uid=f"m{i}",
                )
            )

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(
            return_value=[_edge(EdgeType.CONTAINS, cls.uid, m.uid) for m in methods]
        )
        graph.find_children = AsyncMock(return_value=methods)

        collector = _wdc(graph)
        page = await collector.collect("r", cls)

        assert len(page.methods) == 30
        names = [str(m.properties.get("name")) for m in page.methods]
        assert len(set(names)) == 30


class TestEmptyNode:
    async def test_empty_node(self) -> None:
        cls = _class_node("solo", "Solo", "s.py", 1, 2, "p.Solo")

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(return_value=[])
        graph.find_children = AsyncMock(return_value=[])

        collector = _wdc(graph)
        page = await collector.collect("r", cls)

        assert page.edges == []


class TestSourceLocation:
    async def test_source_location_extraction(self) -> None:
        cls = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "fqn": "app.User",
                "file": "src/User.kt",
                "start_line": 40,
                "end_line": 120,
                "name": "User",
            },
            uid="uid-user",
        )

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(return_value=[])
        graph.find_children = AsyncMock(return_value=[])

        collector = _wdc(graph)
        page = await collector.collect("repo-x", cls)

        expected = SourceLocation(
            file_path="src/User.kt",
            start_line=40,
            end_line=120,
            fqn="app.User",
            repository="repo-x",
        )
        assert page.source_location == expected


class TestMethodLocations:
    async def test_method_locations(self) -> None:
        cls = _class_node("c-loc", "Loc", "loc.py", 5, 50, "p.Loc")
        m_a = _fn("ma", "alpha", 60)
        m_b = _fn("mb", "beta", 80, file_path="loc.py")

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(
            return_value=[_edge(EdgeType.CONTAINS, cls.uid, m.uid) for m in (m_a, m_b)]
        )
        graph.find_children = AsyncMock(return_value=[m_a, m_b])

        collector = _wdc(graph)
        page = await collector.collect("repo-y", cls)

        by_fqn = {loc.fqn: loc for loc in page.method_locations}
        assert by_fqn["pkg.mod.alpha"].start_line == 60
        assert by_fqn["pkg.mod.beta"].file_path == "loc.py"


class TestBusinessSummary:
    async def test_business_summary_present(self) -> None:
        cls = _class_node(
            "biz",
            "Biz",
            "b.py",
            1,
            3,
            "p.Biz",
            business_summary="Handles checkout.",
        )

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(return_value=[])
        graph.find_children = AsyncMock(return_value=[])

        collector = _wdc(graph)
        page = await collector.collect("r", cls)

        assert page.business_summary == "Handles checkout."

    async def test_business_summary_absent(self) -> None:
        cls = _class_node("nobiz", "NoBiz", "n.py", 1, 3, "p.NoBiz")

        graph = AsyncMock(spec=DataCollectorPort)
        graph.find_edges = AsyncMock(return_value=[])
        graph.find_children = AsyncMock(return_value=[])

        collector = _wdc(graph)
        page = await collector.collect("r", cls)

        assert page.business_summary is None
