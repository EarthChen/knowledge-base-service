"""Pipeline node: classify architecture layers for all modules."""
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger

log = get_logger(__name__)


async def classify_architecture_layers_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    configurable = (config or {}).get("configurable", {}) or {}
    graph_store = configurable.get("graph_store")
    llm = configurable.get("llm")
    budget_resolver = configurable.get("budget_resolver")

    if graph_store is None:
        log.info("classify_arch_layers_skip_no_store")
        return {"architecture_layers": {}}

    from core.config import AppWikiFlags
    from wiki.architecture_classifier import ArchitectureLayerClassifier

    wiki_flags = configurable.get("wiki_flags") or AppWikiFlags()
    classifier = ArchitectureLayerClassifier(wiki_flags, graph_store, llm, budget_resolver)

    all_modules = state.get("modules") or {}

    # Track all entries including repo for compound key mapping
    module_entries: list[tuple[str, str, str]] = []  # (repo, name, path)
    unique_by_name: dict[str, str] = {}  # name → first path (deduplicate for batch)

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
            module_entries.append((repo, name, path))
            if name not in unique_by_name:
                unique_by_name[name] = path

    try:
        batch_results = await classifier.classify_modules_batch(list(unique_by_name.items()))
    except Exception:
        log.warning("classify_arch_layers_batch_failed", exc_info=True)
        batch_results = {}

    # Map back to compound keys (same name in different repos both get their entry)
    results: dict[str, dict[str, Any]] = {}
    for repo, name, _ in module_entries:
        layer_result = batch_results.get(name)
        if layer_result is not None:
            compound_key = f"{repo}|{name}"
            results[compound_key] = {"layer": layer_result.layer, "confidence": layer_result.confidence}

    log.info("classify_arch_layers_done", total=len(results))
    return {"architecture_layers": results}
