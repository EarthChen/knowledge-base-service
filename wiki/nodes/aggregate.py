"""Parent pages, leaf summaries, and overview synthesis nodes."""

import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.config import get_settings
from core.log import get_logger
from wiki.dependency_graph import DomainNode
from wiki.domain_complexity import DomainComplexity
from wiki.context_gap import cleanup_context_gaps
from wiki.json_robust import parse_json_robust_sync
from wiki.models import LeafSummary, PageType
from wiki.nodes.utils import (
    _collect_leaf_domains,
    _collect_module_names_in_subtree,
    _collect_parent_domains_by_level,
    _extract_key_entities,
    _extract_summary_from_content,
    _find_page_for_leaf_domain,
    _flatten_all_domains,
    _module_dicts_for_names,
    _normalize_pages_map,
    has_parent_domains,
    select_key_snippets,
)
from wiki.prompts import system_wiki_parent_overview
from wiki.reasoning import MultiStepReasoner, ReasoningLevel, TaskType, select_reasoning_level
from wiki.system_overview_composer import SystemOverviewComposer
from wiki.token_budget import TokenBudgetCalculator, TokenBudgetResolver

log = get_logger(__name__)


def _compute_cross_domain_call_stats(
    parent_domain: dict[str, Any],
    module_call_edges: list[dict[str, Any]] | None,
) -> str:
    """Compute cross-sub-domain call statistics for parent overview prompts."""
    if not module_call_edges:
        return "No cross-domain call data available."

    children = parent_domain.get("children", [])
    if not children:
        return "No sub-domains to analyze."

    module_to_subdomain: dict[str, str] = {}
    for child in children:
        child_name = child.get("display_name") or child.get("name", "")
        for mod in child.get("modules", []):
            module_to_subdomain[mod] = child_name

    cross_calls: Counter[tuple[str, str]] = Counter()
    for edge in module_call_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        src_domain = module_to_subdomain.get(src, "")
        tgt_domain = module_to_subdomain.get(tgt, "")
        if src_domain and tgt_domain and src_domain != tgt_domain:
            weight = edge.get("weight", 1)
            cross_calls[(src_domain, tgt_domain)] += weight

    if not cross_calls:
        return "No cross-sub-domain calls detected."

    lines = []
    for (src, tgt), count in cross_calls.most_common(20):
        lines.append(f"- {src} → {tgt}: {count} calls")
    return "\n".join(lines)


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
    content_language = get_settings().wiki.wiki_content_language
    system_prompt = system_wiki_parent_overview(content_language)

    parent_levels = _collect_parent_domains_by_level(domain_tree)
    total_parents = sum(len(lvl) for lvl in parent_levels)
    log.info(
        "compose_parent_pages_start",
        levels=len(parent_levels),
        total_parents=total_parents,
    )
    all_parent_pages: list[dict[str, Any]] = []
    parent_idx = 0

    for level_idx, level_parents in enumerate(parent_levels):
        for parent_domain in level_parents:
            parent_name = str(parent_domain.get("name", "") or "").strip()
            if not parent_name:
                continue
            parent_idx += 1
            child_count = len(parent_domain.get("children", []) or [])
            log.info(
                "compose_parent_page_generating",
                domain=parent_name,
                level=level_idx,
                progress=f"{parent_idx}/{total_parents}",
                child_count=child_count,
            )
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

            cross_domain_stats = _compute_cross_domain_call_stats(
                parent_domain, state.get("module_call_edges")
            )

            prompt = (
                f'Create a domain overview page for "{parent_name}" that synthesizes '
                "its sub-domains.\n\n"
                "## Sub-domain Summaries\n"
                f"{child_summaries_text}\n\n"
                "## Key Code Interfaces\n"
                f"{snippet_text}\n\n"
                "## Cross-Domain Call Statistics\n"
                f"{cross_domain_stats}\n\n"
                'Return ONLY valid JSON (no markdown fences) with keys: "title", '
                '"content", "executive_summary", "page_type".\n'
                "Requirements for content:\n"
                f"- Use {content_language} for all text including the title\n"
                "- Explain how sub-domains relate and describe data flow between them\n"
                "- Include at least one Mermaid sequenceDiagram or flowchart showing interactions\n"
                "- Reference key interfaces naturally in the explanation\n"
                "- Do NOT just list module names and summaries; explain the business story\n\n"
                "executive_summary should be 150-300 chars capturing the domain's core purpose."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            parsed: dict[str, Any] | None = None
            if hasattr(llm, "complete_json"):
                try:
                    result = await llm.complete_json(messages, {}, max_tokens=gen_budget)
                except (ValueError, Exception):
                    log.warning(
                        "compose_parent_pages_complete_json_failed",
                        domain=parent_name,
                        progress=f"{parent_idx}/{total_parents}",
                        exc_info=True,
                    )
                    continue
                if isinstance(result, dict):
                    parsed = result
                else:
                    log.warning("compose_parent_pages_bad_json", domain=parent_name)
                    continue
            else:
                try:
                    response = await llm.generate(
                        prompt,
                        system=system_prompt,
                        max_tokens=gen_budget,
                    )
                    raw = response if isinstance(response, str) else str(response)
                    parsed = parse_json_robust_sync(raw)
                except Exception:
                    log.warning(
                        "compose_parent_pages_failed",
                        domain=parent_name,
                        progress=f"{parent_idx}/{total_parents}",
                        exc_info=True,
                    )
                    continue
            try:
                if not isinstance(parsed, dict):
                    log.warning("compose_parent_pages_bad_json", domain=parent_name)
                    continue
                title = parsed.get("title") or parent_domain.get("display_name") or parent_name
                content = cleanup_context_gaps(parsed.get("content", ""))
                exec_summary = parsed.get("executive_summary", "")
                page_type_val = parsed.get("page_type") or "domain_overview"
                page_type = str(page_type_val)
                from wiki.path_conventions import domain_overview_path

                page_dict: dict[str, Any] = {
                    "path": domain_overview_path(parent_name),
                    "title": title,
                    "content": content,
                    "page_type": page_type,
                    "domain": parent_name,
                    "business_domain": parent_name,
                    "metadata": {"executive_summary": exec_summary},
                }
                all_parent_pages.append(page_dict)
                log.info(
                    "compose_parent_page_done",
                    domain=parent_name,
                    progress=f"{parent_idx}/{total_parents}",
                    content_len=len(content),
                )
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

    log.info(
        "compose_parent_pages_complete",
        total_parents=total_parents,
        pages_generated=len(all_parent_pages),
    )
    return {"pages": all_parent_pages, "leaf_summaries": leaf_summaries}


_BUSINESS_SUMMARY_SECTION = re.compile(
    r"^##\s*业务概述\s*$",
    re.MULTILINE,
)


def _summarize_domain_for_system_overview(domain_name: str, pages: list[dict[str, Any]]) -> str:
    """Use ## 业务概述 body when present, else first ~300 chars of the best matching page."""
    domain_pages = [
        p
        for p in pages
        if p.get("domain") == domain_name or p.get("business_domain") == domain_name
    ]
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
            domain_pages = [
                p
                for p in pages
                if p.get("domain") == name or p.get("business_domain") == name
            ]
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
        overview_markdown = cleanup_context_gaps(overview_markdown)
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
            "Domains:\n" + "\n".join(thin_domain_lines) + "\n\n"
            "Output:\n"
            "1. ## 系统概览 (high-level description of the system)\n"
            "2. ## 架构图 (Mermaid diagram showing domain relationships)\n"
            "3. ## 域列表 (with links to each domain)\n"
        )
        overview_content = await llm.generate(
            sys_prompt,
            system="You are a technical wiki author. Output Markdown with Mermaid.",
        )
        overview_content = cleanup_context_gaps(overview_content)
        overview_page = {
            "title": "System Overview",
            "content": overview_content,
            "path": "wiki/_system_overview",
            "page_type": PageType.SYSTEM_OVERVIEW.value,
            "domain": "_system",
        }
        return {"pages": [overview_page], "system_overview_uid": "wiki/_system_overview"}
