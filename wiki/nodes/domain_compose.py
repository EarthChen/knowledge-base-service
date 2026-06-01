"""Agent-driven domain documentation composition node."""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.config import ContentLanguage, get_settings
from core.log import get_logger
from wiki.domain_doc_agent import DomainDocAgent, _build_baseline, domain_has_subdomains
from wiki.flow_baseline import extract_flow_baseline, format_flow_baseline_for_prompt
from wiki.llm_rate_limiter import acquire_llm_quota
from wiki.models import ImportanceTier
from wiki.nodes.compose import _maybe_pipeline_progress
from wiki.nodes.tier_utils import resolve_tier, tier_for_module_count
from wiki.nodes.utils import _collect_container_domains, _collect_leaf_domains, _collect_module_names_in_subtree
from wiki.path_conventions import domain_overview_path
from wiki.pipeline_concurrency import PipelineConcurrency
from wiki.source_ref_validator import repair_broken_mermaid_blocks, sanitize_wiki_content

log = get_logger(__name__)

_MERMAID_FENCE_RE = re.compile(r"```\s*mermaid\b", re.IGNORECASE)


def _resolve_content_language_for_compose(
    state: dict[str, Any],
    config: dict[str, Any] | RunnableConfig | None,
) -> ContentLanguage:
    cl = state.get("content_language")
    if isinstance(cl, ContentLanguage):
        return cl
    lang = state.get("language")
    if lang:
        return ContentLanguage.from_any(str(lang))
    wlang = state.get("wiki_content_language")
    if wlang:
        return ContentLanguage.from_any(str(wlang))
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    if not isinstance(configurable, dict):
        configurable = {}
    cfg_lang = configurable.get("wiki_content_language")
    if cfg_lang:
        return ContentLanguage.from_any(str(cfg_lang))
    return ContentLanguage.from_any(get_settings().wiki.wiki_content_language)


def _domain_call_edges(
    module_names: list[str],
    all_edges: list[dict[str, Any]] | None,
) -> list[tuple[str, str]]:
    """Extract bare module call pairs relevant to a domain from pipeline edge dicts."""
    if not all_edges:
        return []
    module_set = {str(m) for m in module_names}
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in all_edges:
        if not isinstance(edge, dict):
            continue
        caller = str(edge.get("source") or "")
        callee = str(edge.get("target") or "")
        if caller not in module_set and callee not in module_set:
            continue
        pair = (caller, callee)
        if pair not in seen:
            pairs.append(pair)
            seen.add(pair)
    return pairs


def _inject_dependency_diagram(
    content: str,
    module_names: list[str],
    call_edges: list[tuple[str, str]] | None = None,
    *,
    language: ContentLanguage | None = None,
) -> str:
    """Append a placeholder Architecture Mermaid diagram when agent output lacks one."""
    if _MERMAID_FENCE_RE.search(content or ""):
        return content
    if len(module_names) < 2:
        return content

    nodes = module_names[:10]
    lines = ["graph TD"]
    for idx, mod in enumerate(nodes):
        safe = str(mod).replace('"', "'")
        lines.append(f'    M{idx}["{safe}"]')

    name_to_idx = {name: idx for idx, name in enumerate(nodes)}

    if call_edges:
        added: set[tuple[int, int]] = set()
        for caller, callee in call_edges:
            if caller in name_to_idx and callee in name_to_idx and caller != callee:
                i, j = name_to_idx[caller], name_to_idx[callee]
                edge = (i, j)
                if edge not in added:
                    lines.append(f"    M{i} --> M{j}")
                    added.add(edge)
        if not added:
            for idx in range(len(nodes) - 1):
                lines.append(f"    M{idx} --> M{idx + 1}")
    else:
        for idx in range(len(nodes) - 1):
            lines.append(f"    M{idx} --> M{idx + 1}")

    diagram = "\n".join(lines)
    heading = "## 架构" if (language and language.is_chinese) else "## Architecture"
    return f"{content.rstrip()}\n\n{heading}\n\n```mermaid\n{diagram}\n```\n"


