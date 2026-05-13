"""Agent-driven domain documentation composition node."""
import asyncio
import os
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.domain_doc_agent import DomainDocAgent, _build_baseline
from wiki.nodes.utils import _collect_leaf_domains

log = get_logger(__name__)

DOMAIN_AGENT_CONCURRENCY = int(os.environ.get("DOMAIN_AGENT_CONCURRENCY", "3"))
DOMAIN_AGENT_TIMEOUT_SEC = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "600"))


def _module_dict_by_name(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Maps module ``name`` (graph property) to module dict — same ambiguity rule as classify/decompose."""
    lookup: dict[str, dict[str, Any]] = {}
    modules = state.get("modules") or {}
    if not isinstance(modules, dict):
        return lookup
    for repo, mod_list in modules.items():
        if not isinstance(mod_list, list):
            continue
        for mod_dict in mod_list:
            if not isinstance(mod_dict, dict):
                continue
            props = mod_dict.get("properties") or {}
            name = props.get("name", "")
            if name:
                lookup[str(name)] = {**mod_dict, "_pipeline_repo_id": repo}
    return lookup


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
    repo_paths: dict[str, str] = configurable.get("repo_paths", {})

    domain_tree = state.get("domain_tree") or []
    module_summaries = state.get("module_summaries", {})
    module_tree = state.get("module_tree", {})
    leaf_domains = _collect_leaf_domains(domain_tree)

    # Incremental filtering: only process affected domains
    is_incremental = state.get("is_incremental", False)
    affected = set(state.get("affected_domains") or [])

    if is_incremental and affected:
        original_count = len(leaf_domains)
        leaf_domains = [
            d for d in leaf_domains
            if d["name"] in affected or d.get("parent") in affected
        ]
        log.info(
            "incremental_domain_filter",
            original=original_count,
            filtered=len(leaf_domains),
            affected_domains=sorted(affected),
        )

    if not leaf_domains:
        log.info("no_leaf_domains_found")
        return {"pages": [], "errors": list(state.get("errors", []))}

    sem = asyncio.Semaphore(DOMAIN_AGENT_CONCURRENCY)
    pages: list[dict[str, Any]] = []
    errors = list(state.get("errors", []))

    async def _run_domain(domain: dict[str, Any]) -> list[dict[str, Any]]:
        async with sem:
            domain_start = asyncio.get_running_loop().time()
            domain_slug = domain["name"]
            domain_display = domain.get("display_name", domain_slug)
            try:
                agent = DomainDocAgent(
                    domain_name=domain_slug,
                    domain_display_name=domain_display,
                    llm=llm,
                    graph_store=graph_store,
                    repo_path=next(iter(repo_paths.values()), None) if repo_paths else None,
                    repo_paths=repo_paths,
                )
                result = await asyncio.wait_for(
                    agent.generate_with_iterations(
                        module_names=domain.get("modules", []),
                        baseline_context=_build_baseline(
                            domain, module_summaries, module_tree=module_tree
                        ),
                    ),
                    timeout=DOMAIN_AGENT_TIMEOUT_SEC,
                )
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

    tasks = [_run_domain(d) for d in leaf_domains]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            errors.append({"domain": leaf_domains[i]["name"], "error": str(result)})
            ph = _make_error_placeholder(leaf_domains[i], result)
            _attach_domain_sources([ph], leaf_domains[i], state)
            pages.append(ph)
        elif isinstance(result, list):
            _attach_domain_sources(result, leaf_domains[i], state)
            for page in result:
                err = page.pop("_error", None)
                if err:
                    errors.append({"domain": page.get("title", ""), "error": err})
                pages.append(page)

    log.info(
        "domain_agents_complete",
        total_domains=len(leaf_domains),
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
