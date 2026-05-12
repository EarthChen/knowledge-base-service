"""Classification and domain hierarchy nodes."""

from collections import Counter
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from store.schema import GraphNode, NodeLabel
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.dependency_graph import ModuleGraph, ModuleInfo
from wiki.domain_complexity import DomainComplexity
from wiki.entity_role_classifier import (
    DOMAIN_CLASSIFICATION_ENTITY_ROLES,
    EntityRoleClassifier,
    WikiEntityRole,
)
from wiki.nodes.utils import (
    _count_modules_in_domain_tree,
    _detect_oversized_leaves,
    _normalize_domain_tree,
)
from wiki.path_conventions import normalize_slug
from wiki.reasoning import TaskType, select_reasoning_level

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

            calls = props.get("calls", []) or []
            imports = props.get("imports", []) or []
            if isinstance(calls, list) and isinstance(imports, list):
                edge_count = len(calls) + len(imports)
            else:
                edge_count = 0

            children_count = int(props.get("inner_class_count", 0) or 0)

            role = classifier.classify(node, edge_count=edge_count, children_count=children_count)
            entity_roles[uid] = role
            role_counter[role] += 1

    log.info(
        "classify_entities_done",
        total=len(entity_roles),
        **{str(r): c for r, c in role_counter.items()},
    )
    return {
        "entity_roles": entity_roles,
        "role_stats": {str(r): c for r, c in role_counter.items()},
    }


