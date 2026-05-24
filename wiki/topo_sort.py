# wiki/topo_sort.py
"""Topological ordering with SCC-based cycle handling for wiki generation order."""
from __future__ import annotations

from collections import defaultdict, deque


def _tarjan_scc(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's algorithm for strongly connected components."""
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in graph.get(v, []):
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
            sccs.append(component)

    for v in graph:
        if v not in index:
            strongconnect(v)

    return sccs


def topological_order(edges: dict[str, list[str]]) -> list[str]:
    """Return nodes in dependency-first order (leaves first).

    Cyclic dependencies are detected via Tarjan's SCC and grouped together.
    Within an SCC, nodes appear in arbitrary order.
    """
    if not edges:
        return []

    all_nodes = set(edges.keys())
    for targets in edges.values():
        all_nodes.update(targets)
    full_graph: dict[str, list[str]] = {n: edges.get(n, []) for n in all_nodes}

    sccs = _tarjan_scc(full_graph)
    # sccs are in reverse topological order of the condensation DAG
    result: list[str] = []
    for scc in sccs:
        result.extend(sorted(scc))
    return result


def kahn_topological_order(edges: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm: roots-first topological order.

    Returns nodes with no incoming edges first — suitable for reading order
    where "entry points" should be read before "implementations".

    Cycles are broken by forcibly dequeuing the node with smallest remaining
    in-degree when the BFS queue empties but unvisited nodes remain.
    """
    if not edges:
        return []

    all_nodes: set[str] = set(edges.keys())
    for targets in edges.values():
        all_nodes.update(targets)

    in_degree: dict[str, int] = {n: 0 for n in all_nodes}
    for src, targets in edges.items():
        for tgt in targets:
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue: deque[str] = deque(sorted(n for n in all_nodes if in_degree[n] == 0))
    result: list[str] = []
    visited: set[str] = set()

    while len(visited) < len(all_nodes):
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            result.append(node)
            for neighbor in edges.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0 and neighbor not in visited:
                    queue.append(neighbor)
        remaining = [n for n in all_nodes if n not in visited]
        if remaining:
            best = min(remaining, key=lambda n: (in_degree.get(n, 0), n))
            queue.append(best)

    return result


def topological_batches(
    nodes: list[str],
    edges: list[tuple[str, str]],
) -> list[list[str]]:
    """Return nodes grouped into batches by topological level.

    ``edges`` are ``(dependent, dependency)`` pairs — *dependent* needs *dependency* first.
    Nodes in the same batch have no mutual dependencies and can be processed in parallel.
    Cycles are broken: nodes in a cycle are placed in the final batch.
    """
    node_set = set(nodes)
    in_degree: dict[str, int] = {n: 0 for n in node_set}
    adj: dict[str, list[str]] = defaultdict(list)

    for dependent, dependency in edges:
        if dependent in node_set and dependency in node_set:
            adj[dependency].append(dependent)
            in_degree[dependent] += 1

    queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
    batches: list[list[str]] = []
    visited: set[str] = set()

    while queue:
        batch = list(queue)
        batches.append(sorted(batch))
        visited.update(batch)
        next_queue: deque[str] = deque()
        for node in batch:
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    remaining = sorted(node_set - visited)
    if remaining:
        batches.append(remaining)

    return batches
