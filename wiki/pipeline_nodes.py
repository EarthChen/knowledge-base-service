"""LangGraph pipeline node implementations for Wiki generation."""

import re
from collections import Counter
from typing import Any

from langchain_core.runnables import RunnableConfig
from log import get_logger
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.data_collector import PageData
from wiki.models import PageType, SourceLocation, WikiPage
from wiki.semantic_diagram_gen import SemanticDiagramGenerator
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.dependency_graph import HierarchicalDecomposer, ModuleGraph, ModuleInfo
from wiki.entity_role_classifier import EntityRoleClassifier, WikiEntityRole
from wiki.token_budget import TokenBudgetResolver
from wiki.topic_page_composer import TopicPageComposer

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
        "role_stats": dict(role_counter),
    }


async def classify_domains_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 2a-2b: classify modules into business domains using LLM.

    Filters to HAS_BUSINESS_LOGIC entities only, then delegates to
    CrossRepoBusinessDomainPlanner for per-repo classification + cross-repo merge.
    """
    llm = (config or {}).get("configurable", {}).get("llm")
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


async def decompose_hierarchy_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 2c: build hierarchical domain tree from flat domain mapping."""
    llm = (config or {}).get("configurable", {}).get("llm")
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


def _call_target_module(call: str) -> str | None:
    c = str(call).strip()
    if "." in c:
        return c.split(".", 1)[0]
    return None


def _build_page_data_for_semantic_diagrams(
    domain_name: str,
    module_names: list[str],
    module_index: dict[str, dict],
) -> PageData:
    """Minimal PageData for SemanticDiagramGenerator (domain modules + CALLS edges)."""
    children: list[GraphNode] = []
    edges: list[GraphEdge] = []
    summaries: list[str] = []
    name_to_uid: dict[str, str] = {}

    for mod_name in module_names:
        mod_dict = module_index.get(mod_name, {})
        props_raw = mod_dict.get("properties", {})
        props: dict[str, str | int | float | list[str]] = dict(props_raw) if isinstance(props_raw, dict) else {}
        uid = mod_dict.get("uid", f"Module::{mod_name}:0")
        name_to_uid[mod_name] = uid
        label_str = mod_dict.get("label", "Module")
        try:
            label = NodeLabel(label_str)
        except ValueError:
            label = NodeLabel.MODULE
        children.append(GraphNode(label=label, properties=props, uid=uid))
        bs = props.get("business_summary", "")
        if isinstance(bs, str) and bs.strip():
            summaries.append(bs)

    for mod_name in module_names:
        mod_dict = module_index.get(mod_name, {})
        src_uid = mod_dict.get("uid", f"Module::{mod_name}:0")
        calls = mod_dict.get("properties", {}).get("calls", []) or []
        if not isinstance(calls, list):
            continue
        for call in calls:
            tgt_mod = _call_target_module(str(call))
            if not tgt_mod or tgt_mod not in name_to_uid:
                continue
            tgt_uid = name_to_uid[tgt_mod]
            if tgt_uid == src_uid:
                continue
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.CALLS,
                    source_uid=src_uid,
                    target_uid=tgt_uid,
                )
            )

    joined_summary = " ".join(summaries)[:4000]
    center_props: dict[str, str | int | float | list[str]] = {
        "name": domain_name,
        "business_summary": joined_summary,
        "description": f"Business domain {domain_name}",
    }
    center = GraphNode(
        label=NodeLabel.MODULE,
        properties=center_props,
        uid=f"Domain::{domain_name}",
    )
    empty_loc = SourceLocation(
        file_path="", start_line=0, end_line=0, fqn=domain_name, repository=""
    )
    return PageData(
        node=center,
        edges=edges,
        children=children,
        source_location=empty_loc,
        method_locations=[],
        business_summary=joined_summary if joined_summary else None,
        methods=[],
    )


def _collect_leaf_domains(tree: list[dict[str, Any]], parent: str = "root") -> list[dict[str, Any]]:
    """Recursively collect leaf domains (no children or children are empty)."""
    leaves: list[dict[str, Any]] = []
    for node in tree:
        children = node.get("children", [])
        node_with_parent = {**node, "parent": parent}
        if not children:
            leaves.append(node_with_parent)
        else:
            leaves.extend(_collect_leaf_domains(children, parent=node.get("name", "unknown")))
    return leaves


