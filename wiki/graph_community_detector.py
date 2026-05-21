from __future__ import annotations

import networkx as nx
from networkx.algorithms.community import louvain_communities

from core.log import get_logger

log = get_logger(__name__)

Node = tuple[str, str]
Edge = tuple[Node, Node, int]


def _ngram_similarity(name_a: str, name_b: str, n: int = 3) -> float:
    grams_a = {name_a[i : i + n] for i in range(len(name_a) - n + 1)}
    grams_b = {name_b[i : i + n] for i in range(len(name_b) - n + 1)}
    if not grams_a or not grams_b:
        return 0.0
    return len(grams_a & grams_b) / len(grams_a | grams_b)


def _edge_density(nodes: set[Node], edges: list[Edge]) -> float:
    n = len(nodes)
    if n <= 1:
        return 1.0
    node_set = nodes
    actual = 0
    seen: set[tuple[Node, Node]] = set()
    for src, dst, _weight in edges:
        if src not in node_set or dst not in node_set:
            continue
        key = (min(src, dst), max(src, dst))
        if key not in seen:
            seen.add(key)
            actual += 1
    possible = n * (n - 1) / 2
    return actual / possible if possible else 0.0


class GraphCommunityDetector:
    """Detect business domain communities from module call graphs using Louvain algorithm."""

    _RESOLUTION_MIN = 0.3
    _RESOLUTION_MAX = 3.0
    _MAX_RESOLUTION_ITERATIONS = 5

    def __init__(self, target_min: int = 5, target_max: int = 15, seed: int = 42):
        self.target_min = target_min
        self.target_max = target_max
        self.seed = seed

    def detect(
        self,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[set[Node]]:
        """Run Louvain community detection with adaptive resolution.

        Returns communities as list of sets of (repo_id, module_name) tuples.
        Micro-communities (≤2 members) are merged into nearest neighbor.
        """
        if not nodes:
            return []

        graph = self._build_graph(nodes, edges)
        resolution = self._find_resolution(graph)
        raw_communities = self._louvain_communities(graph, resolution)
        communities = [set(c) for c in raw_communities]
        communities = self._merge_micro_communities(communities, graph)

        log.info(
            "graph_community_detect_complete",
            node_count=len(nodes),
            edge_count=graph.number_of_edges(),
            community_count=len(communities),
            resolution=resolution,
        )
        return communities

    def assign_isolated_modules(
        self,
        isolated: list[Node],
        communities: list[set[Node]],
        similarity_threshold: float = 0.2,
    ) -> dict[int, list[Node]]:
        """Assign isolated modules to existing communities by name similarity.

        Returns: dict mapping community_index → list of assigned isolated modules.
        Modules below similarity_threshold go into a special misc group (index -1).
        """
        if not isolated:
            return {}

        assignments: dict[int, list[Node]] = {}
        for module in isolated:
            _repo_id, module_name = module
            best_idx = -1
            best_score = 0.0
            for idx, community in enumerate(communities):
                for member in community:
                    score = _ngram_similarity(module_name, member[1])
                    if score > best_score:
                        best_score = score
                        best_idx = idx

            if best_score >= similarity_threshold:
                assignments.setdefault(best_idx, []).append(module)
            else:
                assignments.setdefault(-1, []).append(module)

        return assignments

    _MIN_SUB_COMMUNITY_SIZE = 3

    def detect_sub_communities(
        self,
        community_nodes: set[Node],
        all_edges: list[Edge],
        max_depth: int = 3,
        max_leaf_size: int = 8,
        _current_depth: int = 0,
    ) -> list[dict]:
        """Recursively split a community into sub-domains.

        Returns tree structure:
        [
            {
                "modules": [(repo_id, mod_name), ...],
                "children": [...]  # recursive, or empty if leaf
            }
        ]

        Split conditions:
        - len(modules) > max_leaf_size
        - edge_density <= 0.5 (high cohesion = don't split)
        - depth < max_depth
        - Louvain produces >1 community on sub-graph
        """
        modules = sorted(community_nodes)
        sub_edges = [
            (src, dst, weight)
            for src, dst, weight in all_edges
            if src in community_nodes and dst in community_nodes
        ]

        if (
            len(community_nodes) <= max_leaf_size
            or _current_depth >= max_depth
            or _edge_density(community_nodes, sub_edges) > 0.5
        ):
            return [{"modules": modules, "children": []}]

        graph = self._build_graph(list(community_nodes), sub_edges)
        sub_communities = [set(c) for c in self._louvain_communities(graph, resolution=1.0)]

        if len(sub_communities) <= 1:
            return [{"modules": modules, "children": []}]

        # Merge micro sub-communities (same logic as top-level)
        sub_communities = self._merge_micro_communities(sub_communities, graph)
        if len(sub_communities) <= 1:
            return [{"modules": modules, "children": []}]

        # Merge sub-communities below minimum size into nearest neighbor
        sub_communities = self._merge_small_sub_communities(sub_communities, graph)
        if len(sub_communities) <= 1:
            return [{"modules": modules, "children": []}]

        children: list[dict] = []
        for sub in sub_communities:
            child_trees = self.detect_sub_communities(
                sub,
                all_edges,
                max_depth=max_depth,
                max_leaf_size=max_leaf_size,
                _current_depth=_current_depth + 1,
            )
            children.extend(child_trees)

        return [{"modules": modules, "children": children}]

    def _merge_small_sub_communities(
        self,
        communities: list[set[Node]],
        graph: nx.Graph,
    ) -> list[set[Node]]:
        """Merge sub-communities below _MIN_SUB_COMMUNITY_SIZE into nearest larger neighbor."""
        if len(communities) <= 1:
            return communities

        merged = [set(c) for c in communities]
        changed = True
        while changed:
            changed = False
            small_indices = [
                i for i, c in enumerate(merged)
                if len(c) < self._MIN_SUB_COMMUNITY_SIZE
            ]
            if not small_indices:
                break
            large_exist = any(len(c) >= self._MIN_SUB_COMMUNITY_SIZE for c in merged)
            if not large_exist:
                break

            for idx in sorted(small_indices, reverse=True):
                if idx >= len(merged) or len(merged[idx]) >= self._MIN_SUB_COMMUNITY_SIZE:
                    continue
                target = self._find_merge_target(merged[idx], merged, idx, graph)
                if target is not None and len(merged[target]) >= self._MIN_SUB_COMMUNITY_SIZE:
                    merged[target] |= merged[idx]
                    merged.pop(idx)
                    changed = True

        return [c for c in merged if c]

    def _build_graph(self, nodes: list[Node], edges: list[Edge]) -> nx.Graph:
        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        for src, dst, weight in edges:
            if src in graph and dst in graph:
                if graph.has_edge(src, dst):
                    graph[src][dst]["weight"] += weight
                else:
                    graph.add_edge(src, dst, weight=weight)
        return graph

    def _louvain_communities(self, graph: nx.Graph, resolution: float = 1.0) -> list[set[Node]]:
        if graph.number_of_nodes() == 0:
            return []
        if graph.number_of_edges() == 0:
            return [{node} for node in graph.nodes()]
        return list(
            louvain_communities(
                graph,
                weight="weight",
                resolution=resolution,
                seed=self.seed,
            )
        )

    def _find_resolution(self, graph: nx.Graph) -> float:
        communities = self._louvain_communities(graph, resolution=1.0)
        count = len(communities)

        if self.target_min <= count <= self.target_max:
            return 1.0

        if count < self.target_min:
            lo, hi = 1.0, self._RESOLUTION_MAX
            best = 1.0
            for _ in range(self._MAX_RESOLUTION_ITERATIONS):
                mid = (lo + hi) / 2
                mid_count = len(self._louvain_communities(graph, resolution=mid))
                if mid_count >= self.target_min:
                    best = mid
                    hi = mid
                else:
                    lo = mid
            log.debug("adaptive_resolution_increase", initial_count=count, final_resolution=best)
            return best

        lo, hi = self._RESOLUTION_MIN, 1.0
        best = 1.0
        for _ in range(self._MAX_RESOLUTION_ITERATIONS):
            mid = (lo + hi) / 2
            mid_count = len(self._louvain_communities(graph, resolution=mid))
            if mid_count <= self.target_max:
                best = mid
                lo = mid
            else:
                hi = mid
        log.debug("adaptive_resolution_decrease", initial_count=count, final_resolution=best)
        return best

    def _merge_micro_communities(
        self,
        communities: list[set[Node]],
        graph: nx.Graph,
    ) -> list[set[Node]]:
        if len(communities) <= 1:
            return communities

        merged = [set(c) for c in communities]
        changed = True
        while changed:
            changed = False
            micro_indices = [i for i, c in enumerate(merged) if len(c) <= 2]
            if not micro_indices:
                break

            for idx in sorted(micro_indices, reverse=True):
                if idx >= len(merged) or len(merged[idx]) > 2:
                    continue
                micro = merged[idx]
                if not micro:
                    merged.pop(idx)
                    changed = True
                    continue

                best_target = self._find_merge_target(micro, merged, idx, graph)
                if best_target is None:
                    continue

                merged[best_target] |= micro
                merged.pop(idx)
                changed = True

        return [c for c in merged if c]

    def _find_merge_target(
        self,
        micro: set[Node],
        communities: list[set[Node]],
        micro_idx: int,
        graph: nx.Graph,
    ) -> int | None:
        best_idx: int | None = None
        best_weight = -1.0
        best_similarity = -1.0

        for idx, community in enumerate(communities):
            if idx == micro_idx:
                continue
            edge_weight = 0.0
            for node in micro:
                for neighbor in graph.neighbors(node):
                    if neighbor in community:
                        edge_weight += graph[node][neighbor].get("weight", 1)
            if edge_weight > best_weight:
                best_weight = edge_weight
                best_idx = idx
                best_similarity = -1.0

        if best_weight > 0 and best_idx is not None:
            return best_idx

        for idx, community in enumerate(communities):
            if idx == micro_idx:
                continue
            for micro_node in micro:
                for member in community:
                    sim = _ngram_similarity(micro_node[1], member[1])
                    if sim > best_similarity:
                        best_similarity = sim
                        best_idx = idx

        return best_idx
