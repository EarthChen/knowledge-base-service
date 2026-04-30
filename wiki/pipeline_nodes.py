"""LangGraph pipeline node implementations for Wiki generation."""
from __future__ import annotations

from collections import Counter
from typing import Any

from log import get_logger
from store.schema import GraphNode, NodeLabel
from wiki.entity_role_classifier import EntityRoleClassifier, WikiEntityRole

log = get_logger(__name__)


async def classify_entities_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 1: classify all entities using EntityRoleClassifier."""
    classifier = EntityRoleClassifier()
    entity_roles: dict[str, WikiEntityRole] = {}
    role_counter: Counter[WikiEntityRole] = Counter()

    for _repo, modules in state.get("modules", {}).items():
        for mod_dict in modules:
            uid = mod_dict.get("uid", "")
            props = mod_dict.get("properties", {})
            label_str = mod_dict.get("label", "Module")
            try:
                label = NodeLabel(label_str)
            except ValueError:
                label = NodeLabel.MODULE
            node = GraphNode(label=label, properties=props, uid=uid)
            role = classifier.classify(node, edge_count=0, children_count=0)
            entity_roles[uid] = role
            role_counter[role] += 1

    log.info(
        "classify_entities_done",
        total=len(entity_roles),
        **{str(r): c for r, c in role_counter.items()},
    )
    return {
        "entity_roles": entity_roles,
        "role_stats": dict(role_counter),
    }