def _max_iterations_for_domain(domain: dict[str, Any], state: dict[str, Any]) -> int:
    """Resolve tier-appropriate max_iterations for DomainDocAgent."""
    wiki_cfg = get_settings().wiki
    module_count = len(domain.get("modules") or [])
    domain_path = domain_overview_path(str(domain.get("name") or ""))
    config_tiers = (state.get("config") or {}).get("importance_tiers") or {}
    if domain_path not in config_tiers:
        effective_tiers = {**config_tiers, domain_path: tier_for_module_count(module_count)}
    else:
        effective_tiers = config_tiers
    tier = resolve_tier(domain_path, effective_tiers)
    if tier == ImportanceTier.CORE:
        return wiki_cfg.domain_agent_max_iterations_core
    if tier == ImportanceTier.STANDARD:
        return wiki_cfg.domain_agent_max_iterations_standard
    return wiki_cfg.domain_agent_max_iterations_skeleton


def _scale_explore_params(module_count: int, wiki_cfg: Any) -> tuple[int, int]:
    """Scale explore rounds and tool calls for large domains."""
    base_rounds = wiki_cfg.domain_agent_explore_max_rounds
    base_calls = wiki_cfg.domain_agent_explore_max_tool_calls
    threshold_m = getattr(wiki_cfg, "explore_scale_threshold_medium", 20)
    threshold_l = getattr(wiki_cfg, "explore_scale_threshold_large", 40)

    if module_count > threshold_l:
        return min(base_rounds + 4, 16), min(base_calls + 15, 50)
    if module_count > threshold_m:
        return min(base_rounds + 2, 12), min(base_calls + 10, 40)
    return base_rounds, base_calls


def _explore_limits_for_domain(domain: dict[str, Any], state: dict[str, Any]) -> tuple[int | None, int | None]:
    """Resolve tier-appropriate explore limits for DomainDocAgent."""
    module_count = len(domain.get("modules") or [])
    domain_path = domain_overview_path(str(domain.get("name") or ""))
    config_tiers = (state.get("config") or {}).get("importance_tiers") or {}
    if domain_path not in config_tiers:
        effective_tiers = {**config_tiers, domain_path: tier_for_module_count(module_count)}
    else:
        effective_tiers = config_tiers
    tier = resolve_tier(domain_path, effective_tiers)
    if tier == ImportanceTier.SKELETON:
        return 2, 8
    if tier == ImportanceTier.STANDARD:
        return 5, 20
    return None, None


def _build_layer_summary(
    module_names: list[str],
    architecture_layers: dict[str, dict[str, Any]],
    *,
    module_repo_pairs: list[tuple[str, str]] | None = None,
    language: ContentLanguage | None = None,
) -> str:
    """Format architecture layer info for a domain's modules.

    Returns a string like:
    Architecture layers in this domain:
    - api (2 modules): UserController, AuthHandler
    - service (3 modules): UserService, AuthService, NotificationManager
    """
    from collections import defaultdict

    layer_modules: dict[str, list[str]] = defaultdict(list)
    pairs = module_repo_pairs or []
    for idx, name in enumerate(module_names):
        info = None
        if idx < len(pairs):
            repo, pair_name = pairs[idx]
            if pair_name == name:
                info = architecture_layers.get(f"{repo}|{name}")
        if info is None:
            info = architecture_layers.get(name)
        if info:
            layer_modules[info.get("layer", "unknown")].append(name)

    if not layer_modules:
        return ""

    prefix = "本域架构层分布：" if (language and language.is_chinese) else "Architecture layers in this domain:"
    lines = [prefix]
    for layer in ("api", "service", "data", "infrastructure"):
        modules = layer_modules.get(layer, [])
        if modules:
            lines.append(f"- {layer} ({len(modules)} modules): {', '.join(modules[:5])}")
    return "\n".join(lines)


