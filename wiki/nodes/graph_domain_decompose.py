"""Graph-driven domain decomposition node for wiki pipeline."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.entity_role_classifier import DOMAIN_CLASSIFICATION_ENTITY_ROLES
from wiki.graph_call_query import fetch_module_call_edges
from wiki.graph_community_detector import GraphCommunityDetector
from wiki.graph_domain_namer import GraphDomainNamer
from wiki.nodes.classify import (
    _consolidate_split_entities,
    _ensure_ascii_keys,
    classify_domains_node,
    decompose_hierarchy_node,
)

log = get_logger(__name__)

# Copied from classify_domains_node for consistency
_DATA_MODEL_NAME_SUFFIXES = (
    "DTO", "Dto", "VO", "Vo", "Req", "Resp", "Request", "Response",
    "Param", "Form", "Query", "Result", "Enum", "Constants", "Entity",
    "Bo", "PO", "Po", "Config",
)
_DATA_MODEL_PATH_MARKERS = ("/dto/", "/model/", "/entity/", "/enums/", "/config/")


def _is_data_model(name: str, path: str) -> bool:
    if any(name.endswith(suffix) for suffix in _DATA_MODEL_NAME_SUFFIXES):
        return True
    if any(marker in path.lower() for marker in _DATA_MODEL_PATH_MARKERS):
        return True
    return False


_RELATED_KEYWORDS = [
    frozenset({"intimacy", "closedfriend", "closed"}),
    frozenset({"family", "guild"}),
]


def _merge_domains_by_keyword(
    domain_mapping: dict[str, list],
    domain_display_names: dict[str, str],
) -> tuple[dict[str, list], dict[str, str]]:
    """Merge small domains sharing related business keywords into a larger sibling.

    Only merges when the domain's DOMINANT keyword (>50% of module names) matches.
    Domains with >40 modules are never merged away (they're already well-formed).
    """
    domain_dominant_group: dict[str, str] = {}
    for domain, modules in domain_mapping.items():
        if not modules:
            continue
        group_scores: dict[str, int] = {}
        for _, name in modules:
            name_lower = name.lower()
            for group in _RELATED_KEYWORDS:
                for kw in group:
                    if kw in name_lower:
                        group_key = "|".join(sorted(group))
                        group_scores[group_key] = group_scores.get(group_key, 0) + 1
                        break
        if not group_scores:
            continue
        best_group = max(group_scores, key=lambda g: group_scores[g])
        # Only assign if >50% of modules match this keyword group
        if group_scores[best_group] > len(modules) * 0.5:
            domain_dominant_group[domain] = best_group

    # Group domains by their dominant keyword group
    group_to_domains: dict[str, list[str]] = {}
    for domain, group_key in domain_dominant_group.items():
        group_to_domains.setdefault(group_key, []).append(domain)

    merge_map: dict[str, str] = {}
    for _group_key, domains in group_to_domains.items():
        if len(domains) <= 1:
            continue
        target = max(domains, key=lambda d: len(domain_mapping.get(d, [])))
        for d in domains:
            if d == target:
                continue
            # Don't merge large domains (>40 modules)
            if len(domain_mapping.get(d, [])) > 40:
                continue
            merge_map[d] = target

    # Also merge tiny domains (≤2 modules) by slug keyword match
    for domain, modules in domain_mapping.items():
        if domain in merge_map or len(modules) > 2:
            continue
        slug_lower = domain.lower()
        for group in _RELATED_KEYWORDS:
            matched_kw = None
            for kw in group:
                if kw in slug_lower:
                    matched_kw = kw
                    break
            if matched_kw:
                group_key = "|".join(sorted(group))
                # Find the largest domain in the same keyword group
                candidates = [
                    d for d, g in domain_dominant_group.items()
                    if g == group_key and d != domain and d not in merge_map
                ]
                if candidates:
                    target = max(candidates, key=lambda d: len(domain_mapping.get(d, [])))
                    merge_map[domain] = target
                break

    if not merge_map:
        return domain_mapping, domain_display_names

    new_mapping: dict[str, list] = {}
    new_display: dict[str, str] = {}
    for domain, modules in domain_mapping.items():
        actual = merge_map.get(domain, domain)
        new_mapping.setdefault(actual, []).extend(modules)
        if actual not in new_display and actual in domain_display_names:
            new_display[actual] = domain_display_names[actual]

    for d, display in domain_display_names.items():
        if d not in merge_map and d not in new_display:
            new_display[d] = display

    log.info("merge_domains_by_keyword", merged=len(merge_map), targets=list(set(merge_map.values())))
    return new_mapping, new_display


def _build_domain_tree(
    communities_named: list[dict],
    sub_trees: dict[str, list[dict]],
) -> list[dict[str, Any]]:
    """Build domain_tree from named communities and their sub-trees.

    communities_named: [{"slug": "...", "display_name": "...", "modules": [(repo, name), ...]}]
    sub_trees: slug -> list of sub-domain dicts from detect_sub_communities
    """
    tree = []
    for community in communities_named:
        slug = community["slug"]
        display_name = community["display_name"]
        modules = community["modules"]  # list of (repo_id, name) tuples

        sub = sub_trees.get(slug, [])
        if sub and len(sub) > 1:
            # Has sub-domains
            children = []
            for sub_domain in sub:
                child_modules = [name for _, name in sub_domain.get("modules", [])]
                children.append({
                    "name": sub_domain.get("slug", f"{slug}-sub"),
                    "display_name": sub_domain.get("display_name", ""),
                    "modules": child_modules,
                    "children": [],
                })
            tree.append({
                "name": slug,
                "display_name": display_name,
                "modules": [],  # modules live in children
                "children": children,
            })
        else:
            # Leaf domain
            mod_names = [name for _, name in modules]
            tree.append({
                "name": slug,
                "display_name": display_name,
                "modules": mod_names,
                "children": [],
            })
    return tree


def _dedup_sub_domains(
    named_subs: list[dict],
    parent_display_name: str,
) -> list[dict]:
    """Merge sub-domains with identical display_name, dedup slugs, avoid parent-child collision."""
    merged_by_name: dict[str, dict] = {}
    for sub in named_subs:
        key = sub["display_name"]
        if key in merged_by_name:
            merged_by_name[key]["modules"].extend(sub.get("modules", []))
        else:
            merged_by_name[key] = dict(sub)
    result = list(merged_by_name.values())

    seen_slugs: set[str] = set()
    for sub in result:
        slug = sub["slug"]
        if slug in seen_slugs:
            counter = 1
            while f"{slug}-{counter}" in seen_slugs:
                counter += 1
            sub["slug"] = f"{slug}-{counter}"
        seen_slugs.add(sub["slug"])

    for sub in result:
        if sub["display_name"] == parent_display_name:
            sub["display_name"] = f"{sub['display_name']}（核心）"

    return result


def _collect_leaf_sub_domains(sub_tree: dict) -> list[dict]:
    """Flatten detect_sub_communities tree into leaf sub-domains with modules."""
    children = sub_tree.get("children") or []
    if not children:
        return [sub_tree]
    leaves: list[dict] = []
    for child in children:
        leaves.extend(_collect_leaf_sub_domains(child))
    return leaves


async def graph_driven_domain_decompose_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Graph-driven domain decomposition: replaces classify_domains + decompose_hierarchy.

    Uses Louvain community detection on module call graph to determine business domains.
    Falls back to LLM classification when graph_store is unavailable.
    """
    configurable = (config or {}).get("configurable", {})
    graph_store = configurable.get("graph_store")
    llm = configurable.get("llm")

    # Fallback: no graph_store → use old LLM classification path
    if graph_store is None:
        log.info("graph_domain_decompose_fallback", reason="no graph_store")
        classify_result = await classify_domains_node(state, config)
        state_with_classify = {**state, **classify_result}
        decompose_result = await decompose_hierarchy_node(state_with_classify, config)
        return {**classify_result, **decompose_result}

    # --- Step 0: Filter to BIZ modules (same logic as classify_domains_node) ---
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})
    repositories = state.get("repositories", [])

    biz_modules: list[tuple[str, str]] = []  # (repo_id, module_name)
    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            if entity_roles.get(uid) not in DOMAIN_CLASSIFICATION_ENTITY_ROLES:
                continue
            props = mod_dict.get("properties", {})
            name = str(props.get("name", ""))
            path = str(props.get("path", "") or "")
            if not name or path.startswith("<import:"):
                continue
            if _is_data_model(name, path):
                continue
            biz_modules.append((repo, name))

    if not biz_modules:
        return {
            "domain_mapping": {},
            "domain_display_names": {},
            "domain_tree": [],
            "affected_domains": [],
        }

    valid_modules_set = set(biz_modules)

    # --- Step 1: Fetch call graph edges ---
    edges = await fetch_module_call_edges(graph_store, repositories, valid_modules_set)

    log.info("graph_domain_decompose_edges", total_modules=len(biz_modules), total_edges=len(edges))

    # --- Step 2: Community detection ---
    detector = GraphCommunityDetector(target_min=5, target_max=15, seed=42)

    if not edges:
        # No edges: all modules in one community
        communities = [set(biz_modules)]
    else:
        # Separate nodes with edges from isolated nodes
        nodes_with_edges = set()
        for src, dst, _ in edges:
            nodes_with_edges.add(src)
            nodes_with_edges.add(dst)

        connected_nodes = [n for n in biz_modules if n in nodes_with_edges]
        isolated_nodes = [n for n in biz_modules if n not in nodes_with_edges]

        if connected_nodes:
            communities = detector.detect(connected_nodes, edges)
        else:
            communities = [set(biz_modules)]

        # Assign isolated modules
        if isolated_nodes and communities:
            assignments = detector.assign_isolated_modules(isolated_nodes, communities)
            for idx, assigned_modules in assignments.items():
                if idx == -1:
                    # Misc group: create a new community
                    if assigned_modules:
                        communities.append(set(assigned_modules))
                elif 0 <= idx < len(communities):
                    communities[idx].update(assigned_modules)

    # --- Step 3: LLM Naming ---
    namer = GraphDomainNamer(llm)
    communities_named = []
    for community in communities:
        module_names = sorted([name for _, name in community])
        naming = await namer.name_community(module_names)
        communities_named.append({
            "slug": naming["slug"],
            "display_name": naming["display_name"],
            "description": naming.get("description", ""),
            "modules": sorted(community),  # (repo_id, name) tuples
        })

    # Ensure unique slugs
    seen_slugs: set[str] = set()
    for c in communities_named:
        slug = c["slug"]
        if slug in seen_slugs:
            counter = 1
            while f"{slug}-{counter}" in seen_slugs:
                counter += 1
            c["slug"] = f"{slug}-{counter}"
        seen_slugs.add(c["slug"])

    # --- Step 4: Build domain_mapping ---
    domain_mapping: dict[str, list[tuple[str, str]]] = {}
    domain_display_names: dict[str, str] = {}
    for c in communities_named:
        domain_mapping[c["slug"]] = list(c["modules"])
        domain_display_names[c["slug"]] = c["display_name"]

    # --- Step 5: Post-processing (safety nets) ---
    domain_mapping, domain_display_names = _ensure_ascii_keys(domain_mapping, domain_display_names)
    domain_mapping, domain_display_names = _consolidate_split_entities(domain_mapping, domain_display_names)
    domain_mapping, domain_display_names = _merge_domains_by_keyword(domain_mapping, domain_display_names)

    # Rebuild communities_named to match merged domain_mapping (for tree building)
    communities_named = []
    for slug, module_list in domain_mapping.items():
        communities_named.append({
            "slug": slug,
            "display_name": domain_display_names.get(slug, slug),
            "modules": module_list,
        })

    # --- Step 6: Domain stabilizer ---
    try:
        from wiki.domain_stabilizer import DomainStabilizer

        stabilizer = DomainStabilizer(graph_store)
        rename_map = await stabilizer.stabilize(list(domain_mapping.keys()))
        if any(k != v for k, v in rename_map.items()):
            stabilized: dict[str, list] = {}
            updated_display: dict[str, str] = {}
            for proposed, pairs in domain_mapping.items():
                stable = rename_map.get(proposed, proposed)
                stabilized.setdefault(stable, []).extend(pairs)
                if proposed in domain_display_names:
                    updated_display[stable] = domain_display_names[proposed]
            domain_mapping = stabilized
            domain_display_names.update(updated_display)
    except Exception:
        log.warning("graph_domain_stabilizer_failed", exc_info=True)

    # --- Step 7: Recursive sub-domain splitting ---
    sub_trees: dict[str, list[dict]] = {}
    for c in communities_named:
        slug = c["slug"]
        community_nodes = set(c["modules"])
        if len(community_nodes) > 8:
            sub_result = detector.detect_sub_communities(
                community_nodes, edges, max_depth=3, max_leaf_size=8
            )
            leaf_subs = []
            for root in sub_result:
                leaf_subs.extend(_collect_leaf_sub_domains(root))
            if len(leaf_subs) > 1:
                named_subs = []
                for sub in leaf_subs:
                    sub_module_names = sorted([name for _, name in sub.get("modules", [])])
                    sub_naming = await namer.name_community(sub_module_names)
                    named_subs.append({
                        "slug": sub_naming["slug"],
                        "display_name": sub_naming["display_name"],
                        "modules": list(sub.get("modules", [])),
                    })
                parent_display = domain_display_names.get(slug, slug)
                named_subs = _dedup_sub_domains(named_subs, parent_display)
                sub_trees[slug] = named_subs

    # --- Step 8: Build domain_tree ---
    domain_tree = _build_domain_tree(communities_named, sub_trees)

    # --- Step 9: Determine affected_domains ---
    affected_domains = list(domain_mapping.keys())

    log.info(
        "graph_domain_decompose_done",
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
        with_sub_domains=len(sub_trees),
    )

    return {
        "domain_mapping": domain_mapping,
        "domain_display_names": domain_display_names,
        "domain_tree": domain_tree,
        "affected_domains": affected_domains,
    }
