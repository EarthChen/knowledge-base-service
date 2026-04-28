"""Dynamic delegation for complex modules: split oversized child sets into sub-groups."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from wiki.models import WikiStructureNode


@dataclass
class DelegationDecision:
    should_delegate: bool
    reason: str = ""


def evaluate_delegation(
    children_count: int,
    total_code_lines: int,
    max_children: int = 30,
    max_code_lines: int = 5000,
) -> DelegationDecision:
    if children_count > max_children:
        return DelegationDecision(True, reason="too_many_children")
    if total_code_lines > max_code_lines:
        return DelegationDecision(True, reason="too_much_code")
    return DelegationDecision(False)


def group_children_by_graph(
    children: list[WikiStructureNode],
    edges: list[tuple[str, str]],
    max_group_size: int = 30,
) -> list[list[WikiStructureNode]]:
    """Group children into connected components using graph edges.
    Falls back to chunk-based grouping if no edges produce useful clusters."""
    if not children:
        return []
    if not edges:
        return _chunk_group(children, max_group_size)

    path_to_node = {c.path: c for c in children}
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        if a in path_to_node and b in path_to_node:
            adj[a].add(b)
            adj[b].add(a)

    visited: set[str] = set()
    groups: list[list[WikiStructureNode]] = []

    for child in children:
        if child.path in visited:
            continue
        component: list[WikiStructureNode] = []
        stack = [child.path]
        while stack:
            path = stack.pop()
            if path in visited:
                continue
            visited.add(path)
            if path in path_to_node:
                component.append(path_to_node[path])
            for neighbor in adj.get(path, set()):
                if neighbor not in visited:
                    stack.append(neighbor)
        groups.append(component)

    return groups


def _chunk_group(
    children: list[WikiStructureNode], chunk_size: int,
) -> list[list[WikiStructureNode]]:
    return [
        children[i:i + chunk_size]
        for i in range(0, len(children), chunk_size)
    ]
