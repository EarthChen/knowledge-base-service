"""Pipeline node: classify architecture layers for all modules."""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.pipeline_concurrency import PipelineConcurrency

log = get_logger(__name__)


async def classify_architecture_layers_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Run ArchitectureLayerClassifier on all modules.

    Reads 'modules' from state, classifies each module, returns
    architecture_layers: dict mapping module_name → {"layer": str, "confidence": float}
    """
    configurable = (config or {}).get("configurable", {}) or {}
    graph_store = configurable.get("graph_store")
    llm = configurable.get("llm")

    if graph_store is None:
        log.info("classify_arch_layers_skip_no_store")
        return {"architecture_layers": {}}

    from core.config import AppWikiFlags
    from wiki.architecture_classifier import ArchitectureLayerClassifier

    # Get wiki flags from config or use defaults
    wiki_flags = configurable.get("wiki_flags") or AppWikiFlags()
    classifier = ArchitectureLayerClassifier(wiki_flags, graph_store, llm)

    all_modules = state.get("modules") or {}
    results: dict[str, dict[str, Any]] = {}
    sem = PipelineConcurrency.semaphore("arch_classify")

    async def _classify_one(name: str, path: str) -> tuple[str, dict[str, Any]] | None:
        async with sem:
            try:
                result = await classifier.classify_module(name, path)
                return (name, {"layer": result.layer, "confidence": result.confidence})
            except Exception:
                log.warning("classify_arch_layer_failed", module=name, exc_info=True)
                return None

    tasks: list = []
    for repo, mod_list in all_modules.items():
        if not isinstance(mod_list, list):
            continue
        for mod_dict in mod_list:
            if not isinstance(mod_dict, dict):
                continue
            props = mod_dict.get("properties") or {}
            name = props.get("name", "")
            path = props.get("path", "") or props.get("file", "") or ""
            if not name:
                continue
            tasks.append(_classify_one(name, path))

    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(result, tuple):
            results[result[0]] = result[1]
        elif isinstance(result, BaseException):
            log.warning("classify_arch_layer_gather_error", error=str(result))

    log.info("classify_arch_layers_done", total=len(results))
    return {"architecture_layers": results}
