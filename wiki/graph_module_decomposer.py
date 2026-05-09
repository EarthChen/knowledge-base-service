"""Graph-algorithm-driven module decomposition for wiki generation."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from typing import Any

from core.log import get_logger
from wiki.models.module_tree import ModuleNode, ModuleTree

log = get_logger(__name__)

DEFAULT_MAX_TOKENS = 30000


def make_canonical_key(
    file_paths: list[str],
    existing_keys: set[str],
    entity_uids: list[str] | None = None,
) -> str:
    if not file_paths:
        slug = "unknown"
    elif len(file_paths) == 1:
        slug = file_paths[0].strip("/").replace("/", "-").replace("_", "-").lower()
    else:
        prefix = os.path.commonpath(file_paths)
        slug = prefix.strip("/").replace("/", "-").replace("_", "-").lower()
    if not slug:
        slug = "root"
    if slug in existing_keys:
        uid_str = "".join(sorted(entity_uids or file_paths))
        uid_hash = hashlib.sha256(uid_str.encode()).hexdigest()[:6]
        slug = f"{slug}-{uid_hash}"
    return slug


class GraphModuleDecomposer:
    def __init__(
        self,
        max_tokens_per_module: int = DEFAULT_MAX_TOKENS,
        llm: Any | None = None,
    ) -> None:
        self._max_tokens = max_tokens_per_module
        self._llm = llm

    def _compute_scc(
        self, nodes: list[str], edges: list[tuple[str, str]],
    ) -> list[list[str]]:
        """Tarjan's SCC algorithm."""
        index_counter = [0]
        stack: list[str] = []
        lowlink: dict[str, int] = {}
        index: dict[str, int] = {}
        on_stack: set[str] = set()
        result: list[list[str]] = []
        adj: dict[str, list[str]] = defaultdict(list)
        for u, v in edges:
            adj[u].append(v)

        def strongconnect(v: str) -> None:
            index[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)
            for w in adj.get(v, []):
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])
            if lowlink[v] == index[v]:
                component: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                result.append(sorted(component))

        for node in sorted(nodes):
            if node not in index:
                strongconnect(node)
        return result

    def _condense_graph(
        self,
        nodes: list[str],
        edges: list[tuple[str, str]],
        sccs: list[list[str]],
    ) -> tuple[list[frozenset[str]], list[tuple[frozenset[str], frozenset[str]]]]:
        node_to_scc: dict[str, frozenset[str]] = {}
        scc_nodes: list[frozenset[str]] = []
        for scc in sccs:
            fs = frozenset(scc)
            scc_nodes.append(fs)
            for n in scc:
                node_to_scc[n] = fs
        scc_edges: set[tuple[frozenset[str], frozenset[str]]] = set()
        for u, v in edges:
            su = node_to_scc.get(u)
            sv = node_to_scc.get(v)
            if su and sv and su != sv:
                scc_edges.add((su, sv))
        return scc_nodes, list(scc_edges)

    def _topological_sort(
        self,
        nodes: list[frozenset[str]],
        edges: list[tuple[frozenset[str], frozenset[str]]],
    ) -> list[frozenset[str]]:
        """Kahn's algorithm for topological sort."""
        adj: dict[frozenset[str], list[frozenset[str]]] = defaultdict(list)
        in_degree: dict[frozenset[str], int] = {n: 0 for n in nodes}
        for u, v in edges:
            adj[u].append(v)
            in_degree[v] = in_degree.get(v, 0) + 1
        queue = sorted(
            [n for n in nodes if in_degree.get(n, 0) == 0],
            key=lambda x: sorted(x),
        )
        result: list[frozenset[str]] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in sorted(adj.get(node, []), key=lambda x: sorted(x)):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort(key=lambda x: sorted(x))
        return result

    def _find_connected_components(
        self,
        members: list[str],
        edges: list[tuple[str, str]],
    ) -> list[list[str]]:
        """Find connected components in undirected view of subgraph restricted to members."""
        member_set = set(members)
        adj: dict[str, set[str]] = {m: set() for m in members}
        for u, v in edges:
            if u in member_set and v in member_set:
                adj[u].add(v)
                adj[v].add(u)

        visited: set[str] = set()
        components: list[list[str]] = []
        for start in sorted(members):
            if start in visited:
                continue
            component: list[str] = []
            stack = [start]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for neighbor in sorted(adj[node]):
                    if neighbor not in visited:
                        stack.append(neighbor)
            components.append(sorted(component))
        return components

    def _group_by_path_prefix(
        self,
        members: list[str],
        node_files: dict[str, list[str]],
    ) -> list[list[str]]:
        """Group members by their first file's directory prefix."""
        prefix_groups: dict[str, list[str]] = defaultdict(list)
        for m in members:
            files = node_files.get(m, [])
            if files:
                parts = files[0].strip("/").split("/")
                prefix = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
            else:
                prefix = "_no_path"
            prefix_groups[prefix].append(m)

        groups = [sorted(g) for g in prefix_groups.values()]
        if len(groups) <= 1:
            mid = len(members) // 2
            return [sorted(members[:mid]), sorted(members[mid:])]
        return groups

    async def _llm_cluster(self, members: list[str]) -> list[list[str]] | None:
        """Ask LLM to semantically cluster members into ≤5 groups."""
        if not self._llm:
            return None
        prompt = (
            f"将以下 {len(members)} 个代码模块按语义相关性分为 2-5 个组。\n"
            f"模块列表: {', '.join(members)}\n"
            f'输出 JSON: {{"groups": [["mod1", "mod2"], ["mod3", "mod4"]]}}'
        )
        raw = await self._llm.generate(prompt, max_tokens=500)
        data = json.loads(raw)
        groups = data.get("groups", [])
        if not groups or not all(isinstance(g, list) for g in groups):
            return None
        all_members_set = set(members)
        valid_groups = [[m for m in g if m in all_members_set] for g in groups]
        valid_groups = [g for g in valid_groups if g]
        covered: set[str] = set()
        for g in valid_groups:
            covered.update(g)
        uncovered = all_members_set - covered
        if uncovered:
            valid_groups.append(sorted(uncovered))
        return valid_groups if len(valid_groups) > 1 else None

    async def _maybe_split_scc(
        self,
        members: list[str],
        node_files: dict[str, list[str]],
        node_tokens: dict[str, int],
        edges: list[tuple[str, str]],
        existing_keys: set[str],
    ) -> ModuleNode:
        """Return a leaf ModuleNode if small enough, or a parent with children if too large."""
        total_tokens = sum(node_tokens.get(m, 0) for m in members)
        all_files = sorted({f for m in members for f in node_files.get(m, [])})
        all_uids = sorted(members)

        if total_tokens <= self._max_tokens or len(members) <= 2:
            key = make_canonical_key(all_files, existing_keys, entity_uids=all_uids)
            existing_keys.add(key)
            return ModuleNode(
                canonical_key=key,
                entity_uids=all_uids,
                file_paths=all_files,
                token_estimate=total_tokens,
            )

        components = self._find_connected_components(members, edges)

        if len(components) > 1:
            children = [
                await self._maybe_split_scc(
                    comp, node_files, node_tokens, edges, existing_keys,
                )
                for comp in components
            ]
        else:
            children_llm: list[ModuleNode] | None = None
            if self._llm and len(members) > 10:
                try:
                    cluster_result = await self._llm_cluster(members)
                    if cluster_result and len(cluster_result) > 1:
                        children_llm = [
                            await self._maybe_split_scc(
                                group, node_files, node_tokens, edges, existing_keys,
                            )
                            for group in cluster_result
                        ]
                except Exception:
                    log.warning(
                        "llm_clustering_failed",
                        member_count=len(members),
                        exc_info=True,
                    )
            if children_llm is not None:
                children = children_llm
            else:
                groups = self._group_by_path_prefix(members, node_files)
                children = [
                    await self._maybe_split_scc(
                        g, node_files, node_tokens, edges, existing_keys,
                    )
                    for g in groups
                    if g
                ]

        parent_key = make_canonical_key(all_files, existing_keys, entity_uids=all_uids)
        existing_keys.add(parent_key)
        return ModuleNode(
            canonical_key=parent_key,
            entity_uids=all_uids,
            file_paths=all_files,
            token_estimate=total_tokens,
            children=children,
        )

    async def decompose_from_graph(
        self,
        nodes: list[str],
        edges: list[tuple[str, str]],
        node_files: dict[str, list[str]],
        node_tokens: dict[str, int],
        repo_id: str,
    ) -> ModuleTree:
        sccs = self._compute_scc(nodes, edges)
        condensed_nodes, condensed_edges = self._condense_graph(nodes, edges, sccs)
        topo_order = self._topological_sort(condensed_nodes, condensed_edges)

        existing_keys: set[str] = set()
        module_nodes: list[ModuleNode] = []
        for scc_set in topo_order:
            members = sorted(scc_set)
            node = await self._maybe_split_scc(
                members, node_files, node_tokens, edges, existing_keys,
            )
            module_nodes.append(node)

        return ModuleTree(roots=module_nodes, repo_id=repo_id)
