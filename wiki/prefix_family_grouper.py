"""Deterministic prefix-based grouping for L1 domain tree nodes."""
from __future__ import annotations

from core.log import get_logger

log = get_logger(__name__)


def enforce_prefix_family_grouping(tree: list[dict]) -> list[dict]:
    """Group L1 domains that share a business prefix under a common parent.

    Logic:
    1. Extract prefix for each L1 node using _extract_business_prefix
    2. If ≥2 L1 nodes share the same prefix AND no existing parent already groups them → wrap under synthetic parent
    3. If a node has prefix P but another node already has children with prefix P → reparent under that node
    4. Skip nodes marked user_modified
    """
    from wiki.domain_semantic_clusterer import _extract_business_prefix

    if len(tree) <= 1:
        return _repair_cross_level_prefix_split(tree)

    # Build prefix map for L1 nodes
    prefix_groups: dict[str, list[int]] = {}
    for i, node in enumerate(tree):
        if node.get("user_modified"):
            continue
        prefix = _extract_business_prefix(node.get("name", ""), None)
        if prefix:
            prefix_groups.setdefault(prefix, []).append(i)

    # Find groups that need wrapping (≥2 L1 nodes with same prefix)
    # But skip if one node already HAS children (it's already a parent group)
    result = list(tree)
    indices_to_remove: set[int] = set()
    nodes_to_add: list[dict] = []

    for prefix, indices in prefix_groups.items():
        if len(indices) < 2:
            continue

        # Check if one of them is already a parent (has children)
        parent_idx = None
        for idx in indices:
            if result[idx].get("children") and not result[idx].get("modules"):
                parent_idx = idx
                break

        if parent_idx is not None:
            # Reparent other nodes under existing parent
            for idx in indices:
                if idx == parent_idx:
                    continue
                result[parent_idx]["children"].append(result[idx])
                indices_to_remove.add(idx)
            log.info("prefix_family_reparent", prefix=prefix, parent=result[parent_idx]["name"], moved=len(indices) - 1)
        else:
            # No existing parent — create synthetic wrapper
            children_nodes = [result[idx] for idx in indices]
            synthetic_parent = {
                "name": f"{prefix}-family",
                "display_name": _prefix_display_name(prefix),
                "modules": [],
                "children": children_nodes,
            }
            nodes_to_add.append(synthetic_parent)
            indices_to_remove.update(indices)
            log.info("prefix_family_wrap", prefix=prefix, children=len(children_nodes))

    # Build final tree
    final = [node for i, node in enumerate(result) if i not in indices_to_remove]
    final.extend(nodes_to_add)
    final = _repair_cross_level_prefix_split(final)
    return final


def _repair_cross_level_prefix_split(tree: list[dict]) -> list[dict]:
    """Repair cases where same-prefix domains are split across L1 and nested levels.

    If an L1 node has prefix P, and a shell node has children with prefix P,
    reparent the L1 node under that shell.

    Example:
    - L1: intimacy-task-execution (prefix: intimacy)
    - nested: 关系/intimacy-relationship (prefix: intimacy)
    → Move intimacy-task-execution under 关系 shell
    """
    if len(tree) <= 1:
        return tree

    from wiki.domain_semantic_clusterer import _extract_business_prefix

    shell_prefix_map: dict[str, list[dict]] = {}
    for node in tree:
        if not node.get("children"):
            continue
        for child in node["children"]:
            child_prefix = _extract_business_prefix(child.get("name", ""), None)
            if child_prefix:
                shell_prefix_map.setdefault(child_prefix, []).append(node)

    indices_to_remove: set[int] = set()
    for i, node in enumerate(tree):
        if node.get("user_modified"):
            continue
        if node.get("children"):
            continue
        node_prefix = _extract_business_prefix(node.get("name", ""), None)
        if not node_prefix:
            continue
        target_shells = shell_prefix_map.get(node_prefix, [])
        if not target_shells:
            continue
        target = target_shells[0]
        target["children"].append(node)
        indices_to_remove.add(i)
        log.info(
            "cross_level_prefix_reparent",
            node=node.get("name"),
            target_shell=target.get("name"),
            prefix=node_prefix,
        )

    if indices_to_remove:
        tree = [n for i, n in enumerate(tree) if i not in indices_to_remove]

    return tree


def _prefix_display_name(prefix: str) -> str:
    """Generate a display name for a synthetic parent from prefix."""
    _PREFIX_LABELS = {
        "family": "家族",
        "intimacy": "亲密度",
        "relation": "关系",
        "user": "用户",
        "guild": "公会",
    }
    return _PREFIX_LABELS.get(prefix, prefix.capitalize())