async def compose_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 3: generate topic pages for each leaf domain."""
    llm = (config or {}).get("configurable", {}).get("llm")
    domain_tree = state.get("domain_tree") or []
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    module_index: dict[str, dict] = {}
    for _repo, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                module_index[name] = mod_dict

    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")
    composer = TopicPageComposer(llm, token_budget=budget)

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    leaf_domains = _collect_leaf_domains(domain_tree)

    for leaf in leaf_domains:
        domain_name = leaf.get("name", "unknown")
        module_names = leaf.get("modules", [])

        biz_entities = []
        data_models = []
        for mod_name in module_names:
            mod_dict = module_index.get(mod_name, {})
            uid = mod_dict.get("uid", f"Module::{mod_name}:0")
            role = entity_roles.get(uid, "supporting")
            props = mod_dict.get("properties", {})

            if role == "has_business_logic":
                biz_entities.append({
                    "uid": uid,
                    "name": mod_name,
                    "summary": str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                    "methods": [str(m) for m in (props.get("methods", []) or [])[:10]],
                    "calls": [str(c) for c in (props.get("calls", []) or [])[:15]],
                })
            elif role == "data_model":
                data_models.append({
                    "uid": uid,
                    "name": mod_name,
                    "type": "DTO",
                    "fields": [str(f) for f in (props.get("fields", []) or [])[:8]],
                })

        if len(data_models) > 20:
            log.info("data_models_truncated", domain=domain_name, total=len(data_models), kept=20)

        domain_input = {
            "name": domain_name,
            "parent": leaf.get("parent", "root"),
            "biz_entities": biz_entities,
            "data_models": data_models[:20],
            "sibling_summaries": [],
        }

        try:
            pages = await composer.compose_leaf_domain(domain_input)
            if llm and pages:
                diag_gen = SemanticDiagramGenerator(llm)
                page_data = _build_page_data_for_semantic_diagrams(
                    domain_name, module_names, module_index
                )
                try:
                    digest = diag_gen._build_entity_digest(page_data)
                except Exception:
                    log.warning(
                        "diagram_digest_build_failed",
                        domain=domain_name,
                        exc_info=True,
                    )
                    digest = ""
                for page_dict in pages:
                    page_type = (
                        PageType.DOMAIN_OVERVIEW
                        if page_dict.get("page_type") == "domain_overview"
                        else PageType.TOPIC
                    )
                    try:
                        diagrams = await diag_gen.generate_for_page(
                            page_data, page_type, digest, "full"
                        )
                        if diagrams:
                            page_dict["diagrams"] = [
                                {
                                    "title": d.title,
                                    "diagram_type": d.diagram_type.value
                                    if hasattr(d.diagram_type, "value")
                                    else str(d.diagram_type),
                                    "content": d.content,
                                }
                                for d in diagrams
                            ]
                    except Exception:
                        log.warning(
                            "diagram_generation_failed",
                            page=page_dict.get("title"),
                            exc_info=True,
                        )
            all_pages.extend(pages)
            generated_uids.extend(p.get("path", "") for p in pages)
        except Exception:
            log.warning("compose_pages_domain_failed", domain=domain_name, exc_info=True)

    log.info("compose_pages_done", total_pages=len(all_pages), domains_processed=len(leaf_domains))
    return {"pages": all_pages, "generated_topic_pages": generated_uids}


async def heal_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Regenerate pages that failed the quality gate (replaces them via merge_wiki_pages)."""
    llm = (config or {}).get("configurable", {}).get("llm")
    evaluator = WikiQualityEvaluator()
    heal_attempts = dict(state.get("heal_attempts", {}))
    heal_hints: dict[str, str] = dict(state.get("heal_hints", {}))
    healed_pages: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page_path in state.get("pages_to_heal", []):
        if page_path in seen:
            continue
        seen.add(page_path)
        heal_attempts[page_path] = heal_attempts.get(page_path, 0) + 1

        page_dict = next(
            (p for p in state.get("pages", []) if p.get("path") == page_path),
            None,
        )
        if not page_dict:
            continue

        try:
            page = WikiPage.from_dict(page_dict)
            try:
                bench = evaluator.bench_score(page)
                hint = evaluator.build_heal_prompt_hint_v2(bench)
            except Exception:
                log.warning("heal_bench_score_failed", page=page_path, exc_info=True)
                score = evaluator.structural_check(page)
                hint = evaluator.build_heal_prompt_hint(score)
            heal_hints[page_path] = hint
        except Exception:
            log.warning("heal_page_analysis_failed", page=page_path, exc_info=True)
            continue

        if llm:
            heal_budget = TokenBudgetResolver().budget("topic_page_generate")
            content_char_limit = heal_budget * 3
            domain_name = page_dict.get("domain", "unknown")
            domain_context = ""
            for d in state.get("domain_tree", []) or []:
                if d.get("name") == domain_name:
                    modules = d.get("modules", [])
                    domain_context = (
                        f"Domain: {domain_name}, Modules: {', '.join(str(m) for m in modules[:10])}"
                    )
                    break

            heal_prompt = (
                f"Improve this wiki page for domain '{domain_name}'.\n\n"
                f"Domain context: {domain_context}\n\n"
                f"Quality issues found:{hint}\n\n"
                f"Current content:\n{page_dict.get('content', '')[:content_char_limit]}\n\n"
                "Generate an improved version with these required sections:\n"
                "1. ## 业务概述 (business overview)\n"
                "2. ## 核心业务流程 (include Mermaid sequenceDiagram or flowchart)\n"
                "3. ## 核心服务详情 (detailed service descriptions)\n"
                "4. ## 数据模型 (data models table if applicable)\n"
                "5. ## 关联主题 ([[wiki-link]] to related domains)\n\n"
                "Requirements:\n"
                "- Include at least one Mermaid diagram\n"
                "- Use Chinese for business descriptions\n"
                "- Focus on business logic, not framework details\n"
            )
            try:
                new_content = await llm.generate(
                    heal_prompt,
                    system=(
                        "You are a technical wiki author specializing in business domain documentation. "
                        "Output Markdown with Mermaid diagrams. Use Chinese for business descriptions. "
                        "Focus on business logic and service interactions. "
                        "Do NOT explain frameworks or annotations."
                    ),
                    max_tokens=heal_budget,
                )
                healed_page = {**page_dict, "content": new_content}
                healed_pages.append(healed_page)
                log.info("page_healed", page=page_path, attempt=heal_attempts[page_path])
            except Exception:
                log.warning("heal_page_regen_failed", page=page_path, exc_info=True)
        else:
            log.info("page_heal_skip_no_llm", page=page_path)

    log.info("heal_pages_done", healed_count=len(healed_pages))
    return {
        "pages_to_heal": [],
        "heal_attempts": heal_attempts,
        "heal_hints": heal_hints,
        "pages": healed_pages,
    }


