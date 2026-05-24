"""LangGraph StateGraph definition for Wiki generation pipeline."""
# NOTE: Do NOT add `from __future__ import annotations` here.
# LangGraph needs real type objects (not strings) to detect RunnableConfig
# parameters and automatically inject config into nodes.

import hashlib
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from core.log import get_logger
from wiki.citation_verifier import verify_citations
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.models import ImportanceTier, WikiPage
from wiki.nodes.classify_architecture import classify_architecture_layers_node
from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node
from wiki.nodes.reassemble_domains import reassemble_domains_node
from wiki.pipeline_nodes import (
    assign_canonical_keys_node,
    classify_entities_node,
    compose_domain_agents_node,
    compose_flow_agents_node,
    merge_flow_pages_node,
    compose_leaf_modules_node,
    compose_parent_pages_node,
    create_links_node,
    detect_reorg_node,
    generate_titles_node,
    generate_tour_node,
    graph_decompose_node,
    heal_pages_node,
    persist_classification_node,
    set_review_status_node,
    summarize_leaves_node,
)
from wiki.pipeline_state import WikiPipelineState
from wiki.quality_evaluator import WikiQualityEvaluator

log = get_logger(__name__)

HEAL_LOOP_MAX_TOTAL_ATTEMPTS = 10

# Node name → (API phase label, baseline progress 0..1 for task status / UI)
_NODE_PHASE_MAP: dict[str, tuple[str, float]] = {
    "classify_entity_roles": ("classify_entities", 0.0),
    "classify_architecture_layers": ("classify_architecture_layers", 0.01),
    "detect_reorg": ("detect_reorg", 0.02),
    "graph_decompose": ("graph_decompose", 0.05),
    "assign_canonical_keys": ("assign_keys", 0.07),
    "generate_titles": ("generate_titles", 0.08),
    "compose_leaf_modules": ("compose_leaf_modules", 0.10),
    "classify_domains": ("classify_domains", 0.18),
    "persist_classification": ("persist_classification", 0.20),
    "set_review_status": ("set_review_status", 0.22),
    "compose_domain_agents": ("compose_domain_agents", 0.30),
    "summarize_leaves": ("summarize_leaves", 0.55),
    "compose_parent_pages": ("compose_parent_pages", 0.60),
    "reassemble_domains": ("reassemble_domains", 0.65),
    "compose_flow_agents": ("compose_flow_agents", 0.67),
    "merge_flow_pages": ("merge_flow_pages", 0.68),
    "quality_gate": ("quality_gate", 0.70),
    "heal_pages": ("heal_pages", 0.80),
    "create_links": ("linking", 0.90),
    "generate_tour": ("generate_tour", 0.92),
    "finalize": ("finalize", 0.95),
}


