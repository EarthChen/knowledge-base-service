"""Pipeline node: compose business flow documentation via FlowDocAgent."""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.flow_baseline import FlowBaseline, extract_flow_baseline, format_flow_baseline_for_prompt
from wiki.pipeline_concurrency import PipelineConcurrency

log = get_logger(__name__)


def _is_flow_enabled() -> bool:
    try:
        from core.config import get_settings

        return get_settings().wiki.flow_compose_enabled
    except Exception:
        return True


def _extract_leaf_domains(domain_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract leaf domains (domains with modules) from domain tree."""
    leaves: list[dict[str, Any]] = []
    for domain in domain_tree or []:
        modules = domain.get("modules") or []
        children = domain.get("children") or []
        if modules:
            leaves.append(domain)
        if children:
            leaves.extend(_extract_leaf_domains(children))
    return leaves


async def _run_flow_agent(
    domain_name: str,
    baseline: FlowBaseline,
    llm: Any,
    graph_store: Any,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run FlowDocAgent for a single domain."""
    from wiki.agents.flow_doc_agent import FlowDocAgent

    baseline_text = format_flow_baseline_for_prompt(baseline)
    flow_name = f"{domain_name} Business Flows"

    agent = FlowDocAgent(
        flow_name=flow_name,
        domain_name=domain_name,
        llm=llm,
        graph_store=graph_store,
    )

    module_names = [ep.module_name for ep in baseline.entry_points]
    seen: set[str] = set()
    unique_modules: list[str] = []
    for m in module_names:
        if m not in seen:
            seen.add(m)
            unique_modules.append(m)

    try:
        result = await agent.generate(
            module_names=unique_modules,
            baseline_context=baseline_text,
        )
        if isinstance(result, list):
            return result
        if isinstance(result, str):
            return [
                {
                    "path": f"{domain_name}/business-flows.md",
                    "page_type": "business_flow",
                    "content": result,
                    "domain": domain_name,
                    "title": flow_name,
                }
            ]
        return []
    except Exception:
        log.warning("flow_agent_failed", domain=domain_name, exc_info=True)
        return []


async def _persist_flow_structure(
    graph_store: Any,
    domain_name: str,
    flow_pages: list[dict[str, Any]],
    baseline: FlowBaseline,
    repository: str = "",
) -> None:
    """Persist BusinessFlow and FlowStep nodes using UNWIND batch Cypher."""
    if not graph_store or not baseline.entry_points:
        return

    try:
        flow_data = []
        for ep in baseline.entry_points:
            flow_data.append(
                {
                    "uid": f"bf:{domain_name}:{ep.function_name}",
                    "name": f"{ep.module_name}.{ep.function_name}",
                    "entry_type": ep.entry_type,
                    "domain": domain_name,
                    "repository": repository,
                }
            )

        if flow_data:
            create_cy = """
            UNWIND $flows AS f
            MERGE (bf:BusinessFlow {uid: f.uid})
            SET bf.name = f.name, bf.entry_type = f.entry_type, bf.domain = f.domain,
                bf.repository = f.repository
            """
            await graph_store.execute_query(create_cy, {"flows": flow_data})

            link_cy = """
            UNWIND $flows AS f
            MATCH (wp:WikiPage {business_domain: f.domain, page_type: 'domain_overview'})
            MATCH (bf:BusinessFlow {uid: f.uid})
            MERGE (wp)-[:CONTAINS_FLOW]->(bf)
            """
            await graph_store.execute_query(link_cy, {"flows": flow_data})

    except Exception:
        log.warning("flow_persist_failed", domain=domain_name, exc_info=True)


async def compose_flow_agents_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Compose business flow pages for domains with entry points."""
    if not _is_flow_enabled():
        return {"flow_pages": []}

    configurable = (config or {}).get("configurable", {})
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")

    if not llm:
        return {"flow_pages": []}

    domain_tree = state.get("domain_tree") or []
    leaf_domains = _extract_leaf_domains(domain_tree)

    if not leaf_domains:
        return {"flow_pages": []}

    repos = state.get("repositories") or []
    repository = str(configurable.get("repository") or (repos[0] if repos else "")).strip()

    sem = PipelineConcurrency.semaphore("flow_compose")
    all_flow_pages: list[dict[str, Any]] = []

    async def _process_domain(domain: dict[str, Any]) -> list[dict[str, Any]]:
        async with sem:
            domain_name = domain.get("name", "")
            modules = [str(m) for m in domain.get("modules", [])]
            if not modules or not graph_store:
                return []

            baseline = await extract_flow_baseline(graph_store, domain_name, modules)
            if not baseline.entry_points:
                log.debug("flow_skip_no_entry_points", domain=domain_name)
                return []

            pages = await _run_flow_agent(domain_name, baseline, llm, graph_store, state)
            await _persist_flow_structure(graph_store, domain_name, pages, baseline, repository)
            return pages

    results = await asyncio.gather(*[_process_domain(d) for d in leaf_domains], return_exceptions=True)
    for r in results:
        if isinstance(r, list):
            all_flow_pages.extend(r)
        elif isinstance(r, Exception):
            log.warning("flow_compose_exception", exc_info=r)

    log.info("flow_compose_done", total_flow_pages=len(all_flow_pages))
    return {"flow_pages": all_flow_pages}
