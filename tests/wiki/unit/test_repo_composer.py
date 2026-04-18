"""Unit tests for wiki.repo_composer — full repository wiki composition."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData
from wiki.exporter import WikiExporter
from wiki.models import PageType, SourceLocation, WikiConfig, WikiPageMetadata
from wiki.repo_composer import ArchitectureLayer, WikiRepoComposer
from wiki.structure_planner import GraphQueryPort


def _loc(file_path: str, start: int, end: int, fqn: str, repo: str = "demo") -> SourceLocation:
    return SourceLocation(file_path=file_path, start_line=start, end_line=end, fqn=fqn, repository=repo)


def _module(uid: str, path: str, name: str | None = None) -> GraphNode:
    return GraphNode(
        label=NodeLabel.MODULE,
        properties={"path": path, "name": name or path.strip("/").split("/")[-1]},
        uid=uid,
    )


def _fn(uid: str, name: str, file_path: str, line: int, module_uid: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.FUNCTION,
        properties={
            "name": name,
            "file": file_path,
            "start_line": line,
            "end_line": line + 2,
            "fqn": f"x.{name}",
            "module_uid": module_uid,
        },
        uid=uid,
    )


def _meta() -> WikiPageMetadata:
    return WikiPageMetadata(node_count=1, edge_count=0, generation_mode="structure", fallback_tier=3)


def _make_graph_mock() -> AsyncMock:
    g = AsyncMock(spec=GraphQueryPort)
    g.find_node_by_path = AsyncMock(return_value=None)
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.find_children = AsyncMock(return_value=[])
    g.find_top_level_modules = AsyncMock(return_value=[])
    g.list_repository_modules = AsyncMock(return_value=[])
    g.find_module_import_edges = AsyncMock(return_value=[])
    g.find_repository_calls_edges = AsyncMock(return_value=[])
    return g


@pytest.fixture
def wiki_config() -> WikiConfig:
    return WikiConfig(repository="demo", mode="structure")


class TestComposeRepoWiki:
    @pytest.mark.asyncio
    async def test_compose_repo_discovers_modules(self, wiki_config: WikiConfig) -> None:
        m1 = _module("m1", "a/", "a")
        m2 = _module("m2", "b/", "b")
        m3 = _module("m3", "c/", "c")
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[m1, m2, m3])
        graph.find_children = AsyncMock(return_value=[])

        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()

        async def collect_side(repo: str, node: GraphNode) -> PageData:
            name = str(node.properties.get("name") or "")
            return PageData(
                node=node,
                edges=[],
                children=[],
                source_location=_loc(f"{name}/x", 1, 1, name),
                method_locations=[],
                business_summary=None,
                methods=[],
            )

        collector.collect = AsyncMock(side_effect=collect_side)
        repo_composer = WikiRepoComposer(
            graph=graph,
            composer=composer,
            collector=collector,
            exporter=WikiExporter(),
            context_builder=WikiContextBuilder(),
        )
        pages, structure = await repo_composer.compose_repo_wiki("demo", wiki_config)
        mod_paths = {p.path for p in pages if p.page_type == PageType.MODULE_OVERVIEW}
        assert any("a" in p for p in mod_paths)
        assert any("b" in p for p in mod_paths)
        assert any("c" in p for p in mod_paths)
        assert structure.repository == "demo"
        assert structure.total_pages >= 3

    @pytest.mark.asyncio
    async def test_compose_repo_architecture_classification(self, wiki_config: WikiConfig) -> None:
        api_mod = _module("ma", "controller/UserApi", "UserApi")
        svc_mod = _module("mb", "service/UserService", "UserService")
        data_mod = _module("mc", "repository/UserRepo", "UserRepo")
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[api_mod, svc_mod, data_mod])
        graph.find_children = AsyncMock(return_value=[])

        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()
        collector.collect = AsyncMock(
            side_effect=lambda repo, node: PageData(
                node=node,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, str(node.properties.get("name"))),
                method_locations=[],
                business_summary=None,
                methods=[],
            )
        )
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        pages, _struct = await rc.compose_repo_wiki("demo", wiki_config)
        arch = next(p for p in pages if p.page_type == PageType.ARCHITECTURE)
        assert "API" in arch.content or "api" in arch.content.lower()
        assert "controller" in arch.content.lower() or "UserApi" in arch.content

    @pytest.mark.asyncio
    async def test_compose_repo_dependency_order(self, wiki_config: WikiConfig) -> None:
        """IMPORTS: A imports B, B imports C → generation order C, B, A."""
        mod_a = _module("ma", "pkg/a", "a")
        mod_b = _module("mb", "pkg/b", "b")
        mod_c = _module("mc", "pkg/c", "c")
        edges = [
            GraphEdge(EdgeType.IMPORTS, mod_a.uid, mod_b.uid, {}),
            GraphEdge(EdgeType.IMPORTS, mod_b.uid, mod_c.uid, {}),
        ]
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[mod_a, mod_b, mod_c])
        graph.find_module_import_edges = AsyncMock(return_value=edges)
        graph.find_children = AsyncMock(return_value=[])

        order_seen: list[str] = []

        async def collect(repo: str, node: GraphNode) -> PageData:
            order_seen.append(str(node.properties.get("path") or node.uid))
            return PageData(
                node=node,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, "x"),
                method_locations=[],
                business_summary=None,
                methods=[],
            )

        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()
        collector.collect = AsyncMock(side_effect=collect)
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        await rc.compose_repo_wiki("demo", wiki_config)
        assert order_seen.index("pkg/c") < order_seen.index("pkg/b")
        assert order_seen.index("pkg/b") < order_seen.index("pkg/a")

    @pytest.mark.asyncio
    async def test_compose_repo_overview_page(self, wiki_config: WikiConfig) -> None:
        m1 = _module("m1", "src/x", "x")
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[m1])
        graph.find_children = AsyncMock(return_value=[])
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()
        collector.collect = AsyncMock(
            return_value=PageData(
                node=m1,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, "x"),
                method_locations=[],
                business_summary=None,
                methods=[],
            )
        )
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        pages, _ = await rc.compose_repo_wiki("demo", wiki_config)
        overview = next(p for p in pages if p.page_type == PageType.REPO_OVERVIEW)
        assert overview.title.lower() == "demo" or "demo" in overview.content.lower()
        assert "module" in overview.content.lower() or "src" in overview.content.lower()

    @pytest.mark.asyncio
    async def test_compose_repo_architecture_page(self, wiki_config: WikiConfig) -> None:
        m1 = _module("m1", "api/X", "X")
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[m1])
        graph.find_children = AsyncMock(return_value=[])
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()
        collector.collect = AsyncMock(
            return_value=PageData(
                node=m1,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, "x"),
                method_locations=[],
                business_summary=None,
                methods=[],
            )
        )
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        pages, _ = await rc.compose_repo_wiki("demo", wiki_config)
        arch = next(p for p in pages if p.page_type == PageType.ARCHITECTURE)
        assert arch.diagrams
        assert "flowchart" in arch.diagrams[0].content.lower()
        assert "layer" in arch.content.lower() or "api" in arch.content.lower()

    @pytest.mark.asyncio
    async def test_compose_repo_concurrent_limit(self, wiki_config: WikiConfig) -> None:
        modules = [_module(f"m{i}", f"mod{i}/", f"mod{i}") for i in range(10)]
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=modules)
        graph.find_children = AsyncMock(return_value=[])

        in_flight = 0
        max_seen = {"n": 0}

        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())

        async def collect(repo: str, node: GraphNode) -> PageData:
            nonlocal in_flight
            in_flight += 1
            max_seen["n"] = max(max_seen["n"], in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return PageData(
                node=node,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, "x"),
                method_locations=[],
                business_summary=None,
                methods=[],
            )

        collector = MagicMock()
        collector.collect = AsyncMock(side_effect=collect)
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        await rc.compose_repo_wiki("demo", wiki_config)
        assert max_seen["n"] <= 3


class TestClassificationAndOrdering:
    def test_classify_layer_api(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod = _module("m", "src/controller/UserHandler", "UserHandler")
        assert rc.classify_layer(mod, []) == ArchitectureLayer.API

    def test_classify_layer_service(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod = _module("m", "foo/service/OrderService", "OrderService")
        assert rc.classify_layer(mod, []) == ArchitectureLayer.SERVICE

    def test_classify_layer_data(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod = _module("m", "dao/UserDao", "UserDao")
        assert rc.classify_layer(mod, []) == ArchitectureLayer.DATA

    def test_classify_layer_infra(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod = _module("m", "config/AppConfig", "AppConfig")
        assert rc.classify_layer(mod, []) == ArchitectureLayer.INFRASTRUCTURE

    def test_build_dependency_order_linear(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod_a = _module("ma", "a", "a")
        mod_b = _module("mb", "b", "b")
        mod_c = _module("mc", "c", "c")
        edges = [
            GraphEdge(EdgeType.IMPORTS, mod_a.uid, mod_b.uid, {}),
            GraphEdge(EdgeType.IMPORTS, mod_b.uid, mod_c.uid, {}),
        ]
        order = rc.build_dependency_order([mod_a, mod_b, mod_c], edges)
        assert [n.uid for n in order] == [mod_c.uid, mod_b.uid, mod_a.uid]

    def test_build_dependency_order_cycle(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod_a = _module("ma", "a", "a")
        mod_b = _module("mb", "b", "b")
        edges = [
            GraphEdge(EdgeType.IMPORTS, mod_a.uid, mod_b.uid, {}),
            GraphEdge(EdgeType.IMPORTS, mod_b.uid, mod_a.uid, {}),
        ]
        order = rc.build_dependency_order([mod_a, mod_b], edges)
        assert len(order) == 2
        assert {mod_a.uid, mod_b.uid} == {order[0].uid, order[1].uid}

    def test_detect_entry_points(self) -> None:
        graph = _make_graph_mock()
        rc = WikiRepoComposer(graph, MagicMock(), MagicMock(), WikiExporter(), WikiContextBuilder())
        mod = _module("mod1", "root", "root")
        f_main = _fn("f1", "main", "m.py", 1, mod.uid)
        f_help = _fn("f2", "help", "m.py", 10, mod.uid)
        edges = [GraphEdge(EdgeType.CALLS, f_main.uid, f_help.uid, {})]
        mixed = [mod, f_main, f_help]
        eps = rc._detect_entry_points(mixed, edges)
        assert len(eps) == 1
        assert eps[0].uid == f_main.uid

    @pytest.mark.asyncio
    async def test_compose_repo_filters_test_modules(self, wiki_config: WikiConfig) -> None:
        good = _module("m1", "src/app", "app")
        bad = _module("m2", "src/test_utils", "test_utils")
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[good, bad])
        graph.find_children = AsyncMock(return_value=[])
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()
        collector.collect = AsyncMock(
            return_value=PageData(
                node=good,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, "x"),
                method_locations=[],
                business_summary=None,
                methods=[],
            )
        )
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        pages, _ = await rc.compose_repo_wiki("demo", wiki_config)
        titles_or_paths = " ".join(p.title + p.content for p in pages)
        assert "test_utils" not in titles_or_paths or not any(
            p.page_type == PageType.MODULE_OVERVIEW and "test_utils" in p.path for p in pages
        )

    @pytest.mark.asyncio
    async def test_compose_repo_filters_vendor_modules(self, wiki_config: WikiConfig) -> None:
        good = _module("m1", "src/app", "app")
        bad = _module("m2", "vendor/lib", "lib")
        graph = _make_graph_mock()
        graph.list_repository_modules = AsyncMock(return_value=[good, bad])
        graph.find_children = AsyncMock(return_value=[])
        composer = WikiComposer(llm=None, context_builder=WikiContextBuilder())
        collector = MagicMock()
        collector.collect = AsyncMock(
            return_value=PageData(
                node=good,
                edges=[],
                children=[],
                source_location=_loc("x", 1, 1, "x"),
                method_locations=[],
                business_summary=None,
                methods=[],
            )
        )
        rc = WikiRepoComposer(graph, composer, collector, WikiExporter(), WikiContextBuilder())
        pages, _ = await rc.compose_repo_wiki("demo", wiki_config)
        assert not any("vendor" in p.path and p.page_type == PageType.MODULE_OVERVIEW for p in pages)
