"""Graph-algorithm-driven module decomposition for wiki generation."""

from __future__ import annotations

import hashlib
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

    def decompose_from_graph(
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
            all_files: list[str] = []
            all_uids: list[str] = list(members)
            total_tokens = 0
            for m in members:
                all_files.extend(node_files.get(m, []))
                total_tokens += node_tokens.get(m, 0)
            all_files = sorted(set(all_files))
            key = make_canonical_key(all_files, existing_keys, entity_uids=all_uids)
            existing_keys.add(key)
            node = ModuleNode(
                canonical_key=key,
                entity_uids=all_uids,
                file_paths=all_files,
                token_estimate=total_tokens,
            )
            module_nodes.append(node)

        return ModuleTree(roots=module_nodes, repo_id=repo_id)
