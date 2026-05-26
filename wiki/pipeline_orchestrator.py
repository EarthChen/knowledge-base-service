"""Bridges the LangGraph wiki pipeline into the production WikiService path.

Converts between WikiService's GraphNode-based data model and the
plain-dict format expected by the LangGraph ``WikiPipelineState``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.config import ContentLanguage
from core.log import get_logger
from store.schema import GraphNode
from wiki.dependency_graph import DomainNode
from wiki.models import PageType, WikiPage
from wiki.pipeline_graph import build_wiki_pipeline, get_checkpointer

log = get_logger(__name__)


@dataclass
class PipelineResult:
    """Output of a LangGraph pipeline run, ready for WikiService consumption."""

    domain_mapping: dict[str, list[tuple[str, str]]]
    domain_tree: list[DomainNode] | None
    pages: list[WikiPage]
    resolved_links: dict[str, list[dict[str, str]]]
    entity_roles: dict[str, str]
    errors: list[str] = field(default_factory=list)
    domain_display_names: dict[str, str] = field(default_factory=dict)
    reassembly_actions: list[dict[str, Any]] = field(default_factory=list)


def _graph_nodes_to_dicts(
    all_modules: dict[str, list[GraphNode]],
) -> dict[str, list[dict[str, Any]]]:
    """Convert GraphNode objects to plain dicts for LangGraph state."""
    result: dict[str, list[dict[str, Any]]] = {}
    for repo, nodes in all_modules.items():
        result[repo] = [
            {
                "uid": node.uid,
                "label": node.label.value if hasattr(node.label, "value") else str(node.label),
                "properties": dict(node.properties) if hasattr(node.properties, "items") else node.properties,
            }
            for node in nodes
        ]
    return result


def domain_tree_to_mapping(
    tree: list[dict[str, Any]],
    all_modules: dict[str, list[GraphNode]],
) -> dict[str, list[tuple[str, str]]]:
    """Rebuild slug → (repo, module) mapping from a persisted domain tree snapshot."""
    name_to_repo: dict[str, str] = {}
    for repo, nodes in all_modules.items():
        for node in nodes:
            name = str(node.properties.get("name", "") or "")
            if name and name not in name_to_repo:
                name_to_repo[name] = repo

    mapping: dict[str, list[tuple[str, str]]] = {}

    def visit(node: dict[str, Any]) -> None:
        slug = str(node.get("name") or "")
        children = node.get("children") or []
        mod_names = node.get("modules") or []
        if children:
            for child in children:
                visit(child)
        if mod_names and slug:
            for mod_name in mod_names:
                mod_str = str(mod_name)
                if "|" in mod_str:
                    repo_part, name_part = mod_str.split("|", 1)
                    if repo_part and name_part:
                        mapping.setdefault(slug, []).append((repo_part, name_part))
                else:
                    repo = name_to_repo.get(mod_str)
                    if repo:
                        mapping.setdefault(slug, []).append((repo, mod_str))

    for root in tree:
        if isinstance(root, dict):
            visit(root)
    return mapping


def _dicts_to_domain_tree(raw_tree: list[dict[str, Any]] | None) -> list[DomainNode] | None:
    """Convert pipeline output dicts back to DomainNode objects for downstream persistence."""
    if not raw_tree:
        return None
    result: list[DomainNode] = []
    for d in raw_tree:
        slug_val = d.get("name", "")
        result.append(
            DomainNode(
                name=slug_val,
                slug=slug_val,
                display_name=d.get("display_name", ""),
                description=d.get("description", ""),
                modules=list(d.get("modules", [])),
                children=_dicts_to_domain_tree(d.get("children", [])) or [],
            )
        )
    return result


def _extract_domain_mapping(
    state: dict[str, Any],
    modules_dict: dict[str, list[dict[str, Any]]],
) -> dict[str, list[tuple[str, str]]]:
    """Reconstruct (repo, module_name) pairs from pipeline domain_mapping.

    The pipeline's ``graph_domain_decompose`` node stores ``domain_mapping`` as
    ``dict[domain, list[tuple[repo, module_name]]]`` via
    ``CrossRepoBusinessDomainPlanner.classify``, which already returns the
    expected format.  If the pipeline returns empty mapping, fall back to the
    domain_tree modules to build a best-effort flat mapping.
    """
    raw = state.get("domain_mapping", {})
    if raw:
        return raw

    tree = state.get("domain_tree") or []
    repo_lookup: dict[str, str] = {}
    for repo, mods in modules_dict.items():
        for m in mods:
            name = m.get("properties", {}).get("name", "")
            if name:
                repo_lookup[name] = repo

    mapping: dict[str, list[tuple[str, str]]] = {}
    for node in tree:
        domain = node.get("name", "unknown")
        pairs: list[tuple[str, str]] = []
        for mod_name in node.get("modules", []):
            repo = repo_lookup.get(mod_name, "")
            if repo:
                pairs.append((repo, mod_name))
        if pairs:
            mapping[domain] = pairs
    return mapping


def _normalize_pipeline_page_dict(p: dict[str, Any]) -> dict[str, Any]:
    """Fill fields required by ``WikiPage.from_dict`` for minimal graph-pipeline dicts."""
    d = dict(p)
    d.setdefault("page_type", PageType.MODULE_OVERVIEW.value)
    d.setdefault("diagrams", [])
    d.setdefault("source_locations", [])
    d.setdefault("method_locations", [])
    if not isinstance(d.get("metadata"), dict):
        d["metadata"] = {
            "node_count": 0,
            "edge_count": 0,
            "generation_mode": "structure",
        }
    return d


def _pages_from_state(state: dict[str, Any]) -> list[WikiPage]:
    pages: list[WikiPage] = []
    errors = state.setdefault("errors", [])
    if not isinstance(errors, list):
        errors = []
        state["errors"] = errors
    for p in state.get("pages", []):
        page_path = p.get("path", "?")
        try:
            wp = WikiPage.from_dict(_normalize_pipeline_page_dict(p))
            covered = p.get("covered_entity_uids")
            if covered:
                wp.covered_entity_uids = covered  # type: ignore[attr-defined]
            biz_dom = p.get("business_domain")
            if biz_dom:
                setattr(wp, "business_domain", str(biz_dom))
            ck = p.get("canonical_key")
            if ck:
                setattr(wp, "canonical_key", str(ck))
            pages.append(wp)
        except Exception as exc:
            log.warning("pipeline_page_conversion_failed", page_path=page_path, exc_info=True)
            errors.append(f"page_conversion_failed:{page_path}:{type(exc).__name__}")
    return pages


async def _load_summaries_from_checkpoint(business_id: str) -> dict[str, dict[str, Any]]:
    """Load ``module_summaries`` from the latest LangGraph checkpoint for this business."""
    summaries: dict[str, dict[str, Any]] = {}
    try:
        async with get_checkpointer(business_id) as checkpointer:
            config = {"configurable": {"thread_id": f"biz-{business_id}"}}
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            if checkpoint_tuple is None:
                return {}
            checkpoint = checkpoint_tuple.checkpoint or {}
            channel_values = checkpoint.get("channel_values") or {}
            raw = channel_values.get("module_summaries") or channel_values.get("existing_summaries") or {}
            if isinstance(raw, dict):
                summaries = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        log.warning("load_summaries_from_checkpoint_failed", business_id=business_id, exc_info=True)
    return summaries


def _summaries_from_graph_modules(
    all_modules: dict[str, list[GraphNode]],
) -> dict[str, dict[str, Any]]:
    """Build minimal summary dicts from Module ``business_summary`` graph properties."""
    summaries: dict[str, dict[str, Any]] = {}
    name_to_repos: dict[str, set[str]] = {}
    for repo, mods in all_modules.items():
        for mod in mods:
            name = str(mod.properties.get("name", "") or "")
            if name:
                name_to_repos.setdefault(name, set()).add(repo)

    for repo, mods in all_modules.items():
        for mod in mods:
            name = str(mod.properties.get("name", "") or "")
            if not name:
                continue
            bs = mod.properties.get("business_summary")
            if not isinstance(bs, str) or not bs.strip():
                continue
            entry = {"summary_text": bs.strip()}
            compound = f"{repo}|{name}"
            summaries[compound] = entry
            if len(name_to_repos.get(name, set())) == 1:
                summaries[name] = entry
    return summaries


async def load_existing_module_summaries(
    business_id: str,
    all_modules: dict[str, list[GraphNode]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load persisted module summaries for incremental reuse (checkpoint, then graph fallback)."""
    summaries = await _load_summaries_from_checkpoint(business_id)
    if summaries:
        log.info(
            "existing_summaries_loaded",
            business_id=business_id,
            source="checkpoint",
            count=len(summaries),
        )
        return summaries
    if all_modules:
        summaries = _summaries_from_graph_modules(all_modules)
        if summaries:
            log.info(
                "existing_summaries_loaded",
                business_id=business_id,
                source="graph",
                count=len(summaries),
            )
    return summaries