async def classify_domains_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 2a-2b: classify modules into business domains using LLM.

    Filters to HAS_BUSINESS_LOGIC and ENTRY_POINT entities, then delegates to
    CrossRepoBusinessDomainPlanner for per-repo classification + cross-repo merge.
    """
    llm = (config or {}).get("configurable", {}).get("llm")
    business_id = state.get("business_id", "")
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    # Cap removed in v2; large module sets are batched by CrossRepoBusinessDomainPlanner /
    # BusinessDomainPlanner sub-batches instead of truncating here.
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

    biz_modules: dict[str, list[GraphNode]] = {}
    excluded_data_models = 0
    for repo, mod_list in modules.items():
        filtered: list[GraphNode] = []
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            if entity_roles.get(uid) not in DOMAIN_CLASSIFICATION_ENTITY_ROLES:
                continue
            props = mod_dict.get("properties", {})
            name = str(props.get("name", ""))
            path = str(props.get("path", "") or "")
            if path.startswith("<import:"):
                continue
            if _is_data_model(name, path):
                excluded_data_models += 1
                continue
            label_str = mod_dict.get("label", "Module")
            try:
                label = NodeLabel(label_str)
            except ValueError:
                label = NodeLabel.MODULE
            filtered.append(GraphNode(label=label, properties=props, uid=uid))
        if filtered:
            biz_modules[repo] = filtered

    biz_modules_base = biz_modules

    persistence = state.get("persistence")
    anchors: list[dict[str, Any]] = []
    pinned_raw: list[dict[str, Any]] = []
    if persistence:
        try:
            anchors = await persistence.list_domain_anchors(business_id) or []
            pinned_raw = await persistence.list_pinned_modules(business_id) or []
        except Exception:
            log.warning("domain_anchor_load_failed", exc_info=True)

    pinned_names = {str(p["module_name"]) for p in pinned_raw if p.get("module_name")}
    pinned_mapping: dict[str, str] = {
        str(p["module_name"]): str(p["domain_slug"])
        for p in pinned_raw
        if p.get("module_name") and p.get("domain_slug")
    }

    anchor_context = ""
    if anchors:
        lines = ["Existing domains (prefer reusing these):"]
        for a in anchors:
            slug = str(a.get("slug", "") or "")
            disp = str(a.get("display_name", "") or slug)
            lines.append(f"  - {slug} ({disp})")
        anchor_context = "\n".join(lines)

    pinned_nodes_by_repo: dict[str, list[GraphNode]] = {}
    biz_modules_work = biz_modules_base
    if pinned_names:
        for repo, nodes in biz_modules_base.items():
            pinned_here = [
                n for n in nodes
                if str(n.properties.get("name", "")) in pinned_names
            ]
            if pinned_here:
                pinned_nodes_by_repo[repo] = pinned_here
        biz_modules_work = {
            repo: [
                n for n in nodes
                if str(n.properties.get("name", "")) not in pinned_names
            ]
            for repo, nodes in biz_modules_base.items()
        }
        biz_modules_work = {r: v for r, v in biz_modules_work.items() if v}

    module_total = sum(len(v) for v in biz_modules_work.values())
    log.info(
        "classify_domains_filter",
        included=module_total,
        excluded_data_models=excluded_data_models,
    )

    capped_work = biz_modules_work
    classify_complexity = (
        DomainComplexity.LOW
        if module_total <= 10
        else DomainComplexity.MEDIUM
        if module_total <= 40
        else DomainComplexity.HIGH
    )
    classify_reasoning = select_reasoning_level(TaskType.CLASSIFY, classify_complexity)
    log.info(
        "classify_reasoning_selection",
        module_count=module_total,
        complexity=classify_complexity.value,
        reasoning_level=classify_reasoning.value,
    )

    is_incremental = state.get("is_incremental", False)
    if is_incremental and pinned_nodes_by_repo:
        repos_union = set(capped_work) | set(pinned_nodes_by_repo)
        planner_modules: dict[str, list[GraphNode]] = {}
        for repo in sorted(repos_union):
            nodes = list(capped_work.get(repo, []))
            nodes.extend(pinned_nodes_by_repo.get(repo, []))
            if nodes:
                planner_modules[repo] = nodes
    else:
        planner_modules = capped_work

    graph_store = (config or {}).get("configurable", {}).get("graph_store")
    pre_groups = None
    if graph_store is not None:
        from wiki.graph_pre_grouper import compute_pre_groups

        module_paths: dict[str, str] = {}
        for repo, nodes in planner_modules.items():
            for n in nodes:
                name = str(n.properties.get("name", ""))
                path = str(n.properties.get("path", "") or "")
                if name:
                    module_paths[name] = path
        try:
            pre_groups = await compute_pre_groups(
                graph_store, list(planner_modules.keys()), module_paths
            )
        except Exception:
            log.warning("pre_groups_computation_failed", exc_info=True)

    planner = CrossRepoBusinessDomainPlanner(llm)
    if is_incremental:
        domain_mapping, affected_domains = await planner.classify_incremental(
            business_id,
            planner_modules,
            anchor_context=anchor_context,
            pinned_module_domains=pinned_mapping or None,
        )
    else:
        domain_mapping = await planner.classify(
            business_id,
            planner_modules,
            pre_groups=pre_groups,
            anchor_context=anchor_context,
        )
        affected_domains = set(domain_mapping.keys())

        modules_by_repo = state.get("modules", {})
        repos = state.get("repositories") or []
        fallback_repo = repos[0] if repos else ""

        def _repo_for_pinned(mod_name: str) -> str:
            for repo_id, mod_list in modules_by_repo.items():
                for mod_dict in mod_list:
                    if str(mod_dict.get("properties", {}).get("name", "")) == mod_name:
                        return repo_id
            if fallback_repo:
                return fallback_repo
            return next(iter(modules_by_repo.keys()), "") if modules_by_repo else ""

        if pinned_mapping:
            for mod_name, domain_slug in pinned_mapping.items():
                repo = _repo_for_pinned(mod_name)
                pair = (repo, mod_name)
                bucket = domain_mapping.setdefault(domain_slug, [])
                if pair not in bucket:
                    bucket.append(pair)

    domain_display_names: dict[str, str] = dict(planner.domain_display_names)

    if graph_store is not None:
        from wiki.domain_stabilizer import DomainStabilizer

        stabilizer = DomainStabilizer(graph_store)
        try:
            rename_map = await stabilizer.stabilize(list(domain_mapping.keys()))
            affected_domains = {rename_map.get(d, d) for d in affected_domains}
            stabilized: dict[str, list] = {}
            updated_display: dict[str, str] = {}
            for proposed, pairs in domain_mapping.items():
                stable = rename_map.get(proposed, proposed)
                stabilized.setdefault(stable, []).extend(pairs)
                if proposed in domain_display_names:
                    updated_display[stable] = domain_display_names[proposed]
            if stabilized != domain_mapping:
                renamed = {p: s for p, s in rename_map.items() if p != s}
                log.info("domain_stabilizer_applied", renamed=renamed)
                domain_mapping = stabilized
                domain_display_names.update(updated_display)
        except Exception:
            log.warning("domain_stabilizer_failed", exc_info=True)

    log.info(
        "classify_domains_done",
        business_id=business_id,
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
    )
    return {
        "domain_mapping": domain_mapping,
        "affected_domains": list(affected_domains),
        "domain_display_names": domain_display_names,
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
        prev_biz = _count_modules_in_domain_tree(
            domain_tree if isinstance(domain_tree, list) else []
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


def _assign_slugs_to_tree(
    tree: list[dict[str, Any]],
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
) -> None:
    """Post-process domain tree to assign slug-based ``name`` and ``display_name``.

    Matches decomposer-created tree nodes back to classify-produced slugs
    using module membership overlap.  When no match is found, generates a
    slug via ``normalize_slug`` on the node's existing name.
    """
    module_to_slug: dict[str, str] = {}
    for slug, pairs in domain_mapping.items():
        for _, mod_name in pairs:
            module_to_slug[mod_name] = slug

    display_to_slug: dict[str, str] = {v: k for k, v in domain_display_names.items()}

    def _assign(nodes: list[dict[str, Any]], parent_slug: str = "") -> None:
        used_slugs: set[str] = set()
        for idx, node in enumerate(nodes):
            raw_name = node.get("name", "")
            modules = node.get("modules", [])
            slug = ""

            if raw_name in display_to_slug:
                slug = display_to_slug[raw_name]
            elif raw_name in domain_mapping:
                slug = raw_name

            if not slug and modules:
                slug_counts: dict[str, int] = {}
                for m in modules:
                    s = module_to_slug.get(m, "")
                    if s:
                        slug_counts[s] = slug_counts.get(s, 0) + 1
                if slug_counts:
                    slug = max(slug_counts, key=lambda k: slug_counts[k])

            if not slug:
                candidate = normalize_slug(raw_name)
                slug = candidate if candidate != "unnamed" else ""
            if not slug:
                slug = f"{parent_slug}-sub-{idx}" if parent_slug else f"domain-{idx}"

            while slug in used_slugs:
                slug = f"{slug}-{idx}"
            used_slugs.add(slug)

            node["display_name"] = node.get("display_name", "") or raw_name
            node["name"] = slug

            if slug in domain_display_names and not node.get("display_name"):
                node["display_name"] = domain_display_names[slug]

            _assign(node.get("children", []), parent_slug=slug)

    _assign(tree)


async def decompose_hierarchy_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 2c: build hierarchical domain tree from flat domain mapping."""
    import wiki.pipeline_nodes as pn

    llm = (config or {}).get("configurable", {}).get("llm")
    domain_mapping = state.get("domain_mapping", {})
    domain_display_names: dict[str, str] = state.get("domain_display_names", {})
    modules = state.get("modules", {})

    if not llm or not domain_mapping:
        log.info("decompose_hierarchy_skip", reason="no llm or empty domain_mapping")
        flat_tree = [
            {
                "name": slug,
                "display_name": domain_display_names.get(slug, slug),
                "modules": [m for _, m in pairs],
                "children": [],
            }
            for slug, pairs in domain_mapping.items()
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

    decomposer = pn.HierarchicalDecomposer(llm, max_depth=3, min_modules_for_nesting=3)

    graph_store = (config or {}).get("configurable", {}).get("graph_store")
    filtered_edges = []
    if graph_store is not None:
        from wiki.dependency_graph import ModuleDependencyGraph

        dep_graph = ModuleDependencyGraph(graph_store)
        repos = {repo_id for pairs in domain_mapping.values() for repo_id, _ in pairs}
        all_edges = []
        module_name_set = {m.name for m in all_module_infos}
        for repo in repos:
            try:
                repo_graph = await dep_graph.build(repo)
                all_edges.extend(repo_graph.edges)
            except Exception:
                log.warning("decompose_load_edges_failed", repo=repo, exc_info=True)
        filtered_edges = [e for e in all_edges if e.source in module_name_set and e.target in module_name_set]
        entry_points = dep_graph._identify_entry_points(all_module_infos, filtered_edges)
        module_graph = ModuleGraph(modules=all_module_infos, edges=filtered_edges, entry_points=entry_points)
    else:
        module_graph = ModuleGraph(modules=all_module_infos, edges=filtered_edges, entry_points=[])

    try:
        raw_tree = await decomposer.decompose(all_module_infos, module_graph)
        domain_tree = _normalize_domain_tree(raw_tree)
    except Exception:
        log.warning("decompose_hierarchy_failed", exc_info=True)
        domain_tree = [
            {
                "name": slug,
                "display_name": domain_display_names.get(slug, slug),
                "modules": [m for _, m in pairs],
                "children": [],
            }
            for slug, pairs in domain_mapping.items()
        ]

    _assign_slugs_to_tree(domain_tree, domain_mapping, domain_display_names)

    # P0.2 Sub-B+C: detect oversized leaves and rebalance (one pass only)
    oversized = _detect_oversized_leaves(domain_tree)
    if oversized and llm:
        rebalance_decomposer = pn.HierarchicalDecomposer(llm, max_depth=1, min_modules_for_nesting=3)
        for leaf in oversized:
            leaf_module_names_set = set(leaf.get("modules", []))
            leaf_modules = [m for m in all_module_infos if m.name in leaf_module_names_set]
            if not leaf_modules:
                continue
            leaf_module_names_set_edges = set(leaf_module_names_set)
            rebal_edges = [
                e
                for e in filtered_edges
                if e.source in leaf_module_names_set_edges or e.target in leaf_module_names_set_edges
            ]
            rebal_graph = ModuleGraph(modules=leaf_modules, edges=rebal_edges, entry_points=[])
            try:
                sub_tree = await rebalance_decomposer.decompose(leaf_modules, rebal_graph)
                if sub_tree and len(sub_tree) > 1:
                    leaf["children"] = _normalize_domain_tree(sub_tree)
                    leaf["modules"] = []
                    log.info("leaf_rebalanced", domain=leaf.get("name"), sub_domains=len(sub_tree))
            except Exception:
                log.warning("leaf_rebalance_failed", domain=leaf.get("name"), exc_info=True)

    log.info("decompose_hierarchy_done", domains=len(domain_tree) if domain_tree else 0)
    return {"domain_tree": domain_tree}


async def set_review_status_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark domain tree as pending_review and continue (non-blocking)."""
    review_status = dict(state.get("review_status", {}))
    review_status["domain_tree"] = "pending_review"

    log.info("set_review_status_marked_review", tree_size=len(state.get("domain_tree") or []))
    return {"review_status": review_status}
