"""Derives wiki directory structure from graph scope and CONTAINS edges."""

from __future__ import annotations

from typing import Protocol

from log import get_logger
from store.schema import GraphEdge, GraphNode, NodeLabel
from wiki.models import PageType, ScopeParam, WikiStructure, WikiStructureNode

log = get_logger(__name__)


class WikiScopeError(Exception):
    """Raised when the graph has no node matching the requested wiki scope."""


class GraphQueryPort(Protocol):
    """Abstraction over graph reads for structure planning (e.g. FalkorDB adapter)."""

    async def find_node_by_path(self, repository: str, path: str) -> GraphNode | None: ...

    async def find_node_by_fqn(self, repository: str, fqn: str) -> GraphNode | None: ...

    async def find_children(self, repository: str, parent_uid: str) -> list[GraphNode]: ...

    async def find_top_level_modules(self, repository: str) -> list[GraphNode]: ...

    async def list_repository_modules(self, repository: str) -> list[GraphNode]: ...

    async def find_module_import_edges(self, repository: str) -> list[GraphEdge]: ...

    async def find_repository_calls_edges(self, repository: str) -> list[GraphEdge]: ...


class WikiStructurePlanner:
    """Builds a `WikiStructure` for a repository scope using graph CONTAINS edges."""

    def __init__(self, graph: GraphQueryPort) -> None:
        self._graph = graph

    async def plan(self, repository: str, scope: ScopeParam) -> WikiStructure:
        log.info("structure_plan_start", repository=repository, scope_type=scope.scope_type, scope_value=scope.value)
        if scope.scope_type == "repo":
            return await self._plan_repo(repository)

        if scope.scope_type == "module":
            node = await self._resolve_scope_node(repository, scope.value or "")
            if node.label != NodeLabel.MODULE:
                raise WikiScopeError(
                    f"Scope type 'module' resolved to {node.label}, expected Module"
                )
            root = await self._build_module_tree(repository, node)
            structure = WikiStructure(
                repository=repository,
                root=root,
                total_pages=self._count_pages(root),
            )
            log.info("structure_plan_done", repository=repository, scope_type="module", total_pages=structure.total_pages)
            return structure

        if scope.scope_type == "class":
            node = await self._resolve_scope_node(repository, scope.value or "")
            if node.label != NodeLabel.CLASS:
                raise WikiScopeError(f"Scope type 'class' resolved to {node.label}, expected Class")
            root = self._leaf_wiki_node(node, PageType.CLASS_DETAIL)
            structure = WikiStructure(
                repository=repository,
                root=root,
                total_pages=self._count_pages(root),
            )
            log.info("structure_plan_done", repository=repository, scope_type="class", total_pages=structure.total_pages)
            return structure

        raise WikiScopeError(f"Unsupported scope type: {scope.scope_type!r}")

    async def _plan_repo(self, repository: str) -> WikiStructure:
        modules = await self._graph.find_top_level_modules(repository)
        log.info("plan_repo_modules_found", repository=repository, module_count=len(modules))
        children = [
            self._leaf_wiki_node(m, PageType.MODULE_OVERVIEW)
            for m in sorted(modules, key=self._sort_key_for_module_list)
        ]
        root = WikiStructureNode(
            path="/",
            title=repository,
            page_type=PageType.REPO_OVERVIEW,
            children=children,
        )
        structure = WikiStructure(
            repository=repository,
            root=root,
            total_pages=self._count_pages(root),
        )
        log.info("structure_plan_done", repository=repository, scope_type="repo", total_pages=structure.total_pages)
        return structure

    def _sort_key_for_module_list(self, node: GraphNode) -> tuple[str, str]:
        path = str(node.properties.get("path") or "")
        name = str(node.properties.get("name") or "")
        return (path, name)

    async def _resolve_scope_node(self, repository: str, needle: str) -> GraphNode:
        node = await self._graph.find_node_by_path(repository, needle)
        if node is None:
            node = await self._graph.find_node_by_fqn(repository, needle)
        if node is None:
            raise WikiScopeError(
                f"No matching graph node for scope value {needle!r} in repository {repository!r}"
            )
        return node

    async def _build_module_tree(self, repository: str, module_node: GraphNode) -> WikiStructureNode:
        raw_children = await self._graph.find_children(repository, module_node.uid)
        wiki_children: list[WikiStructureNode] = []
        for child in sorted(raw_children, key=self._node_sort_key):
            if child.label == NodeLabel.MODULE:
                wiki_children.append(await self._build_module_tree(repository, child))
            elif child.label == NodeLabel.CLASS:
                wiki_children.append(self._leaf_wiki_node(child, PageType.CLASS_DETAIL))
            else:
                wiki_children.append(self._leaf_wiki_node(child, PageType.API_REFERENCE))

        return WikiStructureNode(
            path=self._structure_path(module_node),
            title=self._node_title(module_node),
            page_type=PageType.MODULE_OVERVIEW,
            children=wiki_children,
        )

    def _node_sort_key(self, node: GraphNode) -> tuple[str, str]:
        return (self._node_title(node), node.uid)

    def _leaf_wiki_node(self, node: GraphNode, page_type: PageType) -> WikiStructureNode:
        return WikiStructureNode(
            path=self._structure_path(node),
            title=self._node_title(node),
            page_type=page_type,
            children=[],
        )

    def _node_title(self, node: GraphNode) -> str:
        name = node.properties.get("name")
        if isinstance(name, str) and name:
            return name
        path = node.properties.get("path")
        if isinstance(path, str) and path:
            return path
        return node.uid

    def _structure_path(self, node: GraphNode) -> str:
        if node.label == NodeLabel.MODULE:
            p = node.properties.get("path")
            if isinstance(p, str) and p:
                return p
            return self._node_title(node)
        if node.label == NodeLabel.CLASS:
            fqn = node.properties.get("fqn")
            if isinstance(fqn, str) and fqn:
                return fqn
            return self._node_title(node)
        file_val = node.properties.get("file")
        name_val = node.properties.get("name")
        if isinstance(file_val, str) and file_val and isinstance(name_val, str):
            return f"{file_val}#{name_val}"
        if isinstance(name_val, str) and name_val:
            return name_val
        return node.uid

    def _count_pages(self, node: WikiStructureNode) -> int:
        return 1 + sum(self._count_pages(c) for c in node.children)