def wiki_store_rows_to_pages(
    rows: list[dict[str, Any]],
    *,
    business_id: str,
) -> list[WikiPage]:
    """Convert ``get_wiki_pages_for_business`` rows into ``WikiPage`` objects."""
    pages: list[WikiPage] = []
    for row in rows:
        try:
            page_dict = {
                "path": str(row.get("path") or ""),
                "title": str(row.get("title") or ""),
                "page_type": row.get("page_type") or PageType.MODULE_OVERVIEW.value,
                "content": str(row.get("content") or ""),
                "repository": str(row.get("repository") or business_id),
                "metadata": {
                    "node_count": 0,
                    "edge_count": 0,
                    "generation_mode": "cached",
                },
            }
            pages.append(WikiPage.from_dict(_normalize_pipeline_page_dict(page_dict)))
        except Exception:
            log.debug("cached_wiki_page_conversion_failed", path=row.get("path"), exc_info=True)
    return pages


async def load_cached_pipeline_result(
    business_id: str,
    all_modules: dict[str, list[GraphNode]],
    *,
    wiki_store: Any,
    existing_domain_tree: list | None = None,
    existing_domain_mapping: dict[str, list[tuple[str, str]]] | None = None,
) -> PipelineResult:
    """Build a ``PipelineResult`` from persisted wiki pages and domain tree (pipeline skip path)."""
    raw_pages = await wiki_store.get_wiki_pages_for_business(business_id)
    pages = wiki_store_rows_to_pages(raw_pages or [], business_id=business_id)

    tree_dicts: list[dict[str, Any]] | None = None
    if existing_domain_tree:
        tree_dicts = []
        for node in existing_domain_tree:
            if hasattr(node, "name"):
                tree_dicts.append(
                    {
                        "name": node.name,
                        "description": getattr(node, "description", ""),
                        "modules": list(getattr(node, "modules", [])),
                        "children": [],
                    }
                )
            elif isinstance(node, dict):
                tree_dicts.append(node)

    domain_mapping = existing_domain_mapping or {}
    if not domain_mapping and tree_dicts:
        domain_mapping = domain_tree_to_mapping(tree_dicts, all_modules)

    return PipelineResult(
        domain_mapping=domain_mapping,
        domain_tree=_dicts_to_domain_tree(tree_dicts),
        pages=pages,
        resolved_links={},
        entity_roles={},
        errors=[],
        domain_display_names={},
    )


