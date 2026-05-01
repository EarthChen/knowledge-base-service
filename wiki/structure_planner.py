"""Derives wiki directory structure from graph scope and CONTAINS edges."""

from __future__ import annotations

import json
import re
from typing import Protocol

from log import get_logger
from store.schema import GraphEdge, GraphNode, NodeLabel
from wiki.entity_filter import WikiEntityFilter
from wiki.llm_port import LLMPort
from wiki.models import EntityStrategy, ImportanceTier, PageType, ScopeParam, WikiStructure, WikiStructureNode

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

    def __init__(
        self,
        graph: GraphQueryPort,
        llm: LLMPort | None = None,
        semantic_group_threshold: int = 12,
    ) -> None:
        self._graph = graph
        self._llm = llm
        self._semantic_group_threshold = semantic_group_threshold
        self._entity_filter = WikiEntityFilter()

    async def plan(
        self,
        repository: str,
        scope: ScopeParam,
        *,
        importance_tiers: dict[str, ImportanceTier] | None = None,
    ) -> WikiStructure:
        log.info("structure_plan_start", repository=repository, scope_type=scope.scope_type, scope_value=scope.value)
        if scope.scope_type == "repo":
            return await self._plan_repo(repository, importance_tiers=importance_tiers)

        if scope.scope_type == "module":
            node = await self._resolve_scope_node(repository, scope.value or "")
            if node.label != NodeLabel.MODULE:
                raise WikiScopeError(
                    f"Scope type 'module' resolved to {node.label}, expected Module"
                )
            root = await self._build_module_tree(repository, node, importance_tiers=importance_tiers)
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

    def _is_skeleton(self, node: GraphNode, importance_tiers: dict[str, ImportanceTier] | None) -> bool:
        if importance_tiers is None:
            return False
        tier = importance_tiers.get(node.uid)
        if tier is None:
            name = self._module_display_name(node) if node.label == NodeLabel.MODULE else self._node_title(node)
            tier = importance_tiers.get(name)
        return tier == ImportanceTier.SKELETON

    async def _plan_repo(
        self,
        repository: str,
        *,
        importance_tiers: dict[str, ImportanceTier] | None = None,
    ) -> WikiStructure:
        modules = await self._graph.find_top_level_modules(repository)
        if importance_tiers:
            modules = [m for m in modules if not self._is_skeleton(m, importance_tiers)]
        log.info("plan_repo_modules_found", repository=repository, module_count=len(modules))
        if (
            self._llm is not None
            and len(modules) >= self._semantic_group_threshold
        ):
            children = await self._semantic_group_modules(repository, modules)
        else:
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

    @staticmethod
    def _strip_json_code_fences(text: str) -> str:
        t = text.strip()
        fence = re.match(r"^```(?:json)?\s*\n?", t, re.IGNORECASE)
        if fence:
            t = t[fence.end() :]
        if t.endswith("```"):
            t = t[: -3]
        return t.strip()

    def _module_display_name(self, m: GraphNode) -> str:
        name = m.properties.get("name")
        if isinstance(name, str) and name:
            return name
        return self._node_title(m)

    def _semantic_group_path(self, group_name: str) -> str:
        safe = group_name.replace("/", "_").strip() or "group"
        return f"__semantic__/{safe}"

    async def _semantic_group_modules(
        self, repository: str, modules: list[GraphNode]
    ) -> list[WikiStructureNode]:
        if self._llm is None:
            return [
                self._leaf_wiki_node(m, PageType.MODULE_OVERVIEW)
                for m in sorted(modules, key=self._sort_key_for_module_list)
            ]

        lines: list[str] = []
        for m in modules:
            name = self._module_display_name(m)
            raw = m.properties.get("business_summary") or m.properties.get("docstring") or ""
            desc = raw.strip() if isinstance(raw, str) else str(raw or "")
            lines.append(f"- {name}: {desc or '(no description)'}")

        prompt = (
            "You are organizing repository top-level modules into 3-7 thematic groups "
            "for wiki navigation.\nModules list:\n"
            + "\n".join(lines)
            + "\n\nReturn ONLY a JSON array of objects. Each object must have "
            '"group_name" (string) and "modules" (array of module names exactly as listed above, '
            "without the description part).\n"
            "Assign every module to exactly one group."
        )
        system = "Respond with valid JSON only: a single JSON array. No markdown fences or explanation."

        try:
            raw = await self._llm.generate(prompt, system=system)
        except Exception as exc:
            log.warning("semantic_group_llm_failed", repository=repository, error=str(exc))
            return [
                self._leaf_wiki_node(m, PageType.MODULE_OVERVIEW)
                for m in sorted(modules, key=self._sort_key_for_module_list)
            ]

        try:
            parsed = json.loads(self._strip_json_code_fences(raw))
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("semantic_group_json_parse_failed", repository=repository, error=str(exc))
            return [
                self._leaf_wiki_node(m, PageType.MODULE_OVERVIEW)
                for m in sorted(modules, key=self._sort_key_for_module_list)
            ]

        if not isinstance(parsed, list):
            return [
                self._leaf_wiki_node(m, PageType.MODULE_OVERVIEW)
                for m in sorted(modules, key=self._sort_key_for_module_list)
            ]

        name_to_node: dict[str, GraphNode] = {}
        for m in modules:
            n = self._module_display_name(m)
            name_to_node.setdefault(n, m)

        assigned: set[str] = set()
        group_nodes: list[WikiStructureNode] = []

        for item in parsed:
            if not isinstance(item, dict):
                continue
            gname = item.get("group_name")
            mod_names = item.get("modules")
            if not isinstance(gname, str) or not isinstance(mod_names, list):
                continue

            mod_children: list[WikiStructureNode] = []
            for mn in mod_names:
                if not isinstance(mn, str):
                    continue
                node = name_to_node.get(mn)
                if node is None or mn in assigned:
                    continue
                assigned.add(mn)
                mod_children.append(self._leaf_wiki_node(node, PageType.MODULE_OVERVIEW))

            mod_children.sort(key=lambda c: (c.path, c.title))
            if mod_children:
                group_nodes.append(
                    WikiStructureNode(
                        path=self._semantic_group_path(gname),
                        title=gname,
                        page_type=PageType.DOMAIN_OVERVIEW,
                        children=mod_children,
                    )
                )

        flat: list[WikiStructureNode] = []
        for m in sorted(modules, key=self._sort_key_for_module_list):
            mn = self._module_display_name(m)
            if mn not in assigned:
                flat.append(self._leaf_wiki_node(m, PageType.MODULE_OVERVIEW))

        return group_nodes + flat

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

    def _classification_children_count_estimate(self, node: GraphNode) -> int:
        """Structural child count surrogate when callers skip edge queries (see spec §7)."""

        if node.label == NodeLabel.CLASS:
            mc = node.properties.get("methods_count")
            if isinstance(mc, int) and mc >= 0:
                return mc
        return 0

    async def _build_module_tree(
        self,
        repository: str,
        module_node: GraphNode,
        *,
        importance_tiers: dict[str, ImportanceTier] | None = None,
    ) -> WikiStructureNode:
        raw_children = await self._graph.find_children(repository, module_node.uid)
        wiki_children: list[WikiStructureNode] = []
        for child in sorted(raw_children, key=self._node_sort_key):
            if self._is_skeleton(child, importance_tiers):
                continue
            if child.label == NodeLabel.MODULE:
                wiki_children.append(await self._build_module_tree(repository, child, importance_tiers=importance_tiers))
            elif child.label == NodeLabel.CLASS:
                child_count = self._classification_children_count_estimate(child)
                if (
                    self._entity_filter.classify(child, edge_count=0, children_count=child_count)
                    == EntityStrategy.MERGE_TO_PARENT
                ):
                    continue
                wiki_children.append(self._leaf_wiki_node(child, PageType.CLASS_DETAIL))
            elif child.label == NodeLabel.FUNCTION:
                child_count = self._classification_children_count_estimate(child)
                if (
                    self._entity_filter.classify(child, edge_count=0, children_count=child_count)
                    == EntityStrategy.MERGE_TO_PARENT
                ):
                    continue
                wiki_children.append(self._leaf_wiki_node(child, PageType.API_REFERENCE))
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