def _module_dict_by_name(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Maps module compound key ``repo|name`` to module dict; includes bare-name fallback."""
    by_compound: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    modules = state.get("modules") or {}
    if not isinstance(modules, dict):
        return by_compound
    for repo, mod_list in modules.items():
        if not isinstance(mod_list, list):
            continue
        for mod_dict in mod_list:
            if not isinstance(mod_dict, dict):
                continue
            props = mod_dict.get("properties") or {}
            name = props.get("name", "")
            if name:
                mod_with_repo = {**mod_dict, "_pipeline_repo_id": repo}
                by_compound[f"{repo}|{name}"] = mod_with_repo
                by_name.setdefault(str(name), mod_with_repo)
    return {**by_name, **by_compound}


def _overview_module_sources(
    state: dict[str, Any],
    module_names: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build pipeline ``source_locations`` dicts plus Module ``uid`` list for ``covered_entity_uids``."""
    lookup = _module_dict_by_name(state)
    locations: list[dict[str, Any]] = []
    uids: list[str] = []
    for raw_name in module_names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        mod_dict = lookup.get(name)
        if not mod_dict:
            continue
        uid = str(mod_dict.get("uid") or "").strip()
        props = mod_dict.get("properties") or {}
        repo_fallback = mod_dict.get("_pipeline_repo_id", "")
        repository = (
            str(props.get("repository") or "").strip() or str(repo_fallback or "").strip()
        )
        file_path = str(props.get("path") or props.get("file") or ".").strip() or "."
        fqn = str(props.get("fqn") or name)
        locations.append({
            "file_path": file_path,
            "start_line": int(props.get("start_line") or 0),
            "end_line": int(props.get("end_line") or props.get("start_line") or 0),
            "fqn": fqn,
            "repository": repository,
        })
        if uid:
            uids.append(uid)
    return locations, uids


def _domain_module_pairs(
    domain: dict[str, Any],
    domain_mapping: dict[str, list[tuple[str, str]]],
    module_lookup: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve repo|name pairs for a domain's modules."""
    slug_pairs = domain_mapping.get(str(domain.get("name") or ""), [])
    name_to_repos: dict[str, list[str]] = {}
    for repo, name in slug_pairs:
        name_to_repos.setdefault(str(name), []).append(str(repo))

    module_repo_pairs: list[tuple[str, str]] = []
    valid_pairs: list[str] = []
    for mod_name in domain.get("modules", []):
        name = str(mod_name)
        repos = name_to_repos.get(name, [])
        if len(repos) == 1:
            repo = repos[0]
        else:
            info = module_lookup.get(name)
            repo = str(info.get("_pipeline_repo_id", "") if info else (repos[0] if repos else ""))
        module_repo_pairs.append((repo, name))
        valid_pairs.append(f"{repo}|{name}" if repo else name)
    return module_repo_pairs, valid_pairs


def _attach_domain_sources(pages_out: list[dict[str, Any]], domain: dict[str, Any], state: dict[str, Any]) -> None:
    """Link domain pages (overview + topic) to constituent Module nodes."""
    locations, covered = _overview_module_sources(state, list(domain.get("modules") or []))
    if not locations and not covered:
        return
    for page in pages_out:
        if page.get("page_type") not in ("domain_overview", "topic"):
            continue
        page["source_locations"] = locations
        if covered:
            existing = page.get("covered_entity_uids") or []
            page["covered_entity_uids"] = list(set(existing) | set(covered))


async def compose_domain_agents_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Agent-driven domain documentation generation."""
    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    budget_resolver = configurable.get("budget_resolver")
    repo_paths: dict[str, str] = configurable.get("repo_paths", {})
    module_lookup = _module_dict_by_name(state)
    fallback_repo_path = next(iter(repo_paths.values()), None) if repo_paths else None

    domain_tree = state.get("domain_tree") or []
    module_summaries = state.get("module_summaries", {})
    module_tree = state.get("module_tree", [])
    leaf_domains = _collect_leaf_domains(domain_tree)
    container_domains = _collect_container_domains(domain_tree)
    compose_domains = container_domains + leaf_domains

    # Incremental filtering: only process affected domains
    is_incremental = state.get("is_incremental", False)
    affected = set(state.get("affected_domains") or [])

    if is_incremental and affected:
        original_count = len(compose_domains)
        compose_domains = [
            d for d in compose_domains
            if d["name"] in affected or d.get("parent") in affected
        ]
        log.info(
            "incremental_domain_filter",
            original=original_count,
            filtered=len(compose_domains),
            affected_domains=sorted(affected),
        )

    if not compose_domains:
        log.info("no_leaf_domains_found")
        return {"pages": [], "errors": list(state.get("errors", []))}

    total_domains = len(compose_domains)
    await _maybe_pipeline_progress(
        configurable,
        {
            "phase": "compose_domain_agents",
            "progress_pct": 0.30,
            "detail": f"域文档生成 0/{total_domains}",
        },
    )

    sem = PipelineConcurrency.semaphore("domain_agent")
    pages: list[dict[str, Any]] = []
    errors = list(state.get("errors", []))
    arch_layers = state.get("architecture_layers") or {}
    domain_mapping = state.get("domain_mapping") or {}

    def _domain_repo_path(domain: dict[str, Any]) -> str | None:
        if not repo_paths:
            return None
        repos: list[str] = []
        for mod_name in domain.get("modules", []):
            info = module_lookup.get(str(mod_name))
            if info:
                repos.append(info.get("_pipeline_repo_id", ""))
        if repos:
            primary = Counter(repos).most_common(1)[0][0]
            return repo_paths.get(primary, fallback_repo_path)
        return fallback_repo_path

    content_language = _resolve_content_language_for_compose(state, config)

    async def _run_domain(domain: dict[str, Any]) -> list[dict[str, Any]]:
        async with sem:
            domain_start = asyncio.get_running_loop().time()
            domain_slug = domain["name"]
            domain_display = domain.get("display_name", domain_slug)
            try:
                module_names = list(domain.get("modules") or [])
                if domain_has_subdomains(domain) and not module_names:
                    module_names = _collect_module_names_in_subtree(domain)
                explore_rounds, explore_calls = _explore_limits_for_domain(domain, state)
                wiki_cfg = get_settings().wiki
                scaled_rounds, scaled_calls = _scale_explore_params(len(module_names), wiki_cfg)
                if explore_rounds is None:
                    explore_rounds = scaled_rounds
                if explore_calls is None:
                    explore_calls = scaled_calls
                subdomains = list(domain.get("children") or domain.get("subdomains") or [])
                if not domain_has_subdomains(domain):
                    subdomains = []
                agent = DomainDocAgent(
                    domain_name=domain_slug,
                    domain_display_name=domain_display,
                    llm=llm,
                    graph_store=graph_store,
                    repo_path=_domain_repo_path(domain),
                    repo_paths=repo_paths,
                    max_iterations=_max_iterations_for_domain(domain, state),
                    explore_max_rounds=explore_rounds,
                    explore_max_tool_calls=explore_calls,
                    budget_resolver=budget_resolver,
                    content_language=content_language.display_label,
                    term_glossary=state.get("term_glossary", {}),
                    subdomains=subdomains,
                    module_call_edges=state.get("module_call_edges"),
                )
                module_repo_pairs, valid_pairs = _domain_module_pairs(
                    domain, domain_mapping, module_lookup,
                )
                layer_summary = _build_layer_summary(
                    module_names,
                    arch_layers,
                    module_repo_pairs=module_repo_pairs,
                    language=content_language,
                )
                baseline = _build_baseline(domain, module_summaries, module_tree=module_tree)
                if layer_summary:
                    baseline = baseline + "\n\n" + layer_summary
                if graph_store:
                    try:
                        flow_baseline = await extract_flow_baseline(
                            graph_store,
                            domain_slug,
                            module_names,
                            valid_pairs=valid_pairs,
                        )
                        flow_text = format_flow_baseline_for_prompt(flow_baseline)
                        if flow_text:
                            baseline = baseline + "\n\n" + flow_text
                    except Exception:
                        log.warning("domain_flow_baseline_failed", domain=domain_slug, exc_info=True)
                project_docs = configurable.get("project_docs")
                if project_docs:
                    from wiki.project_doc_provider import format_for_page_agent

                    baseline = format_for_page_agent(project_docs) + "\n\n" + baseline

                await acquire_llm_quota(config, estimated_tokens=4000)
                outer_timeout = get_settings().wiki.domain_agent_timeout_sec
                result = await asyncio.wait_for(
                    agent.generate_with_iterations(
                        module_names=module_names,
                        baseline_context=baseline,
                        valid_pairs=valid_pairs,
                    ),
                    timeout=outer_timeout,
                )
                domain_edges = _domain_call_edges(
                    module_names,
                    state.get("module_call_edges"),
                )
                for page in result:
                    if page.get("metadata", {}).get("generation_mode") != "agent_error":
                        page["content"] = _inject_dependency_diagram(
                            page.get("content", ""),
                            module_names,
                            call_edges=domain_edges,
                            language=content_language,
                        )
                for page in result:
                    page.setdefault("content_language", content_language.value)

                elapsed = asyncio.get_running_loop().time() - domain_start
                log.info(
                    "domain_agent_done",
                    domain=domain_slug,
                    pages=len(result),
                    elapsed_sec=round(elapsed, 1),
                    iterations=len(agent.iteration_history),
                )
                return result
            except Exception as e:
                elapsed = asyncio.get_running_loop().time() - domain_start
                log.error(
                    "domain_agent_failed",
                    domain=domain_slug,
                    error=str(e),
                    elapsed_sec=round(elapsed, 1),
                )
                return [_make_error_placeholder(domain, e)]

    async def _run_domain_indexed(
        index: int, domain: dict[str, Any],
    ) -> tuple[int, list[dict[str, Any]] | BaseException]:
        try:
            return index, await _run_domain(domain)
        except BaseException as exc:
            return index, exc

    wrapped = [_run_domain_indexed(i, d) for i, d in enumerate(compose_domains)]
    results: list[list[dict[str, Any]] | BaseException | None] = [None] * total_domains
    completed = 0
    for item in asyncio.as_completed(wrapped):
        index, result = await item
        results[index] = result
        completed += 1
        domain_name = compose_domains[index]["name"]
        await _maybe_pipeline_progress(
            configurable,
            {
                "phase": "compose_domain_agents",
                "progress_pct": 0.30 + (completed / total_domains) * 0.24,
                "detail": f"域文档 {completed}/{total_domains}: {domain_name}",
            },
        )

    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            errors.append({"domain": compose_domains[i]["name"], "error": str(result)})
            ph = _make_error_placeholder(compose_domains[i], result)
            _attach_domain_sources([ph], compose_domains[i], state)
            pages.append(ph)
        elif isinstance(result, list):
            _attach_domain_sources(result, compose_domains[i], state)
            for page in result:
                err = page.pop("_error", None)
                if err:
                    errors.append({"domain": page.get("title", ""), "error": err})
                pages.append(page)

    # Sanitize domain pages (Mermaid validation + repair)
    known_entities: list[dict[str, str | int]] = []
    for repo_mods in state.get("modules", {}).values():
        for m in repo_mods:
            props = m.get("properties", {}) or {}
            name = props.get("name", "")
            if name:
                known_entities.append({
                    "name": name,
                    "repository": props.get("repository", ""),
                    "file_path": props.get("path", props.get("file_path", "")),
                    "start_line": int(props.get("start_line") or 0),
                })
    for page in pages:
        raw = page.get("content", "")
        page["content"] = sanitize_wiki_content(raw, known_entities)
        metadata = page.setdefault("metadata", {})
        if llm is not None and not metadata.get("mermaid_fixed"):
            page["content"] = await repair_broken_mermaid_blocks(page["content"], llm)
            metadata["mermaid_fixed"] = True

    log.info(
        "domain_agents_complete",
        total_domains=len(compose_domains),
        total_pages=len(pages),
        error_count=len(errors) - len(state.get("errors", [])),
    )
    return {"pages": pages, "errors": errors}


def _make_error_placeholder(domain: dict[str, Any], error: BaseException) -> dict[str, Any]:
    """Failed domain produces a placeholder page (not skipped)."""
    from wiki.path_conventions import domain_overview_path

    modules_list = "\n".join(f"- {m}" for m in domain.get("modules", []))
    slug = domain["name"]
    display = domain.get("display_name", slug)
    return {
        "page_type": "domain_overview",
        "title": display,
        "path": domain_overview_path(slug),
        "_error": str(error)[:200],
        "content": (
            f"# {display}\n\n"
            f"> ⚠️ 文档生成失败: {str(error)[:200]}\n\n"
            f"## 域内模块\n\n{modules_list}"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {
            "node_count": 0,
            "edge_count": 0,
            "generation_mode": "agent_error",
        },
    }