async def synthesize_overviews_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 4a+4b: generate domain overviews and system overview."""
    llm = (config or {}).get("configurable", {}).get("llm")
    pages = list(state.get("pages", []))
    domain_tree = state.get("domain_tree") or []

    if not llm:
        return {}

    domain_summaries = []
    for domain in domain_tree:
        name = domain.get("name", "")
        domain_pages = [p for p in pages if p.get("domain") == name]
        summary = domain_pages[0]["content"][:200] if domain_pages else ""
        domain_summaries.append(f"- **{name}**: {summary}")

    if domain_summaries:
        sys_prompt = (
            "Generate a system overview wiki page summarizing the entire codebase.\n\n"
            f"Domains:\n" + "\n".join(domain_summaries) + "\n\n"
            "Output:\n"
            "1. ## 系统概览 (high-level description of the system)\n"
            "2. ## 架构图 (Mermaid diagram showing domain relationships)\n"
            "3. ## 域列表 (with links to each domain)\n"
        )
        overview_content = await llm.generate(
            sys_prompt,
            system="You are a technical wiki author. Output Markdown with Mermaid.",
        )
        overview_page = {
            "title": "System Overview",
            "content": overview_content,
            "path": "wiki/_system_overview",
            "page_type": "system_overview",
            "domain": "_system",
        }
        return {"pages": [overview_page], "system_overview_uid": "wiki/_system_overview"}

    return {}


async def create_links_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 4c-4d: resolve cross-links and prepare link metadata for persistence."""
    pages = state.get("pages", [])
    page_titles = {p.get("title", "").lower(): p.get("path", "") for p in pages}
    page_paths = {
        p.get("path", "").rsplit("/", 1)[-1].lower(): p.get("path", "")
        for p in pages
        if p.get("path")
    }

    link_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    resolved_links: dict[str, list[dict[str, str]]] = {}

    for page in pages:
        page_path = page.get("path", "")
        content = page.get("content", "")
        links: list[dict[str, str]] = []

        for match in link_pattern.finditer(content):
            link_text = match.group(1)
            key = link_text.lower()
            target = page_titles.get(key) or page_paths.get(key)
            if target and target != page_path:
                links.append({"from_text": link_text, "target_path": target})
                log.debug("wiki_link_resolved", source=page_path, target=target)

        if links:
            resolved_links[page_path] = links

    log.info(
        "create_links_done",
        pages_with_links=len(resolved_links),
        total_links=sum(len(v) for v in resolved_links.values()),
    )
    return {"resolved_links": resolved_links}
