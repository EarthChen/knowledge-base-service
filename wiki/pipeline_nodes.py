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


async def detect_reorg_node(state: dict[str, Any]) -> dict[str, Any]:
    """Determine reorganization type based on pipeline state.

    Returns reorg_type: first_run | full | heavy | light | none
    """
    domain_tree = state.get("domain_tree")
    is_incremental = state.get("is_incremental", False)
    affected_domains = state.get("affected_domains", [])

    if domain_tree is None:
        reorg_type = "first_run"
    elif not is_incremental:
        reorg_type = "full"
    elif affected_domains:
        biz_count = state.get("role_stats", {}).get("has_business_logic", 0)
        prev_biz = sum(
            len(d.get("modules", []))
            for d in (domain_tree if isinstance(domain_tree, list) else [])
        )
        ratio = abs(biz_count - prev_biz) / max(prev_biz, 1)
        if ratio > 0.3:
            reorg_type = "heavy"
        else:
            reorg_type = "light"
    else:
        reorg_type = "none"

    log.info("detect_reorg_done", reorg_type=reorg_type, is_incremental=is_incremental)
    return {"reorg_type": reorg_type}
