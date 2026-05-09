"""Bridges the LangGraph wiki pipeline into the production WikiService path.

Converts between WikiService's GraphNode-based data model and the
plain-dict format expected by the LangGraph ``WikiPipelineState``.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger
from store.schema import GraphNode
from wiki.dependency_graph import DomainNode
from wiki.models import PageType, WikiPage
from wiki.pipeline_graph import build_wiki_pipeline

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


def _dicts_to_domain_tree(raw_tree: list[dict[str, Any]] | None) -> list[DomainNode] | None:
    """Convert pipeline output dicts back to DomainNode objects for downstream persistence."""
    if not raw_tree:
        return None
    result: list[DomainNode] = []
    for d in raw_tree:
        result.append(DomainNode(
            name=d.get("name", ""),
            description=d.get("description", ""),
            modules=list(d.get("modules", [])),
            children=_dicts_to_domain_tree(d.get("children", [])) or [],
        ))
    return result


def _extract_domain_mapping(
    state: dict[str, Any],
    modules_dict: dict[str, list[dict[str, Any]]],
) -> dict[str, list[tuple[str, str]]]:
    """Reconstruct (repo, module_name) pairs from pipeline domain_mapping.

    The pipeline's ``classify_domains_node`` stores ``domain_mapping`` as
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
    for p in state.get("pages", []):
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
        except Exception:
            log.warning("pipeline_page_conversion_failed", page_path=p.get("path", "?"))
    return pages


async def run_langgraph_pipeline(
    business_id: str,
    repositories: list[str],
    all_modules: dict[str, list[GraphNode]],
    llm: Any,
    *,
    existing_domain_tree: list | None = None,
    is_incremental: bool = False,
    affected_domains: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    model_strategy: Any | None = None,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
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
                existing_tree_dicts.append({
                    "name": node.name,
                    "description": getattr(node, "description", ""),
                    "modules": list(getattr(node, "modules", [])),
                    "children": [],
                })
            elif isinstance(node, dict):
                existing_tree_dicts.append(node)

    language = (config_overrides or {}).get("language", "zh")

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
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
        "entity_roles": {},
        "role_stats": {},
        "is_incremental": is_incremental,
        "reorg_type": "",
        "affected_domains": affected_domains or [],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
        "module_tree": [],
        "canonical_keys": {},
        "domain_cache": {},
        "language": language,
    }

    pipeline = build_wiki_pipeline()

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

    log.info(
        "langgraph_pipeline_config_debug",
        has_llm=llm is not None,
        llm_type=type(llm).__name__ if llm else "NoneType",
        configurable_keys=list(configurable.keys()),
    )

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": configurable},
    )

    domain_mapping = _extract_domain_mapping(result, modules_dict)
    domain_tree = _dicts_to_domain_tree(result.get("domain_tree"))
    pages = _pages_from_state(result)
    resolved_links = result.get("resolved_links", {})
    entity_roles = result.get("entity_roles", {})
    errors = result.get("errors", [])

    log.info(
        "langgraph_pipeline_done",
        business_id=business_id,
        pages=len(pages),
        domains=len(domain_mapping),
        errors=len(errors),
    )

    return PipelineResult(
        domain_mapping=domain_mapping,
        domain_tree=domain_tree,
        pages=pages,
        resolved_links=resolved_links,
        entity_roles=entity_roles,
        errors=errors,
    )
