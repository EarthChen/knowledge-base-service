"""Topological sort with batch grouping for parallel leaf composition.

Note: This utility is prepared as foundation for Phase 2 hierarchical
composition where leaf nodes are batched by dependency order. It is not
yet integrated into the production compose pipeline.
"""

from __future__ import annotations

from collections import defaultdict, deque


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
