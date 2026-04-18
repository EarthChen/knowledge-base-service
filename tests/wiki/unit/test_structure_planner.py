"""Unit tests for wiki.structure_planner — T1.3 StructurePlanner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.models import PageType, ScopeParam, parse_scope
from wiki.structure_planner import GraphQueryPort, WikiScopeError, WikiStructurePlanner


def _module(uid: str, path: str, name: str) -> GraphNode:
    return GraphNode(
        label=NodeLabel.MODULE,
        properties={"path": path, "name": name},
        uid=uid,
    )


def _class_node(uid: str, fqn: str, name: str, file_path: str = "src/Foo.java") -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS,
        properties={"fqn": fqn, "name": name, "file": file_path, "start_line": 1},
        uid=uid,
    )


class TestScopeResolution:
    async def test_resolve_module_by_path(self) -> None:
        expected = _module("m1", "src/service.py", "service")
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=expected)
        graph.find_node_by_fqn = AsyncMock(return_value=None)
        graph.find_children = AsyncMock(return_value=[])

        planner = WikiStructurePlanner(graph)
        scope = parse_scope("module:src/service.py")
        result = await planner.plan("my-repo", scope)

        graph.find_node_by_path.assert_awaited_once_with("my-repo", "src/service.py")
        graph.find_node_by_fqn.assert_not_called()
        assert result.repository == "my-repo"
        assert result.root.path == "src/service.py"
        assert result.root.title == "service"
        assert result.root.page_type == PageType.MODULE_OVERVIEW
        assert result.total_pages == 1

    async def test_resolve_class_by_fqn(self) -> None:
        cls = _class_node("c1", "com.example.UserService", "UserService")
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=None)
        graph.find_node_by_fqn = AsyncMock(return_value=cls)

        planner = WikiStructurePlanner(graph)
        scope = parse_scope("class:com.example.UserService")
        result = await planner.plan("my-repo", scope)

        graph.find_node_by_path.assert_awaited_once_with("my-repo", "com.example.UserService")
        graph.find_node_by_fqn.assert_awaited_once_with("my-repo", "com.example.UserService")
        assert result.root.page_type == PageType.CLASS_DETAIL
        assert result.root.path == "com.example.UserService"
        assert result.root.title == "UserService"
        assert result.root.children == []
        assert result.total_pages == 1

    async def test_resolve_fallback_path_to_fqn(self) -> None:
        mod = _module("m1", "src/foo.py", "foo")
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=None)
        graph.find_node_by_fqn = AsyncMock(return_value=mod)
        graph.find_children = AsyncMock(return_value=[])

        planner = WikiStructurePlanner(graph)
        scope = ScopeParam(scope_type="module", value="src/foo.py")
        result = await planner.plan("repo-x", scope)

        graph.find_node_by_path.assert_awaited_once_with("repo-x", "src/foo.py")
        graph.find_node_by_fqn.assert_awaited_once_with("repo-x", "src/foo.py")
        assert result.root.path == "src/foo.py"
        assert result.total_pages == 1

    async def test_resolve_no_match(self) -> None:
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=None)
        graph.find_node_by_fqn = AsyncMock(return_value=None)

        planner = WikiStructurePlanner(graph)
        scope = parse_scope("module:missing/path.py")

        with pytest.raises(WikiScopeError, match="scope"):
            await planner.plan("my-repo", scope)

    async def test_module_scope_wrong_node_label_raises(self) -> None:
        cls = _class_node("c1", "com.example.X", "X")
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=cls)

        planner = WikiStructurePlanner(graph)
        with pytest.raises(WikiScopeError, match="module"):
            await planner.plan("r", parse_scope("module:com.example.X"))

    async def test_class_scope_wrong_node_label_raises(self) -> None:
        mod = _module("m1", "src/x.py", "x")
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=mod)

        planner = WikiStructurePlanner(graph)
        with pytest.raises(WikiScopeError, match="class"):
            await planner.plan("r", parse_scope("class:src/x.py"))

    async def test_unsupported_scope_type_raises(self) -> None:
        graph = AsyncMock(spec=GraphQueryPort)
        planner = WikiStructurePlanner(graph)
        with pytest.raises(WikiScopeError, match="Unsupported"):
            await planner.plan("r", ScopeParam(scope_type="package", value="pkg"))


class TestPageTree:
    async def test_build_page_tree_flat(self) -> None:
        root_mod = _module("root", "pkg/__init__.py", "pkg")
        children = [
            _class_node(f"c{i}", f"pkg.C{i}", f"C{i}") for i in range(5)
        ]
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=root_mod)
        graph.find_node_by_fqn = AsyncMock(return_value=None)
        graph.find_children = AsyncMock(return_value=children)

        planner = WikiStructurePlanner(graph)
        result = await planner.plan(
            "r1",
            parse_scope("module:pkg/__init__.py"),
        )

        assert len(result.root.children) == 5
        titles = sorted(c.title for c in result.root.children)
        assert titles == ["C0", "C1", "C2", "C3", "C4"]
        for child in result.root.children:
            assert child.page_type == PageType.CLASS_DETAIL
            assert child.children == []
        # root + 5 class pages
        assert result.total_pages == 6

    async def test_build_page_tree_nested(self) -> None:
        outer = _module("m-outer", "src/api/__init__.py", "api")
        inner = _module("m-inner", "src/api/v1/__init__.py", "v1")
        leaf_class = _class_node("c-leaf", "com.app.api.v1.Handler", "Handler")

        graph = AsyncMock(spec=GraphQueryPort)

        async def children_for(repo: str, parent_uid: str) -> list[GraphNode]:
            if parent_uid == "m-outer":
                return [inner]
            if parent_uid == "m-inner":
                return [leaf_class]
            return []

        graph.find_node_by_path = AsyncMock(return_value=outer)
        graph.find_node_by_fqn = AsyncMock(return_value=None)
        graph.find_children = AsyncMock(side_effect=children_for)

        planner = WikiStructurePlanner(graph)
        result = await planner.plan("r2", parse_scope("module:src/api/__init__.py"))

        assert result.root.path == "src/api/__init__.py"
        assert len(result.root.children) == 1
        inner_node = result.root.children[0]
        assert inner_node.title == "v1"
        assert inner_node.page_type == PageType.MODULE_OVERVIEW
        assert len(inner_node.children) == 1
        leaf_wiki = inner_node.children[0]
        assert leaf_wiki.title == "Handler"
        assert leaf_wiki.page_type == PageType.CLASS_DETAIL
        assert result.total_pages == 3

    async def test_repo_scope_lists_modules(self) -> None:
        mods = [
            _module("a", "src/a.py", "a"),
            _module("b", "src/b.py", "b"),
            _module("c", "pkg/mod.py", "mod"),
        ]
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_top_level_modules = AsyncMock(return_value=mods)

        planner = WikiStructurePlanner(graph)
        result = await planner.plan("big-repo", parse_scope("repo"))

        graph.find_top_level_modules.assert_awaited_once_with("big-repo")
        assert result.repository == "big-repo"
        assert result.root.page_type == PageType.REPO_OVERVIEW
        assert result.root.path == "/"
        titles = sorted(n.title for n in result.root.sorted_children())
        assert titles == ["a", "b", "mod"]
        paths = sorted(n.path for n in result.root.sorted_children())
        assert paths == ["pkg/mod.py", "src/a.py", "src/b.py"]
        assert result.total_pages == 4

    async def test_build_page_tree_function_child_is_api_reference(self) -> None:
        root_mod = _module("mod-root", "svc/main.py", "main")
        func = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={"name": "run", "file": "svc/main.py", "start_line": 42},
            uid="fn-1",
        )
        graph = AsyncMock(spec=GraphQueryPort)
        graph.find_node_by_path = AsyncMock(return_value=root_mod)
        graph.find_node_by_fqn = AsyncMock(return_value=None)
        graph.find_children = AsyncMock(return_value=[func])

        planner = WikiStructurePlanner(graph)
        result = await planner.plan("r", parse_scope("module:svc/main.py"))

        assert len(result.root.children) == 1
        leaf = result.root.children[0]
        assert leaf.page_type == PageType.API_REFERENCE
        assert leaf.path == "svc/main.py#run"
        assert leaf.title == "run"


class TestStructurePathHelpers:
    """Covers MODULE path fallback and CLASS path without `fqn` via WikiStructurePlanner."""

    def test_module_without_path_property_uses_name(self) -> None:
        planner = WikiStructurePlanner(AsyncMock(spec=GraphQueryPort))
        node = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "orphan"},
            uid="mod-u",
        )
        path = planner._structure_path(node)
        title = planner._node_title(node)
        assert path == "orphan"
        assert title == "orphan"

    def test_class_without_fqn_uses_name(self) -> None:
        planner = WikiStructurePlanner(AsyncMock(spec=GraphQueryPort))
        node = GraphNode(
            label=NodeLabel.CLASS,
            properties={"name": "Bare", "file": "src/Bare.java", "start_line": 1},
            uid="class-u",
        )
        assert planner._structure_path(node) == "Bare"

    def test_module_title_prefers_path_when_name_missing(self) -> None:
        planner = WikiStructurePlanner(AsyncMock(spec=GraphQueryPort))
        node = GraphNode(
            label=NodeLabel.MODULE,
            properties={"path": "only/path.py"},
            uid="mod-path-only",
        )
        assert planner._node_title(node) == "only/path.py"
