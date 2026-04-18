"""Unit tests for wiki.incremental.WikiIncrementalUpdater (TDD)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import EdgeType, GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData, WikiDataCollector
from wiki.incremental import IncrementalUpdateResult, WikiIncrementalUpdater, _wiki_path_for_node
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiConfig,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
)


def _cls(
    uid: str,
    name: str,
    file_path: str,
    *,
    module_uid: str | None = None,
    module_path: str | None = None,
) -> GraphNode:
    props: dict[str, str | int | float | list[str]] = {
        "name": name,
        "file": file_path,
        "start_line": 1,
        "end_line": 10,
        "fqn": f"x.{name}",
    }
    if module_uid:
        props["module_uid"] = module_uid
    if module_path:
        props["module_path"] = module_path
    return GraphNode(label=NodeLabel.CLASS, properties=props, uid=uid)


def _mod(uid: str, path: str) -> GraphNode:
    return GraphNode(label=NodeLabel.MODULE, properties={"path": path, "name": path.split("/")[-1]}, uid=uid)


def _page_data(node: GraphNode) -> PageData:
    return PageData(
        node=node,
        edges=[],
        children=[],
        source_location=SourceLocation(
            file_path=str(node.properties.get("file") or ""),
            start_line=1,
            end_line=2,
            fqn=str(node.properties.get("fqn") or ""),
            repository="r1",
        ),
        method_locations=[],
        business_summary=None,
        methods=[],
    )


def _make_updater(
    graph: AsyncMock,
    collector: WikiDataCollector | MagicMock | AsyncMock,
    cache: MagicMock | None = None,
) -> WikiIncrementalUpdater:
    composer = WikiComposer(None, WikiContextBuilder(None))
    ctx = WikiContextBuilder(None)
    c = cache or MagicMock()
    c.invalidate = MagicMock(return_value=0)
    return WikiIncrementalUpdater(graph, composer, collector, ctx, c)  # type: ignore[arg-type]


@pytest.fixture
def config() -> WikiConfig:
    return WikiConfig(repository="r1", mode="structure", format="markdown", language="en")


class TestWikiIncrementalUpdater:
    async def test_diff_single_file_modified(self, config: WikiConfig) -> None:
        node_a = _cls("uA", "Alpha", "src/A.java")
        graph = AsyncMock()
        graph.get_graph_version = AsyncMock(return_value=5)
        graph.increment_graph_version = AsyncMock(return_value=6)
        graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
        graph.find_neighbors = AsyncMock(return_value=[])

        collector = AsyncMock()
        collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

        updater = _make_updater(graph, collector)
        res = await updater.update_from_diff(
            "r1",
            [("M", "src/A.java", "src/A.java")],
            config,
            previous_glossary={},
        )
        assert isinstance(res, IncrementalUpdateResult)
        assert res.affected_pages == ["classes/Alpha.md"]
        assert res.graph_version == 6
        collector.collect.assert_awaited_once()
        graph.increment_graph_version.assert_awaited_once()

    async def test_diff_file_deleted(self, config: WikiConfig) -> None:
        dead = _cls("uDead", "Dead", "src/Old.java")
        graph = AsyncMock()
        graph.get_graph_version = AsyncMock(return_value=3)
        graph.increment_graph_version = AsyncMock(return_value=4)
        graph.find_nodes_by_file = AsyncMock(return_value=[dead])
        graph.find_neighbors = AsyncMock(return_value=[])

        collector = AsyncMock()
        collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

        updater = _make_updater(graph, collector)
        res = await updater.update_from_diff("r1", [("D", "src/Old.java", None)], config)
        assert res.affected_pages == []
        collector.collect.assert_not_called()

    async def test_diff_neighbor_expansion(self, config: WikiConfig) -> None:
        node_a = _cls("uA", "Alpha", "src/A.java")
        node_b = _cls("uB", "Beta", "src/B.java")

        graph = AsyncMock()
        graph.get_graph_version = AsyncMock(return_value=1)
        graph.increment_graph_version = AsyncMock(return_value=2)

        async def nodes_by_file(repo: str, fp: str) -> list[GraphNode]:
            if fp == "src/A.java":
                return [node_a]
            return []

        graph.find_nodes_by_file = AsyncMock(side_effect=nodes_by_file)

        async def neigh(uid: str, ets: list[str]) -> list[GraphNode]:
            if uid == "uA":
                return [node_b]
            return []

        graph.find_neighbors = AsyncMock(side_effect=neigh)

        collector = AsyncMock()
        collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

        updater = _make_updater(graph, collector)
        res = await updater.update_from_diff(
            "r1",
            [("M", "src/A.java", "src/A.java")],
            config,
            previous_glossary={},
        )
        assert sorted(res.affected_pages) == ["classes/Alpha.md", "classes/Beta.md"]
        assert collector.collect.await_count == 2

    async def test_diff_module_threshold(self, config: WikiConfig) -> None:
        mod_uid = "module:pkg/stuff"
        classes = [
            _cls(f"c{i}", f"C{i}", f"src/m/C{i}.java", module_uid=mod_uid, module_path="pkg/stuff")
            for i in range(10)
        ]
        graph = AsyncMock()
        graph.get_graph_version = AsyncMock(return_value=0)
        graph.increment_graph_version = AsyncMock(return_value=1)

        changed_paths = [f"src/m/C{i}.java" for i in range(4)]

        async def nodes_by_file(repo: str, fp: str) -> list[GraphNode]:
            for i in range(10):
                if fp == f"src/m/C{i}.java":
                    return [classes[i]]
            return []

        graph.find_nodes_by_file = AsyncMock(side_effect=nodes_by_file)

        async def neigh(uid: str, ets: list[str]) -> list[GraphNode]:
            if uid == mod_uid and EdgeType.CONTAINS.value in ets:
                return classes
            return []

        graph.find_neighbors = AsyncMock(side_effect=neigh)

        collector = AsyncMock()
        collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

        updater = _make_updater(graph, collector)
        cf = [("M", p, p) for p in changed_paths]
        res = await updater.update_from_diff("r1", cf, config, previous_glossary={})

        assert "modules/pkg_stuff.md" in res.affected_pages
        assert collector.collect.await_count >= 5

    async def test_glossary_drift_trigger(self, config: WikiConfig) -> None:
        updater = _make_updater(AsyncMock(), AsyncMock())
        old = {f"t{i}": "a" for i in range(10)}
        new = {f"t{i}": ("b" if i < 3 else "a") for i in range(10)}
        assert await updater._check_glossary_drift(old, new) is True

    async def test_glossary_stable(self, config: WikiConfig) -> None:
        updater = _make_updater(AsyncMock(), AsyncMock())
        old = {f"t{i}": "x" for i in range(10)}
        new = dict(old)
        new["t0"] = "y"
        assert await updater._check_glossary_drift(old, new) is False

    async def test_broken_ref_cleanup(self, config: WikiConfig) -> None:
        updater = _make_updater(AsyncMock(), AsyncMock())
        meta = WikiPageMetadata(node_count=1, edge_count=0)
        p = WikiPage(
            path="classes/X.md",
            title="X",
            page_type=PageType.CLASS_DETAIL,
            content="See [gone](classes/Missing.md) ok.",
            diagrams=[WikiDiagram(diagram_type=DiagramType.FLOWCHART, content="", title="")],
            source_locations=[],
            metadata=meta,
        )
        fixed, n = updater._fix_broken_refs([p], {"classes/Missing.md"})
        assert n == 1
        assert "Missing.md" not in fixed[0].content
        assert "gone" in fixed[0].content

    async def test_version_stamp_increment(self, config: WikiConfig) -> None:
        node_a = _cls("uA", "Alpha", "src/A.java")
        graph = AsyncMock()
        graph.get_graph_version = AsyncMock(return_value=10)
        graph.increment_graph_version = AsyncMock(return_value=11)
        graph.find_nodes_by_file = AsyncMock(return_value=[node_a])
        graph.find_neighbors = AsyncMock(return_value=[])

        collector = AsyncMock()
        collector.collect = AsyncMock(side_effect=lambda repo, n: _page_data(n))

        updater = _make_updater(graph, collector)
        res = await updater.update_from_diff("r1", [("M", "x", "y")], config)
        assert res.graph_version == 11

    async def test_map_files_to_nodes(self, config: WikiConfig) -> None:
        n1 = _cls("a", "A", "f1.java")
        graph = AsyncMock()
        graph.find_nodes_by_file = AsyncMock(return_value=[n1])
        updater = _make_updater(graph, AsyncMock())
        out = await updater._map_files_to_nodes("r1", ["f1.java"])
        assert out == {"a"}

    async def test_expand_neighbors_1hop(self, config: WikiConfig) -> None:
        graph = AsyncMock()
        na = _cls("A", "A", "a.java")
        nb = _cls("B", "B", "b.java")
        nc = _cls("C", "C", "c.java")

        async def neigh(uid: str, ets: list[str]) -> list[GraphNode]:
            if uid == "A":
                return [nb]
            if uid == "B":
                return [nc]
            return []

        graph.find_neighbors = AsyncMock(side_effect=neigh)
        updater = _make_updater(graph, AsyncMock())
        uid_map: dict[str, GraphNode] = {"A": na}
        expanded = await updater._expand_neighbors({"A"}, uid_map)
        assert expanded == {"A", "B"}
        assert "C" not in expanded

    async def test_resolve_class_page_path(self, config: WikiConfig) -> None:
        updater = _make_updater(AsyncMock(), AsyncMock())
        n = _cls("x", "FooBar", "f.java")
        m = updater._resolve_page_paths([n])
        assert m[n.uid] == "classes/FooBar.md"

    async def test_resolve_module_page_path(self, config: WikiConfig) -> None:
        updater = _make_updater(AsyncMock(), AsyncMock())
        n = _mod("m1", "com/example/pkg")
        m = updater._resolve_page_paths([n])
        assert m[n.uid] == "modules/com_example_pkg.md"

    async def test_empty_diff(self, config: WikiConfig) -> None:
        graph = AsyncMock()
        graph.get_graph_version = AsyncMock(return_value=99)
        graph.increment_graph_version = AsyncMock(return_value=100)
        collector = AsyncMock()
        updater = _make_updater(graph, collector)
        res = await updater.update_from_diff("r1", [], config)
        assert res.affected_pages == []
        assert res.graph_version == 99
        graph.increment_graph_version.assert_not_called()

    async def test_concurrent_version_increment(self, config: WikiConfig) -> None:
        graph = AsyncMock()
        ctr = {"v": 0}

        async def bump(repo: str) -> int:
            await asyncio.sleep(0)
            ctr["v"] += 1
            return ctr["v"]

        graph.increment_graph_version = AsyncMock(side_effect=bump)
        updater = _make_updater(graph, AsyncMock())

        await asyncio.gather(*[updater._increment_version("r1") for _ in range(10)])
        assert ctr["v"] == 10


class TestWikiPathHelpers:
    def test_wiki_path_matches_composer_slug_rules(self) -> None:
        n = _mod("m", "a/b/c-d")
        assert _wiki_path_for_node(n, PageType.MODULE_OVERVIEW) == "modules/a_b_c-d.md"
