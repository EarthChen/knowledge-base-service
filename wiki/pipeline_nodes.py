"""LangGraph pipeline node implementations for Wiki generation."""

import asyncio
import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from core.config import get_settings
from langchain_core.runnables import RunnableConfig
from core.log import get_logger
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.data_collector import PageData
from wiki.models import LeafSummary, PageType, SourceLocation, WikiPage
from wiki.semantic_diagram_gen import SemanticDiagramGenerator
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.dependency_graph import DomainNode, HierarchicalDecomposer, ModuleGraph, ModuleInfo
from wiki.system_overview_composer import SystemOverviewComposer
from wiki.entity_role_classifier import (
    DOMAIN_CLASSIFICATION_ENTITY_ROLES,
    EntityRoleClassifier,
    WikiEntityRole,
)
from wiki.domain_complexity import DomainComplexity, DomainComplexityScorer
from wiki.reasoning import (
    GuidedPromptEnhancer,
    MultiStepReasoner,
    ReasoningLevel,
    TaskType,
    select_reasoning_level,
)
from wiki.domain_overview_composer import DomainOverviewComposer
from wiki.topic_page_composer import TopicPageComposer
from wiki.topic_structure_planner import TopicBasedStructurePlanner
from wiki.json_robust import parse_json_robust_sync
from wiki.prompts import SYSTEM_WIKI_HEAL, SYSTEM_WIKI_PARENT_OVERVIEW
from wiki.snippet_selector import select_key_snippets
from wiki.token_budget import TokenBudgetCalculator, TokenBudgetResolver

log = get_logger(__name__)

_COMPOSE_CONCURRENCY = get_settings().wiki.compose_concurrency


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

    biz_modules: dict[str, list[GraphNode]] = {}
    for repo, mod_list in modules.items():
        filtered: list[GraphNode] = []
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            if entity_roles.get(uid) in DOMAIN_CLASSIFICATION_ENTITY_ROLES:
                props = mod_dict.get("properties", {})
                label_str = mod_dict.get("label", "Module")
                try:
                    label = NodeLabel(label_str)
                except ValueError:
                    label = NodeLabel.MODULE
                filtered.append(GraphNode(label=label, properties=props, uid=uid))
        if filtered:
            biz_modules[repo] = filtered

    module_total = sum(len(v) for v in biz_modules.values())
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

    planner = CrossRepoBusinessDomainPlanner(llm)
    domain_mapping = await planner.classify(business_id, biz_modules)

    graph_store = (config or {}).get("configurable", {}).get("graph_store")
    if graph_store is not None:
        from wiki.domain_stabilizer import DomainStabilizer

        stabilizer = DomainStabilizer(graph_store)
        try:
            rename_map = await stabilizer.stabilize(list(domain_mapping.keys()))
            stabilized: dict[str, list] = {}
            for proposed, pairs in domain_mapping.items():
                stable = rename_map.get(proposed, proposed)
                stabilized.setdefault(stable, []).extend(pairs)
            if stabilized != domain_mapping:
                renamed = {p: s for p, s in rename_map.items() if p != s}
                log.info("domain_stabilizer_applied", renamed=renamed)
                domain_mapping = stabilized
        except Exception:
            log.warning("domain_stabilizer_failed", exc_info=True)

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


