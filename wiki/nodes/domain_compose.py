"""Agent-driven domain documentation composition node."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.domain_doc_agent import DomainDocAgent, _build_baseline
from wiki.nodes.utils import _collect_leaf_domains

log = get_logger(__name__)

DOMAIN_AGENT_CONCURRENCY = int(os.environ.get("DOMAIN_AGENT_CONCURRENCY", "3"))
DOMAIN_AGENT_TIMEOUT_SEC = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "300"))


async def compose_domain_agents_node(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Agent-driven domain documentation generation."""
    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")

    domain_tree = state.get("domain_tree") or []
    module_summaries = state.get("module_summaries", {})
    leaf_domains = _collect_leaf_domains(domain_tree)

    if not leaf_domains:
        log.info("no_leaf_domains_found")
        return {"pages": [], "errors": list(state.get("errors", []))}

    sem = asyncio.Semaphore(DOMAIN_AGENT_CONCURRENCY)
    pages: list[dict[str, Any]] = []
    errors = list(state.get("errors", []))

    async def _run_domain(domain: dict[str, Any]) -> list[dict[str, Any]]:
        async with sem:
            domain_start = asyncio.get_event_loop().time()
            try:
                agent = DomainDocAgent(
                    domain_name=domain["name"],
                    llm=llm,
                    graph_store=graph_store,
                )
                result = await asyncio.wait_for(
                    agent.generate_with_iterations(
                        module_names=domain.get("modules", []),
                        baseline_context=_build_baseline(domain, module_summaries),
                    ),
                    timeout=DOMAIN_AGENT_TIMEOUT_SEC,
                )
                elapsed = asyncio.get_event_loop().time() - domain_start
                log.info(
                    "domain_agent_done",
                    domain=domain["name"],
                    pages=len(result),
                    elapsed_sec=round(elapsed, 1),
                    iterations=len(agent.iteration_history),
                )
                return result
            except Exception as e:
                elapsed = asyncio.get_event_loop().time() - domain_start
                log.error(
                    "domain_agent_failed",
                    domain=domain["name"],
                    error=str(e),
                    elapsed_sec=round(elapsed, 1),
                )
                return [_make_error_placeholder(domain, e)]

    tasks = [_run_domain(d) for d in leaf_domains]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            errors.append({"domain": leaf_domains[i]["name"], "error": str(result)})
            pages.append(_make_error_placeholder(leaf_domains[i], result))
        elif isinstance(result, list):
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
    modules_list = "\n".join(f"- {m}" for m in domain.get("modules", []))
    return {
        "type": "domain_overview",
        "title": domain["name"],
        "content": (
            f"# {domain['name']}\n\n"
            f"> ⚠️ 文档生成失败: {str(error)[:200]}\n\n"
            f"## 域内模块\n\n{modules_list}"
        ),
    }
