"""LangGraph pipeline node implementations for Wiki generation."""
from __future__ import annotations

from collections import Counter
from typing import Any

from log import get_logger
from store.schema import GraphNode, NodeLabel
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.dependency_graph import HierarchicalDecomposer, ModuleGraph, ModuleInfo
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


async def classify_domains_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 2a-2b: classify modules into business domains using LLM.

    Filters to HAS_BUSINESS_LOGIC entities only, then delegates to
    CrossRepoBusinessDomainPlanner for per-repo classification + cross-repo merge.
    """
    llm = state.get("llm")
    business_id = state.get("business_id", "")
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    biz_modules: dict[str, list[GraphNode]] = {}
    for repo, mod_list in modules.items():
        filtered: list[GraphNode] = []
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            if entity_roles.get(uid) == "has_business_logic":
                props = mod_dict.get("properties", {})
                label_str = mod_dict.get("label", "Module")
                try:
                    label = NodeLabel(label_str)
                except ValueError:
                    label = NodeLabel.MODULE
                filtered.append(GraphNode(label=label, properties=props, uid=uid))
        if filtered:
            biz_modules[repo] = filtered

    planner = CrossRepoBusinessDomainPlanner(llm)
    domain_mapping = await planner.classify(business_id, biz_modules)

    log.info(
        "classify_domains_done",
        business_id=business_id,
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
    )
    return {"domain_mapping": domain_mapping}


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


def _normalize_domain_tree(raw_tree: list | None, domain_mapping: dict[str, list]) -> list[dict[str, Any]]:
    """Convert HierarchicalDecomposer output (DomainNode list) to plain dicts."""
    if not raw_tree:
        return []
    result = []
    for node in raw_tree:
        if hasattr(node, "name"):
            d = {
                "name": getattr(node, "name", ""),
                "description": getattr(node, "description", ""),
                "modules": [m.name if hasattr(m, "name") else str(m) for m in getattr(node, "modules", [])],
                "children": _normalize_domain_tree(getattr(node, "children", []), domain_mapping),
            }
        elif isinstance(node, dict):
            d = {
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "modules": node.get("modules", []),
                "children": _normalize_domain_tree(node.get("children", []), domain_mapping),
            }
        else:
            continue
        result.append(d)
    return result


async def decompose_hierarchy_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 2c: build hierarchical domain tree from flat domain mapping."""
    llm = state.get("llm")
    domain_mapping = state.get("domain_mapping", {})
    modules = state.get("modules", {})

    if not llm or not domain_mapping:
        log.info("decompose_hierarchy_skip", reason="no llm or empty domain_mapping")
        flat_tree = [
            {"name": domain, "modules": [m for _, m in pairs], "children": []}
            for domain, pairs in domain_mapping.items()
        ]
        return {"domain_tree": flat_tree}

    module_lookup: dict[str, dict] = {}
    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                module_lookup[name] = mod_dict

    all_module_infos: list[ModuleInfo] = []
    for domain, pairs in domain_mapping.items():
        for repo_id, mod_name in pairs:
            mod_dict = module_lookup.get(mod_name, {})
            props = mod_dict.get("properties", {})
            all_module_infos.append(ModuleInfo(
                name=mod_name,
                path=str(props.get("path", "")),
                uid=mod_dict.get("uid", f"Module::{mod_name}:0"),
                summary=str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                semantic_roles=list(props.get("semantic_roles", []) or []),
            ))

    if not all_module_infos:
        return {"domain_tree": []}

    decomposer = HierarchicalDecomposer(llm, max_depth=3, min_modules_for_nesting=3)
    module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])

    try:
        raw_tree = await decomposer.decompose(all_module_infos, module_graph)
        domain_tree = _normalize_domain_tree(raw_tree, domain_mapping)
    except Exception:
        log.warning("decompose_hierarchy_failed", exc_info=True)
        domain_tree = [
            {"name": domain, "modules": [m for _, m in pairs], "children": []}
            for domain, pairs in domain_mapping.items()
        ]

    log.info("decompose_hierarchy_done", domains=len(domain_tree) if domain_tree else 0)
    return {"domain_tree": domain_tree}


async def plan_structure_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark domain tree as pending_review and continue (non-blocking)."""
    review_status = dict(state.get("review_status", {}))
    review_status["domain_tree"] = "pending_review"

    log.info("plan_structure_marked_review", tree_size=len(state.get("domain_tree") or []))
    return {"review_status": review_status}