def _normalize_domain_tree(raw_tree: list | None) -> list[dict[str, Any]]:
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
                "children": _normalize_domain_tree(getattr(node, "children", [])),
            }
        elif isinstance(node, dict):
            d = {
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "modules": node.get("modules", []),
                "children": _normalize_domain_tree(node.get("children", [])),
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
        domain_tree = _normalize_domain_tree(raw_tree)
    except Exception:
        log.warning("decompose_hierarchy_failed", exc_info=True)
        domain_tree = [
            {"name": domain, "modules": [m for _, m in pairs], "children": []}
            for domain, pairs in domain_mapping.items()
        ]

    log.info("decompose_hierarchy_done", domains=len(domain_tree) if domain_tree else 0)
    return {"domain_tree": domain_tree}


async def set_review_status_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark domain tree as pending_review and continue (non-blocking)."""
    review_status = dict(state.get("review_status", {}))
    review_status["domain_tree"] = "pending_review"

    log.info("set_review_status_marked_review", tree_size=len(state.get("domain_tree") or []))
    return {"review_status": review_status}


def _call_target_module(call: str) -> str | None:
    c = str(call).strip()
    if "." in c:
        return c.split(".", 1)[0]
    return None


def _build_page_data_for_semantic_diagrams(
    domain_name: str,
    module_names: list[str],
    module_index: dict[str, list[dict]],
) -> PageData:
    """Minimal PageData for SemanticDiagramGenerator (domain modules + CALLS edges)."""
    children: list[GraphNode] = []
    edges: list[GraphEdge] = []
    summaries: list[str] = []
    name_to_uid: dict[str, str] = {}

    for mod_name in module_names:
        for mod_dict in module_index.get(mod_name, []):
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
        for mod_dict in module_index.get(mod_name, []):
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


_OVERVIEW_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^##\s*业务概述\s*$", re.MULTILINE),
    re.compile(r"^##\s*Overview\s*$", re.MULTILINE),
    re.compile(r"^##\s*Summary\s*$", re.MULTILINE),
    re.compile(r"^##\s*概述\s*$", re.MULTILINE),
)

_SUMMARY_MAX_LEN = 300


def _normalize_pages_map(pages: Any) -> dict[str, dict[str, Any]]:
    """Build path -> page dict whether ``pages`` is a mapping or list of page dicts."""
    if isinstance(pages, dict):
        return {str(k): v for k, v in pages.items() if isinstance(v, dict)}
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(pages, list):
        return out
    for p in pages:
        if not isinstance(p, dict):
            continue
        path = p.get("path")
        if path:
            out[str(path)] = p
    return out


def _find_page_for_leaf_domain(
    pages_by_path: dict[str, dict[str, Any]], domain_name: str
) -> dict[str, Any] | None:
    """Locate the wiki page for a leaf domain (path contains domain slug)."""
    if not domain_name:
        return None
    preferred = f"wiki/{domain_name}"
    if preferred in pages_by_path:
        return pages_by_path[preferred]
    if domain_name in pages_by_path:
        return pages_by_path[domain_name]
    suffix = f"/{domain_name}"
    for path, page in pages_by_path.items():
        if path == domain_name or path.rstrip("/").endswith(suffix):
            return page
    return None


def _extract_summary_from_content(content: str) -> str:
    """Rule-based summary: overview section, then first paragraph after first heading, else truncate."""
    text = content or ""
    if not text.strip():
        return ""

    for pattern in _OVERVIEW_SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            start = match.end()
            remainder = text[start:]
            stop = remainder.find("\n## ")
            body = remainder if stop < 0 else remainder[:stop]
            out = body.strip()
            if out:
                return out[:_SUMMARY_MAX_LEN]

    lines = text.splitlines()
    heading_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("#"):
            heading_idx = idx
            break
    if heading_idx is not None:
        i = heading_idx + 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        para_parts: list[str] = []
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                break
            if line.strip().startswith("#"):
                break
            para_parts.append(line.strip())
            i += 1
        para = " ".join(para_parts).strip()
        if para:
            return para[:_SUMMARY_MAX_LEN]

    return text.strip()[:_SUMMARY_MAX_LEN]


def _extract_key_entities(page: dict[str, Any]) -> list[str]:
    """Best-effort entity names from page metadata; empty if unknown."""
    meta = page.get("metadata") or {}
    if not isinstance(meta, dict):
        return []
    raw = meta.get("key_entities")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x is not None and str(x).strip()]


async def summarize_leaves_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract structured summaries for leaf-domain wiki pages.

    Prefers ``executive_summary`` from page metadata (populated by earlier compose/LLM
    steps when available); otherwise falls back to rule-based extraction from Markdown.
    """
    domain_tree = state.get("domain_tree") or []
    if not isinstance(domain_tree, list):
        domain_tree = []
    pages_by_path = _normalize_pages_map(state.get("pages"))
    leaf_domains = _collect_leaf_domains(domain_tree)
    leaf_summaries: dict[str, dict[str, Any]] = {}

    for leaf in leaf_domains:
        name = str(leaf.get("name") or "").strip()
        if not name:
            continue
        page = _find_page_for_leaf_domain(pages_by_path, name)
        if not page:
            continue
        metadata = page.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        module_count = len(leaf.get("modules", [])) if isinstance(leaf.get("modules"), list) else 0
        key_entities = _extract_key_entities(page)
        exec_summary = metadata.get("executive_summary")
        if isinstance(exec_summary, str) and exec_summary.strip():
            ls = LeafSummary(
                domain_name=name,
                summary_text=exec_summary.strip(),
                module_count=module_count,
                key_entities=key_entities,
                source="llm",
            )
            leaf_summaries[name] = asdict(ls)
        else:
            raw_content = page.get("content")
            content = str(raw_content) if raw_content is not None else ""
            extracted = _extract_summary_from_content(content)
            ls = LeafSummary(
                domain_name=name,
                summary_text=extracted,
                module_count=module_count,
                key_entities=key_entities,
                source="rule_extracted",
            )
            leaf_summaries[name] = asdict(ls)

    return {"leaf_summaries": leaf_summaries}


def has_parent_domains(state: dict[str, Any]) -> bool:
    """True if any top-level domain node has non-empty children (nested tree)."""
    domain_tree = state.get("domain_tree", []) or []
    for domain in domain_tree:
        children = domain.get("children", []) or []
        if children:
            return True
    return False


def _collect_parent_domains_by_level(
    domain_tree: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Collect parent domains (nodes with children) by depth; deepest level first."""
    levels: list[list[dict[str, Any]]] = []

    def _traverse(nodes: list[Any], depth: int) -> None:
        while len(levels) <= depth:
            levels.append([])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            children = node.get("children", []) or []
            if not isinstance(children, list):
                children = []
            if children:
                levels[depth].append(node)
                _traverse(children, depth + 1)

    if not isinstance(domain_tree, list):
        return []
    _traverse(domain_tree, 0)
    levels.reverse()
    return [lvl for lvl in levels if lvl]


def _collect_module_names_in_subtree(domain: dict[str, Any]) -> list[str]:
    names: list[str] = []
    mods = domain.get("modules", []) or []
    if isinstance(mods, list):
        names.extend(str(m) for m in mods)
    for child in domain.get("children", []) or []:
        if isinstance(child, dict):
            names.extend(_collect_module_names_in_subtree(child))
    return names


def _module_dicts_for_names(
    module_names: list[str],
    modules_by_repo: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve module dicts from pipeline ``modules`` (first occurrence wins per name)."""
    index: dict[str, dict[str, Any]] = {}
    if isinstance(modules_by_repo, dict):
        for _repo, mod_list in modules_by_repo.items():
            if not isinstance(mod_list, list):
                continue
            for mod_dict in mod_list:
                if not isinstance(mod_dict, dict):
                    continue
                name = mod_dict.get("properties", {}).get("name", "")
                if name and name not in index:
                    index[name] = mod_dict
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mn in module_names:
        if mn in seen:
            continue
        m = index.get(mn)
        if m:
            out.append(m)
            seen.add(mn)
    return out


async def compose_parent_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Generate overview wiki pages for parent domains from child summaries (bottom-up)."""
    domain_tree = state.get("domain_tree", []) or []
    if not isinstance(domain_tree, list):
        domain_tree = []

    if not has_parent_domains({**state, "domain_tree": domain_tree}):
        return {"pages": []}

    llm = (config or {}).get("configurable", {}).get("llm")
    if not llm:
        log.info("compose_parent_pages_skip", reason="no_llm")
        return {"pages": []}

    leaf_summaries: dict[str, Any] = dict(state.get("leaf_summaries", {}) or {})
    modules = state.get("modules", {})
    entity_roles_raw = state.get("entity_roles", {})
    entity_roles = entity_roles_raw if isinstance(entity_roles_raw, dict) else {}

    budget_resolver = TokenBudgetResolver()
    gen_budget = budget_resolver.budget("topic_page_generate")
    budget_calc = TokenBudgetCalculator()

    parent_levels = _collect_parent_domains_by_level(domain_tree)
    all_parent_pages: list[dict[str, Any]] = []

    for level_parents in parent_levels:
        for parent_domain in level_parents:
            parent_name = str(parent_domain.get("name", "") or "").strip()
            if not parent_name:
                continue
            children = parent_domain.get("children", []) or []
            if not isinstance(children, list):
                continue
            child_names: list[str] = []
            for c in children:
                if isinstance(c, dict):
                    cn = str(c.get("name", "") or "").strip()
                    if cn:
                        child_names.append(cn)

            child_summary_lines: list[str] = []
            for cn in child_names:
                summary = leaf_summaries.get(cn, {})
                if not isinstance(summary, dict):
                    summary = {}
                raw_text = summary.get("summary_text", f"{cn} domain")
                text = raw_text if isinstance(raw_text, str) else str(raw_text)
                child_summary_lines.append(f"- **{cn}**: {text}")
            child_summaries_text = "\n".join(child_summary_lines)

            mod_names = _collect_module_names_in_subtree(parent_domain)
            all_mod_dicts = _module_dicts_for_names(mod_names, modules)
            snippet_budget = budget_calc.budget_for_snippets(len(all_mod_dicts))
            snippets = select_key_snippets(
                all_mod_dicts,
                entity_roles,
                budget_tokens=snippet_budget,
            )
            snippet_lines = [s.format_for_prompt() for s in snippets]
            snippet_text = (
                "\n".join(snippet_lines) if snippet_lines else "No code signatures available."
            )

            prompt = (
                f'Create a domain overview page for "{parent_name}" that synthesizes '
                "its sub-domains.\n\n"
                "## Sub-domain Summaries\n"
                f"{child_summaries_text}\n\n"
                "## Key Code Interfaces\n"
                f"{snippet_text}\n\n"
                'Return ONLY valid JSON (no markdown fences) with keys: "title", '
                '"content", "executive_summary", "page_type".\n'
                "The content should explain how sub-domains relate, describe data flow, "
                "and reference key interfaces naturally.\n"
                "executive_summary should be 150-300 chars capturing the domain's core purpose."
            )
            try:
                response = await llm.generate(
                    prompt,
                    system=SYSTEM_WIKI_PARENT_OVERVIEW,
                    max_tokens=gen_budget,
                )
                raw = response if isinstance(response, str) else str(response)
                parsed = parse_json_robust_sync(raw)
                if not isinstance(parsed, dict):
                    log.warning("compose_parent_pages_bad_json", domain=parent_name)
                    continue
                title = parsed.get("title", parent_name)
                content = parsed.get("content", "")
                exec_summary = parsed.get("executive_summary", "")
                page_type_val = parsed.get("page_type") or "domain_overview"
                page_type = str(page_type_val)
                slug = parent_name.strip().lower().replace(" ", "_")
                page_dict: dict[str, Any] = {
                    "path": f"wiki/{slug}",
                    "title": title,
                    "content": content,
                    "page_type": page_type,
                    "domain": parent_name,
                    "metadata": {"executive_summary": exec_summary},
                }
                all_parent_pages.append(page_dict)
                exec_str = str(exec_summary) if exec_summary is not None else ""
                parent_ls = LeafSummary(
                    domain_name=parent_name,
                    summary_text=exec_str[:300],
                    module_count=len(mod_names),
                    key_entities=child_names,
                    source="llm",
                )
                leaf_summaries[parent_name] = asdict(parent_ls)
            except Exception:
                log.warning(
                    "compose_parent_pages_failed",
                    domain=parent_name,
                    exc_info=True,
                )

    return {"pages": all_parent_pages, "leaf_summaries": leaf_summaries}


def _find_domain_in_tree(domain_tree: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Recursively find a domain node by name in the domain tree."""
    for domain in domain_tree:
        if domain.get("name") == name:
            return domain
        found = _find_domain_in_tree(domain.get("children", []) or [], name)
        if found is not None:
            return found
    return None


def _flatten_all_domains(domain_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every domain node in the tree (including nested children), preorder."""
    nodes: list[dict[str, Any]] = []
    for domain in domain_tree:
        nodes.append(domain)
        nodes.extend(_flatten_all_domains(domain.get("children", []) or []))
    return nodes


_BUSINESS_SUMMARY_SECTION = re.compile(
    r"^##\s*业务概述\s*$",
    re.MULTILINE,
)


def _summarize_domain_for_system_overview(domain_name: str, pages: list[dict[str, Any]]) -> str:
    """Use ## 业务概述 body when present, else first ~300 chars of the best matching page."""
    domain_pages = [p for p in pages if p.get("domain") == domain_name]
    if not domain_pages:
        return ""
    preferred: str | None = None
    for type_rank in ("domain_overview", "topic"):
        for p in domain_pages:
            if p.get("page_type") == type_rank:
                preferred = p.get("content") or ""
                break
        if preferred is not None:
            break
    content = preferred if preferred is not None else (domain_pages[0].get("content") or "")
    if not content.strip():
        return ""
    match = list(_BUSINESS_SUMMARY_SECTION.finditer(content))
    if match:
        start = match[-1].end()
        remainder = content[start:]
        stop = remainder.find("\n## ")
        body = remainder if stop < 0 else remainder[:stop]
        out = body.strip()
        return out[:800] if out else ""
    return content.strip()[:300]


def _domain_tree_dict_to_nodes(domains: list[dict[str, Any]]) -> list[DomainNode]:
    """Convert serialized domain_tree dicts to DomainNode hierarchy for SystemOverviewComposer."""
    nodes: list[DomainNode] = []
    for d in domains:
        children_raw = d.get("children") or []
        kids = (
            _domain_tree_dict_to_nodes(children_raw)
            if isinstance(children_raw, list)
            else []
        )
        modules_raw = d.get("modules") or []
        mods = [str(m) for m in modules_raw] if isinstance(modules_raw, list) else []
        nodes.append(
            DomainNode(
                name=str(d.get("name", "") or ""),
                description=str(d.get("description", "") or ""),
                modules=mods,
                children=kids,
            ),
        )
    return nodes


def _stats_by_repo_from_pipeline_modules(modules_by_repo: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Approximate repo stats from pipeline ``modules`` shape (GraphNode-ish dicts)."""
    stats: dict[str, dict[str, int]] = {}
    if not isinstance(modules_by_repo, dict):
        return stats
    for repo, mod_list in modules_by_repo.items():
        if not isinstance(mod_list, list):
            continue
        module_count = 0
        class_count = 0
        fn_count = 0
        for mod in mod_list:
            if not isinstance(mod, dict):
                continue
            label = str(mod.get("label") or "Module")
            props = mod.get("properties") or {}
            if not isinstance(props, dict):
                props = {}
            if label.upper() == "CLASS":
                class_count += 1
            elif label.upper() == "FUNCTION":
                fn_count += 1
            else:
                module_count += 1
            mc = props.get("methods_count")
            if isinstance(mc, int):
                fn_count += mc
            elif isinstance(mc, str) and mc.isdigit():
                fn_count += int(mc)
        stats[str(repo)] = {
            "module_count": module_count,
            "class_count": class_count,
            "function_count": fn_count,
        }
    return stats


def _entry_points_by_repo_from_modules(modules_by_repo: dict[str, Any]) -> dict[str, list[str]]:
    """Collect likely HTTP / listener entry modules from annotations (pipeline module dicts)."""
    out: dict[str, list[str]] = {}
    if not isinstance(modules_by_repo, dict):
        return out
    entry_markers = ("@RestController", "@Controller", "@KafkaListener", "@RocketMQMessageListener")

    def _is_entry(props: dict[str, Any]) -> bool:
        if props.get("is_entry_point"):
            return True
        anns = props.get("annotations") or []
        if not isinstance(anns, list):
            return False
        merged = " ".join(str(a) for a in anns)
        return any(marker in merged for marker in entry_markers)

    for repo, mod_list in modules_by_repo.items():
        eps: list[str] = []
        if isinstance(mod_list, list):
            for mod in mod_list:
                if not isinstance(mod, dict):
                    continue
                props = mod.get("properties") or {}
                if not isinstance(props, dict):
                    continue
                name = props.get("name")
                if _is_entry(props) and name:
                    eps.append(str(name))
        out[str(repo)] = eps
    return out


def _count_modules_in_domain_tree(domain_tree: Any) -> int:
    """Sum module counts on every domain node at all nesting levels."""
    if not isinstance(domain_tree, list):
        return 0
    total = 0
    for d in domain_tree:
        if not isinstance(d, dict):
            continue
        mods = d.get("modules", []) or []
        total += len(mods)
        total += _count_modules_in_domain_tree(d.get("children", []) or [])
    return total


async def _compose_single_leaf_domain(
    leaf: dict[str, Any],
    module_index: dict[str, list[dict]],
    entity_roles: dict[str, Any],
    llm: Any,
    token_budget: int,
    *,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    domain_mapping: dict[str, list] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compose pages for one leaf domain (and optional diagrams when llm is set)."""
    domain_name = leaf.get("name", "unknown")
    module_names = leaf.get("modules", [])

    if graph_store is not None:
        from wiki.content_context_builder import ContentContextBuilder

        try:
            ccb = ContentContextBuilder(graph_store, wiki_store=wiki_store)
            context = await ccb.build_context(
                domain_name=domain_name,
                module_names=list(module_names),
                module_index=module_index,
                entity_roles=entity_roles,  # type: ignore[arg-type]
                domain_mapping=domain_mapping or {},
                depth=2,
                parent_domain=str(leaf.get("parent") or "root"),
            )
            covered_entity_uids = [e.uid for e in context.biz_entities] + [
                str(d["uid"]) for d in context.data_models if d.get("uid")
            ]
            overview_composer = DomainOverviewComposer(llm=llm)
            composer = TopicPageComposer(llm, token_budget=token_budget)
            pages = await composer.compose_leaf_domain_from_context(
                context, overview_composer=overview_composer
            )
            if not pages:
                return [], []
            if llm and pages:
                diag_gen = SemanticDiagramGenerator(llm)
                page_data = _build_page_data_for_semantic_diagrams(
                    domain_name, module_names, module_index
                )
                try:
                    digest = diag_gen.build_entity_digest(page_data)
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
                                    "type": d.diagram_type.value
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
            for page_dict in pages:
                page_dict["covered_entity_uids"] = covered_entity_uids
            return pages, [p.get("path", "") for p in pages]
        except Exception:
            log.warning(
                "ccb_compose_failed_fallback_to_legacy",
                domain=domain_name,
                exc_info=True,
            )

    biz_entities = []
    data_models = []
    for mod_name in module_names:
        for mod_dict in module_index.get(mod_name, []):
            uid = mod_dict.get("uid", f"Module::{mod_name}:0")
            role = entity_roles.get(uid, "supporting")
            props = mod_dict.get("properties", {})

            if str(role) in ("has_business_logic", "entry_point"):
                biz_entities.append({
                    "uid": uid,
                    "name": mod_name,
                    "repository": mod_dict.get("_repo", ""),
                    "file_path": str(props.get("file", "") or props.get("file_path", "") or props.get("path", "")),
                    "summary": str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                    "methods": [str(m) for m in (props.get("methods", []) or [])[:10]],
                    "calls": [str(c) for c in (props.get("calls", []) or [])[:15]],
                    "loc": int(props.get("loc", 0) or props.get("line_count", 0) or 0),
                })
            elif str(role) == "data_model":
                data_models.append({
                    "uid": uid,
                    "name": mod_name,
                    "type": "DTO",
                    "fields": [str(f) for f in (props.get("fields", []) or [])[:8]],
                })

    budget_calc = TokenBudgetCalculator()
    domain_modules = [
        md for m in module_names for md in module_index.get(m, [])
    ]
    snippets = select_key_snippets(
        domain_modules,
        entity_roles,
        budget_tokens=budget_calc.budget_for_snippets(len(domain_modules)),
    )
    snippet_section = ""
    if snippets:
        lines = [s.format_for_prompt() for s in snippets]
        snippet_section = "\n## Key Code Interfaces\n" + "\n".join(lines) + "\n"

    if len(data_models) > 20:
        log.info("data_models_truncated", domain=domain_name, total=len(data_models), kept=20)

    covered_entity_uids = [e["uid"] for e in biz_entities] + [d["uid"] for d in data_models[:20]]

    domain_input = {
        "name": domain_name,
        "parent": leaf.get("parent", "root"),
        "biz_entities": biz_entities,
        "data_models": data_models[:20],
        "sibling_summaries": [],
        "snippet_section": snippet_section,
    }

    scorer = DomainComplexityScorer()
    metrics = scorer.score(domain_input)
    reasoning_level = select_reasoning_level(TaskType.COMPOSE, metrics.complexity)
    composer = TopicPageComposer(
        llm,
        token_budget=token_budget,
        reasoning_level=reasoning_level,
        complexity_scorer=scorer,
    )

    try:
        pages = await composer.compose_leaf_domain(domain_input)
        if llm and pages:
            diag_gen = SemanticDiagramGenerator(llm)
            page_data = _build_page_data_for_semantic_diagrams(
                domain_name, module_names, module_index
            )
            try:
                digest = diag_gen.build_entity_digest(page_data)
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
                                "type": d.diagram_type.value
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
        for page_dict in pages:
            page_dict["covered_entity_uids"] = covered_entity_uids
        return pages, [p.get("path", "") for p in pages]
    except Exception:
        log.warning("compose_pages_domain_failed", domain=domain_name, exc_info=True)
        return [], []


async def plan_topic_structure_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Plan topic-based wiki structure using LLM."""
    llm = (config or {}).get("configurable", {}).get("llm")
    if not llm:
        log.info("plan_topic_structure_skip", reason="no_llm")
        return {"topic_structure": None}

    domain_mapping = state.get("domain_mapping", {})
    if not domain_mapping:
        return {"topic_structure": None}

    modules = state.get("modules", {})
    entity_roles = state.get("entity_roles", {})

    module_metadata: dict[tuple[str, str], dict[str, Any]] = {}
    importance_tiers: dict[str, str] = {}

    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            props = mod_dict.get("properties", {})
            name = props.get("name", "")
            uid = mod_dict.get("uid", "")
            if not name:
                continue
            module_metadata[(repo_name, name)] = {
                "summary": props.get("business_summary", "") or props.get("docstring", ""),
                "methods": props.get("methods", []),
                "calls": props.get("calls", []),
            }
            role = str(entity_roles.get(uid, "supporting"))
            if role == "framework_noise":
                importance_tiers[name] = "skeleton"
            elif role in ("has_business_logic", "entry_point"):
                importance_tiers[name] = "core"
            else:
                importance_tiers[name] = "standard"

    planner = TopicBasedStructurePlanner(llm)
    topic_pages = await planner.plan(
        domain_mapping, module_metadata, importance_tiers
    )

    topic_dicts = [
        {
            "title": tp.title,
            "description": tp.description,
            "covered_modules": tp.covered_modules,
            "sub_topics": [
                {
                    "title": st.title,
                    "description": st.description,
                    "covered_modules": st.covered_modules,
                }
                for st in tp.sub_topics
            ],
        }
        for tp in topic_pages
    ]

    log.info("topic_structure_planned", topic_count=len(topic_dicts))
    return {"topic_structure": topic_dicts}


def _topic_to_domain_dict(
    topic: dict[str, Any],
    module_index: dict[str, list[dict]],
) -> dict[str, Any]:
    """Convert a TopicPage dict into the domain dict format expected by
    _compose_single_leaf_domain."""
    covered = topic.get("covered_modules", [])
    module_names = [name for _repo, name in covered]
    return {
        "name": topic["title"],
        "modules": module_names,
        "children": [],
    }


async def _compose_from_topic_structure(
    topic_structure: list[dict[str, Any]],
    module_index: dict[str, list[dict]],
    entity_roles: dict[str, Any],
    llm: Any,
    *,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    domain_mapping: dict[str, list] | None = None,
) -> dict[str, Any]:
    """Compose pages from TopicBasedStructurePlanner output."""
    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")
    sem = asyncio.Semaphore(_COMPOSE_CONCURRENCY)

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    async def _compose_topic(topic: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        async with sem:
            domain_dict = _topic_to_domain_dict(topic, module_index)
            return await _compose_single_leaf_domain(
                domain_dict,
                module_index,
                entity_roles,
                llm,
                budget,
                graph_store=graph_store,
                wiki_store=wiki_store,
                domain_mapping=domain_mapping,
            )

    all_topics = list(topic_structure)
    for t in topic_structure:
        for sub in t.get("sub_topics", []):
            all_topics.append(sub)

    results = await asyncio.gather(
        *[_compose_topic(t) for t in all_topics],
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, BaseException):
            log.warning("compose_topic_failed", exc_info=item)
            continue
        pages, uids = item
        all_pages.extend(pages)
        generated_uids.extend(uids)

    log.info("compose_from_topics_done", total_pages=len(all_pages))
    return {"pages": all_pages, "generated_topic_pages": generated_uids}


async def compose_leaf_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 3: generate topic pages for each leaf domain."""
    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    wiki_store = configurable.get("wiki_store")
    domain_mapping = state.get("domain_mapping") or {}
    domain_tree = state.get("domain_tree") or []
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    module_index: dict[str, list[dict]] = {}
    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                mod_dict["_repo"] = repo_name
                module_index.setdefault(name, []).append(mod_dict)

    topic_structure = state.get("topic_structure")
    if topic_structure:
        return await _compose_from_topic_structure(
            topic_structure,
            module_index,
            entity_roles,
            llm,
            graph_store=graph_store,
            wiki_store=wiki_store,
            domain_mapping=domain_mapping,
        )

    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    leaf_domains = _collect_leaf_domains(domain_tree)

    sem = asyncio.Semaphore(_COMPOSE_CONCURRENCY)

    async def _bounded(leaf: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        async with sem:
            return await _compose_single_leaf_domain(
                leaf,
                module_index,
                entity_roles,
                llm,
                budget,
                graph_store=graph_store,
                wiki_store=wiki_store,
                domain_mapping=domain_mapping,
            )

    results = await asyncio.gather(
        *[_bounded(leaf) for leaf in leaf_domains],
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, BaseException):
            log.warning("compose_pages_domain_failed", exc_info=item)
            continue
        pages, uids = item
        all_pages.extend(pages)
        generated_uids.extend(uids)

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
            dmatch = _find_domain_in_tree(state.get("domain_tree", []) or [], domain_name)
            if dmatch is not None:
                modules = dmatch.get("modules", [])
                domain_context = (
                    f"Domain: {domain_name}, Modules: {', '.join(str(m) for m in modules[:10])}"
                )

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
                # Try targeted heal first
                from wiki.targeted_healer import TargetedHealer

                healer = TargetedHealer()
                targeted_result = await healer.heal(
                    page,
                    hint,
                    llm,
                    domain_context,
                    content_char_limit=content_char_limit,
                    max_tokens=heal_budget,
                )
                if targeted_result:
                    healed_page = {**page_dict, "content": targeted_result.content}
                    healed_pages.append(healed_page)
                    log.info("targeted_heal_success", page=page_path)
                else:
                    heal_scorer = DomainComplexityScorer()
                    dmods = (
                        list(dmatch.get("modules", []))
                        if isinstance(dmatch, dict)
                        else []
                    )
                    heal_domain = {
                        "name": domain_name,
                        "biz_entities": [
                            {"name": str(m), "methods": [], "calls": []}
                            for m in dmods[:80]
                        ],
                        "data_models": [],
                    }
                    heal_metrics = heal_scorer.score(heal_domain)
                    heal_level = select_reasoning_level(TaskType.HEAL, heal_metrics.complexity)
                    fallback_prompt = heal_prompt
                    if heal_level == ReasoningLevel.GUIDED:
                        fallback_prompt = GuidedPromptEnhancer().enhance_heal_prompt(heal_prompt)
                    new_content = await llm.generate(
                        fallback_prompt,
                        system=SYSTEM_WIKI_HEAL,
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

    flat_domains = _flatten_all_domains(domain_tree if isinstance(domain_tree, list) else [])
    leaf_summaries = state.get("leaf_summaries", {}) or {}

    domain_overviews: dict[str, str] = {}
    for d in flat_domains:
        name = str(d.get("name", "") or "")
        if not name:
            continue
        ls = leaf_summaries.get(name, {})
        if isinstance(ls, dict) and ls.get("summary_text"):
            domain_overviews[name] = ls["summary_text"]
        else:
            domain_overviews[name] = _summarize_domain_for_system_overview(name, pages)

    thin_domain_lines = []
    for domain in flat_domains:
        name = domain.get("name", "") or ""
        ls = leaf_summaries.get(name, {})
        if isinstance(ls, dict) and ls.get("summary_text"):
            summary = ls["summary_text"]
        else:
            domain_pages = [p for p in pages if p.get("domain") == name]
            summary = domain_pages[0].get("content", "")[:200] if domain_pages else ""
        thin_domain_lines.append(f"- **{name}**: {summary}")

    if not thin_domain_lines:
        return {}

    cfg = (config or {}).get("configurable") or {}
    nested_cfg = state.get("config") or {}
    language = cfg.get("language") or nested_cfg.get("language") or "en"
    business_id = str(state.get("business_id") or "default")

    modules_dict_raw = state.get("modules") or {}
    repositories: list[str]
    if isinstance(modules_dict_raw, dict) and modules_dict_raw:
        repositories = sorted(str(k) for k in modules_dict_raw.keys())
    else:
        repositories = list(str(r) for r in (state.get("repositories") or []) if r)
    stats_by_repo = (
        _stats_by_repo_from_pipeline_modules(modules_dict_raw)
        if isinstance(modules_dict_raw, dict)
        else {}
    )
    entry_points_by_repo = (
        _entry_points_by_repo_from_modules(modules_dict_raw)
        if isinstance(modules_dict_raw, dict)
        else {}
    )
    domain_tree_nodes = (
        _domain_tree_dict_to_nodes(domain_tree)
        if isinstance(domain_tree, list)
        else []
    )

    overview_domain_count = len(flat_domains)
    overview_complexity = (
        DomainComplexity.LOW
        if overview_domain_count <= 5
        else DomainComplexity.MEDIUM
        if overview_domain_count <= 12
        else DomainComplexity.HIGH
    )
    overview_reasoning_level = select_reasoning_level(
        TaskType.OVERVIEW,
        overview_complexity,
    )
    overview_budget = TokenBudgetResolver().budget("topic_page_generate")
    overview_system_prompt = (
        "你是一位技术文档作者。输出带 Mermaid 的 Markdown。"
        if str(language) == "zh"
        else "You are a technical wiki author. Output Markdown with Mermaid."
    )

    if overview_reasoning_level == ReasoningLevel.MULTI_STEP:
        log.info(
            "overview_multi_step_reasoning",
            domain_count=overview_domain_count,
            complexity=overview_complexity.value,
        )
        domains_summary = "\n".join(thin_domain_lines)
        reasoner = MultiStepReasoner()
        overview_markdown = await reasoner.plan_and_overview(
            domains_summary,
            llm,
            system=overview_system_prompt,
            max_tokens=overview_budget,
        )
        overview_multi = {
            "title": "System Overview",
            "content": overview_markdown,
            "path": "wiki/_system_overview",
            "page_type": PageType.SYSTEM_OVERVIEW.value,
            "domain": "_system",
        }
        return {"pages": [overview_multi], "system_overview_uid": "wiki/_system_overview"}

    try:
        composer = SystemOverviewComposer(llm)
        wiki_page = await composer.compose(
            business_id=business_id,
            repositories=repositories or [],
            domain_tree=domain_tree_nodes,
            entry_points_by_repo=entry_points_by_repo,
            domain_overviews=domain_overviews,
            stats_by_repo=stats_by_repo,
            language=str(language),
        )
        overview_dict = wiki_page.to_dict()
        overview_dict["path"] = "wiki/_system_overview"
        overview_dict["page_type"] = PageType.SYSTEM_OVERVIEW.value
        overview_dict.setdefault("domain", "_system")
        return {"pages": [overview_dict], "system_overview_uid": "wiki/_system_overview"}
    except Exception:
        log.warning("system_overview_composer_pipeline_failed_falling_back", exc_info=True)
        sys_prompt = (
            "Generate a system overview wiki page summarizing the entire codebase.\n\n"
            f"Domains:\n" + "\n".join(thin_domain_lines) + "\n\n"
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
            "page_type": PageType.SYSTEM_OVERVIEW.value,
            "domain": "_system",
        }
        return {"pages": [overview_page], "system_overview_uid": "wiki/_system_overview"}


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