def _build_initial_state_language(config_overrides: dict[str, Any] | None) -> ContentLanguage:
    language_raw = (config_overrides or {}).get("language", "zh-CN")
    return ContentLanguage.from_any(language_raw)


async def run_langgraph_pipeline(
    business_id: str,
    repositories: list[str],
    all_modules: dict[str, list[GraphNode]],
    llm: Any,
    *,
    existing_domain_tree: list | None = None,
    existing_domain_mapping: dict[str, list[tuple[str, str]]] | None = None,
    existing_summaries: dict[str, dict[str, Any]] | None = None,
    affected_modules: list[str] | None = None,
    pinned_modules: dict[str, str] | None = None,
    is_incremental: bool = False,
    affected_domains: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    model_strategy: Any | None = None,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    budget_resolver: Any | None = None,
    llm_rate_limiter: Any | None = None,
) -> PipelineResult:
    """Execute the LangGraph wiki pipeline and return production-ready results.

    This is the single integration point between the LangGraph graph
    (``build_wiki_pipeline``) and ``WikiService.generate_business_wiki``.
    """
    modules_dict = _graph_nodes_to_dicts(all_modules)

    existing_tree_dicts: list[dict[str, Any]] | None = None
    if existing_domain_tree:
        existing_tree_dicts = []
        for node in existing_domain_tree:
            if hasattr(node, "name"):
                existing_tree_dicts.append(
                    {
                        "name": node.name,
                        "description": getattr(node, "description", ""),
                        "modules": list(getattr(node, "modules", [])),
                        "children": [],
                    }
                )
            elif isinstance(node, dict):
                existing_tree_dicts.append(node)

    content_language = _build_initial_state_language(config_overrides)

    resolved_existing_mapping = existing_domain_mapping
    if resolved_existing_mapping is None and existing_tree_dicts:
        resolved_existing_mapping = domain_tree_to_mapping(existing_tree_dicts, all_modules)

    initial_state: dict[str, Any] = {
        "business_id": business_id,
        "repositories": repositories,
        "config": config_overrides or {},
        "modules": modules_dict,
        "domain_mapping": {},
        "domain_tree": existing_tree_dicts,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "errors": [],
        "entity_roles": {},
        "role_stats": {},
        "is_incremental": is_incremental,
        "reorg_type": "",
        "affected_domains": affected_domains or [],
        "existing_domain_mapping": resolved_existing_mapping or {},
        "affected_modules": affected_modules or [],
        "pinned_modules": pinned_modules or {},
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
        "module_tree": [],
        "canonical_keys": {},
        "domain_cache": {},
        "language": content_language.value,
        "content_language": content_language,
    }

    if existing_summaries:
        initial_state["module_summaries"] = existing_summaries
        initial_state["existing_summaries"] = existing_summaries

    log.info(
        "langgraph_pipeline_start",
        business_id=business_id,
        repos=len(repositories),
        modules=sum(len(v) for v in modules_dict.values()),
        is_incremental=is_incremental,
    )

    configurable: dict[str, Any] = {"thread_id": f"biz-{business_id}", "llm": llm}
    if model_strategy is not None:
        configurable["model_strategy"] = model_strategy
    if graph_store is not None:
        configurable["graph_store"] = graph_store
    if wiki_store is not None:
        configurable["wiki_store"] = wiki_store
    if progress_callback is not None:
        configurable["progress_callback"] = progress_callback
    if budget_resolver is not None:
        configurable["budget_resolver"] = budget_resolver
    if llm_rate_limiter is not None:
        configurable["llm_rate_limiter"] = llm_rate_limiter

    try:
        from core.config import get_settings
        from services.git_manager import resolve_repo_clone_root

        _settings = get_settings()
        _repo_paths: dict[str, str] = {}
        for repo in repositories:
            resolved = resolve_repo_clone_root(repo, _settings.git)
            if resolved is not None:
                _repo_paths[repo] = str(resolved)
        if _repo_paths:
            configurable["repo_paths"] = _repo_paths
    except Exception:
        log.warning("repo_paths_resolution_failed", exc_info=True)

    log.info(
        "langgraph_pipeline_config_debug",
        has_llm=llm is not None,
        llm_type=type(llm).__name__ if llm else "NoneType",
        configurable_keys=list(configurable.keys()),
    )

    import time as _time

    pipeline_t0 = _time.monotonic()
    try:
        async with get_checkpointer(business_id) as checkpointer:
            pipeline = build_wiki_pipeline(checkpointer=checkpointer)
            result = await pipeline.ainvoke(
                initial_state,
                config={"configurable": configurable},
            )
    except Exception as exc:
        pipeline_elapsed = _time.monotonic() - pipeline_t0
        log.error(
            "pipeline_invoke_crashed",
            business_id=business_id,
            error=str(exc),
            exc_info=True,
        )
        return PipelineResult(
            domain_mapping={},
            domain_tree=None,
            pages=[],
            resolved_links={},
            entity_roles={},
            errors=[f"pipeline_invoke_failed:{exc}"],
            domain_display_names={},
        )
    pipeline_elapsed = _time.monotonic() - pipeline_t0

    domain_mapping = _extract_domain_mapping(result, modules_dict)
    domain_tree = _dicts_to_domain_tree(result.get("domain_tree"))
    pages = _pages_from_state(result)
    resolved_links = result.get("resolved_links", {})
    entity_roles = result.get("entity_roles", {})
    errors = result.get("errors", [])
    domain_display_names = result.get("domain_display_names", {})
    reassembly_actions = result.get("reassembly_actions", [])

    log.info(
        "langgraph_pipeline_done",
        business_id=business_id,
        pages=len(pages),
        domains=len(domain_mapping),
        errors=len(errors),
        total_elapsed_sec=round(pipeline_elapsed, 1),
        total_elapsed_min=round(pipeline_elapsed / 60, 1),
    )

    return PipelineResult(
        domain_mapping=domain_mapping,
        domain_tree=domain_tree,
        pages=pages,
        resolved_links=resolved_links,
        entity_roles=entity_roles,
        errors=errors,
        domain_display_names=domain_display_names,
        reassembly_actions=reassembly_actions,
    )