def _with_progress(
    node_name: str,
    func: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Wrap a graph node to invoke ``configurable[\"progress_callback\"]`` on entry."""
    mapping = _NODE_PHASE_MAP.get(node_name)
    if mapping is None:
        return func
    phase, pct = mapping
    _sig = inspect.signature(func)
    params = [
        p
        for p in _sig.parameters.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    pass_config = len(params) >= 2

    if pass_config:
        async def _wrapper(
            state: WikiPipelineState,
            config: RunnableConfig | None = None,
        ) -> dict[str, Any]:
            import time as _time
            configurable = (config or {}).get("configurable", {}) or {}
            cb = configurable.get("progress_callback")
            if cb:
                try:
                    await cb({
                        "phase": phase,
                        "progress_pct": pct,
                        "detail": f"{phase} 开始",
                    })
                except Exception:
                    log.debug("progress_callback_failed", phase=phase, exc_info=True)
            log.info("pipeline_node_enter", node=node_name, phase=phase)
            t0 = _time.monotonic()
            result = await func(state, config)
            elapsed = _time.monotonic() - t0
            log.info(
                "pipeline_node_exit",
                node=node_name,
                phase=phase,
                elapsed_sec=round(elapsed, 1),
            )
            return result
    else:
        async def _wrapper(state: WikiPipelineState) -> dict[str, Any]:  # type: ignore[misc]
            import time as _time
            log.info("pipeline_node_enter", node=node_name, phase=phase)
            t0 = _time.monotonic()
            result = await func(state)
            elapsed = _time.monotonic() - t0
            log.info(
                "pipeline_node_exit",
                node=node_name,
                phase=phase,
                elapsed_sec=round(elapsed, 1),
            )
            return result
    # Copy __name__/__doc__ for debugging but NOT __annotations__/__wrapped__
    # because functools.wraps would copy string annotations from the original
    # function (which uses `from __future__ import annotations`), making
    # LangGraph unable to detect the RunnableConfig type for config injection.
    _wrapper.__name__ = func.__name__
    _wrapper.__qualname__ = func.__qualname__
    _wrapper.__doc__ = func.__doc__

    return _wrapper

# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def route_by_reorg_type(state: WikiPipelineState) -> str:
    """Route based on detected reorg type."""
    reorg_type = state.get("reorg_type", "first_run")
    if reorg_type == "none":
        return "finalize"
    return "graph_decompose"


def should_heal(state: WikiPipelineState) -> str:
    """Route to heal_pages if quality_gate_node identified pages to heal."""
    if state.get("pages_to_heal"):
        total_heal_attempts = sum(state.get("heal_attempts", {}).values())
        if total_heal_attempts > HEAL_LOOP_MAX_TOTAL_ATTEMPTS:
            log.warning(
                "heal_loop_safety_limit",
                total_attempts=total_heal_attempts,
                limit=HEAL_LOOP_MAX_TOTAL_ATTEMPTS,
            )
            return "create_links"
        return "heal_pages"
    return "create_links"


# ---------------------------------------------------------------------------
# Quality / finalize nodes (graph-local)
# ---------------------------------------------------------------------------

async def quality_gate_node(
    state: WikiPipelineState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Evaluate page quality with configurable L1/L2/L3 layers.

    Configuration (priority high→low):
    1. state["config"]["quality_levels"]
    2. config["configurable"]["quality_levels"]
    3. Default: ["L1", "L2"]

    Uses _structural_check_cache to skip re-evaluation when page content is
    unchanged between heal cycles.
    """
    cfg = state.get("config") or {}
    levels = (
        cfg.get("quality_levels")
        or (config or {}).get("configurable", {}).get("quality_levels")
        or ["L1", "L2"]
    )

    evaluator = WikiQualityEvaluator()
    importance_tiers: dict[str, str] = cfg.get("importance_tiers", {})
    heal_attempts = state.get("heal_attempts", {})

    # Load or initialise structural check cache
    check_cache: dict[str, dict[str, Any]] = dict(state.get("_structural_check_cache", {}))

    quality_scores: dict[str, dict[str, Any]] = {}
    pages_to_heal: list[str] = []

    all_module_names: set[str] = set()
    for repo_mods in state.get("modules", {}).values():
        for mod in repo_mods:
            mod_name = mod.get("properties", {}).get("name", "")
            if mod_name:
                all_module_names.add(mod_name)

    for page_dict in state.get("pages", []):
        try:
            page = WikiPage.from_dict(page_dict)
        except Exception:
            log.warning("quality_gate_page_parse_failed", page_data=str(page_dict)[:100])
            continue

        raw_tier = importance_tiers.get(page.path, "standard")
        try:
            tier = ImportanceTier(str(raw_tier).lower())
        except ValueError:
            tier = ImportanceTier.STANDARD

        if tier == ImportanceTier.SKELETON:
            quality_scores[page.path] = {"l1_structural": 1.0, "overall": 1.0}
            continue

        # Compute content hash for cache lookup
        content_bytes = (page.content or "").encode("utf-8", errors="replace")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        cached = check_cache.get(page.path)

        score_dict: dict[str, Any] = {}

        if cached and cached.get("content_hash") == content_hash:
            # Reuse cached L1 score
            cached_score = cached.get("score", {})
            l1_overall = cached_score.get("l1_structural", 0.0)
            score_dict["l1_structural"] = l1_overall
        else:
            # Evaluate structural check fresh
            l1 = evaluator.structural_check(page)
            score_dict["l1_structural"] = l1.overall

            # Citation verification — detect hallucinated entity references
            citation_result = verify_citations(page.content, all_module_names)
            if citation_result.invalid_count > 0:
                score_dict["citation_invalid_count"] = citation_result.invalid_count
                score_dict["citation_invalid_refs"] = citation_result.invalid_refs[:5]
                penalty = min(0.2, citation_result.invalid_count * 0.05)
                l1_adjusted = max(0.0, l1.overall - penalty)
                score_dict["l1_structural"] = round(l1_adjusted, 4)

            gap_issues = [i for i in l1.issues if i.startswith("context_gaps:")]
            if gap_issues:
                gap_count = int(gap_issues[0].split(":")[1])
                score_dict["context_gap_count"] = gap_count

            # Update cache
            check_cache[page.path] = {"score": dict(score_dict), "content_hash": content_hash}

        if "L2" in levels:
            l2 = evaluator.bench_score(page)
            score_dict["l2_bench"] = l2.overall

        score_dict["l3_llm_judge"] = None
        l1_val = score_dict.get("l1_structural", 0.0)
        was_healed = page.path in heal_attempts and heal_attempts.get(page.path, 0) > 0
        if "L3" in levels and l1_val >= 0.7:
            should_l3 = (tier == ImportanceTier.CORE) or was_healed
            l3_cache_key = check_cache.get(page.path, {}).get("l3_evaluated", False)
            if should_l3 and not l3_cache_key:
                llm = (config or {}).get("configurable", {}).get("llm")
                if llm:
                    harness_eval = WikiPageEvaluator()
                    page_modules = page_dict.get("entity_uids") or [page.title or page.path]
                    l3_result = await harness_eval.evaluate_l3(page.content, page_modules, llm)
                    if l3_result.dimensions:
                        avg_1_5 = sum(l3_result.dimensions.values()) / len(l3_result.dimensions)
                        score_dict["l3_llm_judge"] = round((avg_1_5 - 1.0) / 4.0, 4)
                        score_dict["l3_dimensions"] = l3_result.dimensions
                    if page.path in check_cache:
                        check_cache[page.path]["l3_evaluated"] = True

        _SCORE_KEYS = {"l1_structural", "l2_bench", "l3_llm_judge"}
        numeric_scores = [
            v
            for k, v in score_dict.items()
            if k in _SCORE_KEYS and isinstance(v, (int, float)) and v is not None
        ]
        score_dict["overall"] = (
            round(sum(numeric_scores) / len(numeric_scores), 4) if numeric_scores else 0.0
        )

        quality_scores[page.path] = score_dict

        threshold = 0.7 if tier == ImportanceTier.CORE else 0.5
        max_retries = 2 if tier == ImportanceTier.CORE else 1
        attempts = heal_attempts.get(page.path, 0)

        structural_score = score_dict["l1_structural"]
        if structural_score < threshold and attempts < max_retries:
            pages_to_heal.append(page.path)

    if "L2" in levels and len(pages_to_heal) > 1:
        pages_to_heal.sort(key=lambda p: quality_scores.get(p, {}).get("l2_bench", 0.0))

    total_gaps = sum(
        v.get("context_gap_count", 0) for v in quality_scores.values()
    )
    pages_with_gaps = sum(
        1 for v in quality_scores.values() if v.get("context_gap_count", 0) > 0
    )

    log.info(
        "quality_gate_done",
        total_pages=len(state.get("pages", [])),
        evaluated=len(quality_scores),
        to_heal=len(pages_to_heal),
        levels=levels,
        context_gaps_total=total_gaps,
        pages_with_context_gaps=pages_with_gaps,
    )
    return {
        "quality_scores": quality_scores,
        "pages_to_heal": pages_to_heal,
        "_structural_check_cache": check_cache,
    }


async def finalize_node(state: WikiPipelineState) -> dict[str, Any]:
    timings = state.get("stage_timings", {})
    total_ms = sum(timings.values())
    log.info(
        "pipeline_complete",
        total_pages=len(state.get("pages", [])),
        total_elapsed_ms=total_ms,
        llm_call_count=state.get("llm_call_count", 0),
        error_count=len(state.get("errors", [])),
    )
    return {}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_wiki_pipeline(checkpointer: Any | None | bool = None) -> Any:
    """Build and compile the Wiki generation StateGraph.

    Args:
        checkpointer: Checkpoint backend. Defaults to in-memory
            ``MemorySaver``. Pass ``False`` to disable checkpointing.
            For production persistence, pass ``AsyncSqliteSaver``
            or ``RedisSaver``::

                async with AsyncSqliteSaver.from_conn_string(path) as saver:
                    pipeline = build_wiki_pipeline(checkpointer=saver)
    """
    graph = StateGraph(WikiPipelineState)

    graph.add_node("classify_entity_roles", _with_progress("classify_entity_roles", classify_entities_node))
    graph.add_node(
        "classify_architecture_layers",
        _with_progress("classify_architecture_layers", classify_architecture_layers_node),
    )
    graph.add_node("detect_reorg", _with_progress("detect_reorg", detect_reorg_node))
    graph.add_node("graph_decompose", _with_progress("graph_decompose", graph_decompose_node))
    graph.add_node("assign_canonical_keys", _with_progress("assign_canonical_keys", assign_canonical_keys_node))
    graph.add_node("classify_domains", _with_progress("classify_domains", graph_driven_domain_decompose_node))
    graph.add_node(
        "persist_classification",
        _with_progress("persist_classification", persist_classification_node),
    )
    graph.add_node("generate_titles", _with_progress("generate_titles", generate_titles_node))
    graph.add_node("set_review_status", _with_progress("set_review_status", set_review_status_node))
    graph.add_node("compose_leaf_modules", _with_progress("compose_leaf_modules", compose_leaf_modules_node))

    graph.add_node(
        "compose_domain_agents",
        _with_progress("compose_domain_agents", compose_domain_agents_node),
    )
    graph.add_node("summarize_leaves", _with_progress("summarize_leaves", summarize_leaves_node))
    graph.add_node("compose_parent_pages", _with_progress("compose_parent_pages", compose_parent_pages_node))
    graph.add_edge("compose_domain_agents", "summarize_leaves")
    graph.add_edge("summarize_leaves", "compose_parent_pages")
    graph.add_node(
        "reassemble_domains",
        _with_progress("reassemble_domains", reassemble_domains_node),
    )
    graph.add_edge("compose_parent_pages", "reassemble_domains")
    graph.add_node(
        "compose_flow_agents",
        _with_progress("compose_flow_agents", compose_flow_agents_node),
    )
    graph.add_edge("reassemble_domains", "compose_flow_agents")
    graph.add_node(
        "merge_flow_pages",
        _with_progress("merge_flow_pages", merge_flow_pages_node),
    )
    graph.add_edge("compose_flow_agents", "merge_flow_pages")
    graph.add_edge("merge_flow_pages", "quality_gate")

    graph.add_node("quality_gate", _with_progress("quality_gate", quality_gate_node))
    graph.add_node("heal_pages", _with_progress("heal_pages", heal_pages_node))
    graph.add_node("create_links", _with_progress("create_links", create_links_node))
    graph.add_node("generate_tour", _with_progress("generate_tour", generate_tour_node))
    graph.add_node("finalize", _with_progress("finalize", finalize_node))

    graph.add_edge("classify_entity_roles", "classify_architecture_layers")
    graph.add_edge("classify_architecture_layers", "detect_reorg")
    graph.add_conditional_edges(
        "detect_reorg",
        route_by_reorg_type,
        {"graph_decompose": "graph_decompose", "finalize": "finalize"},
    )
    graph.add_edge("graph_decompose", "assign_canonical_keys")
    graph.add_edge("assign_canonical_keys", "generate_titles")
    graph.add_edge("generate_titles", "compose_leaf_modules")
    graph.add_edge("compose_leaf_modules", "classify_domains")
    graph.add_edge("classify_domains", "persist_classification")
    graph.add_edge("persist_classification", "set_review_status")
    graph.add_edge("set_review_status", "compose_domain_agents")
    graph.add_conditional_edges(
        "quality_gate",
        should_heal,
        {"heal_pages": "heal_pages", "create_links": "create_links"},
    )
    graph.add_edge("heal_pages", "quality_gate")
    graph.add_edge("create_links", "generate_tour")
    graph.add_edge("generate_tour", "finalize")

    graph.set_entry_point("classify_entity_roles")
    graph.set_finish_point("finalize")

    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return graph.compile(checkpointer=checkpointer)


def get_checkpointer(business_id: str, checkpoint_dir: str | None = None):
    """Return an async context manager that yields ``AsyncSqliteSaver`` for ``business_id``.

    Usage::

        async with get_checkpointer(business_id) as checkpointer:
            pipeline = build_wiki_pipeline(checkpointer=checkpointer)
            await pipeline.ainvoke(...)
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if checkpoint_dir is None:
        checkpoint_dir = os.environ.get(
            "WIKI_CHECKPOINT_DIR",
            os.path.join(os.path.dirname(__file__), "..", "data", "checkpoints"),
        )
    os.makedirs(checkpoint_dir, exist_ok=True)
    db_path = os.path.join(checkpoint_dir, f"{business_id}_wiki.db")
    return AsyncSqliteSaver.from_conn_string(db_path)
