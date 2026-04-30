"""Tests for ImportanceTier filtering in WikiStructurePlanner."""

from __future__ import annotations

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.models import EntityStrategy, ImportanceTier, PageType
from wiki.structure_planner import WikiStructurePlanner


def _make_node(uid: str, label: NodeLabel, name: str, **extra: object) -> GraphNode:
    props: dict = {"name": name, **extra}
    return GraphNode(uid=uid, label=label, properties=props)


class FakeGraph:
    def __init__(self, children_map: dict[str, list[GraphNode]] | None = None) -> None:
        self._children = children_map or {}

    async def find_node_by_path(self, repository: str, path: str) -> GraphNode | None:
        return None

    async def find_node_by_fqn(self, repository: str, fqn: str) -> GraphNode | None:
        return None

    async def find_children(self, repository: str, parent_uid: str) -> list[GraphNode]:
        return self._children.get(parent_uid, [])

    async def find_top_level_modules(self, repository: str) -> list[GraphNode]:
        return self._children.get("root", [])

    async def list_repository_modules(self, repository: str) -> list[GraphNode]:
        return []

    async def find_module_import_edges(self, repository: str) -> list:
        return []

    async def find_repository_calls_edges(self, repository: str) -> list:
        return []


@pytest.mark.asyncio
async def test_skeleton_entities_excluded_from_module_tree() -> None:
    """SKELETON-tier classes should not generate pages in _build_module_tree."""
    cls_core = _make_node("c1", NodeLabel.CLASS, "CoreService", methods_count=10)
    cls_skeleton = _make_node("c2", NodeLabel.CLASS, "TinyEnum", methods_count=0, start_line=1, end_line=5)
    module = _make_node("m1", NodeLabel.MODULE, "mymodule", path="mymodule")

    graph = FakeGraph(children_map={"m1": [cls_core, cls_skeleton]})
    planner = WikiStructurePlanner(graph)

    tiers = {
        "CoreService": ImportanceTier.CORE,
        "TinyEnum": ImportanceTier.SKELETON,
    }
    from wiki.models import ScopeParam
    scope = ScopeParam(scope_type="module", value="mymodule")

    # Without tier filtering: mock resolve to return our module
    class GraphWithResolve(FakeGraph):
        async def find_node_by_path(self, repository: str, path: str) -> GraphNode | None:
            if path == "mymodule":
                return module
            return None

    planner2 = WikiStructurePlanner(GraphWithResolve(children_map={"m1": [cls_core, cls_skeleton]}))
    structure = await planner2.plan("repo", scope, importance_tiers=tiers)

    page_titles = [c.title for c in structure.root.children]
    assert "CoreService" in page_titles
    assert "TinyEnum" not in page_titles


@pytest.mark.asyncio
async def test_no_tiers_means_no_filtering() -> None:
    """When importance_tiers is None, no entities are filtered."""
    cls1 = _make_node("c1", NodeLabel.CLASS, "A", methods_count=5)
    cls2 = _make_node("c2", NodeLabel.CLASS, "B", methods_count=5)
    module = _make_node("m1", NodeLabel.MODULE, "mod", path="mod")

    class GraphWithResolve(FakeGraph):
        async def find_node_by_path(self, repository: str, path: str) -> GraphNode | None:
            if path == "mod":
                return module
            return None

    planner = WikiStructurePlanner(GraphWithResolve(children_map={"m1": [cls1, cls2]}))
    from wiki.models import ScopeParam
    scope = ScopeParam(scope_type="module", value="mod")

    structure = await planner.plan("repo", scope)
    assert len(structure.root.children) == 2


@pytest.mark.asyncio
async def test_skeleton_modules_excluded_from_repo_plan() -> None:
    """SKELETON modules should not appear in repo overview."""
    m1 = _make_node("m1", NodeLabel.MODULE, "coremod", path="coremod")
    m2 = _make_node("m2", NodeLabel.MODULE, "utilmod", path="utilmod")

    graph = FakeGraph(children_map={"root": [m1, m2], "m1": [], "m2": []})
    planner = WikiStructurePlanner(graph)
    from wiki.models import ScopeParam
    scope = ScopeParam(scope_type="repo", value=None)

    tiers = {"coremod": ImportanceTier.CORE, "utilmod": ImportanceTier.SKELETON}
    structure = await planner.plan("repo", scope, importance_tiers=tiers)

    child_titles = [c.title for c in structure.root.children]
    assert "coremod" in child_titles
    assert "utilmod" not in child_titles
