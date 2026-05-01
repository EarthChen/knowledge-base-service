"""LangGraph StateGraph definition for Wiki generation pipeline."""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from log import get_logger
from wiki.models import ImportanceTier, WikiPage
from wiki.pipeline_nodes import (
    classify_domains_node,
    classify_entities_node,
    compose_leaf_pages_node,
    create_links_node,
    decompose_hierarchy_node,
    detect_reorg_node,
    heal_pages_node,
    set_review_status_node,
    synthesize_overviews_node,
)
from wiki.pipeline_state import WikiPipelineState
from wiki.quality_evaluator import WikiQualityEvaluator

log = get_logger(__name__)

HEAL_LOOP_MAX_TOTAL_ATTEMPTS = 10

# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def route_by_reorg_type(state: WikiPipelineState) -> str:
    """Route based on detected reorg type."""
    reorg_type = state.get("reorg_type", "first_run")
    if reorg_type == "none":
        return "finalize"
    return "classify_domains"


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
            return "synthesize_overviews"
        return "heal_pages"
    return "synthesize_overviews"


# ---------------------------------------------------------------------------
# Quality / finalize nodes (graph-local)
# ---------------------------------------------------------------------------

async def quality_gate_node(state: WikiPipelineState) -> dict[str, Any]:
    """Evaluate page quality, identify pages needing healing."""
    evaluator = WikiQualityEvaluator()
    scores: dict[str, float] = {}
    pages_to_heal: list[str] = []
    importance_tiers: dict[str, str] = state.get("config", {}).get("importance_tiers", {})
    heal_attempts = state.get("heal_attempts", {})

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
            scores[page.path] = 1.0
            continue

        score = evaluator.structural_check(page)
        scores[page.path] = score.overall

        threshold = 0.7 if tier == ImportanceTier.CORE else 0.5
        max_retries = 2 if tier == ImportanceTier.CORE else 1
        attempts = heal_attempts.get(page.path, 0)

        if score.overall < threshold and attempts < max_retries:
            pages_to_heal.append(page.path)

    log.info(
        "quality_gate_done",
        total_pages=len(state.get("pages", [])),
        evaluated=len(scores),
        to_heal=len(pages_to_heal),
    )
    return {"quality_scores": scores, "pages_to_heal": pages_to_heal}


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

    graph.add_node("classify_entity_roles", classify_entities_node)
    graph.add_node("detect_reorg", detect_reorg_node)
    graph.add_node("classify_domains", classify_domains_node)
    graph.add_node("decompose_hierarchy", decompose_hierarchy_node)
    graph.add_node("set_review_status", set_review_status_node)
    graph.add_node("compose_leaf_pages", compose_leaf_pages_node)
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("heal_pages", heal_pages_node)
    graph.add_node("synthesize_overviews", synthesize_overviews_node)
    graph.add_node("create_links", create_links_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge("classify_entity_roles", "detect_reorg")
    graph.add_conditional_edges(
        "detect_reorg",
        route_by_reorg_type,
        {"classify_domains": "classify_domains", "finalize": "finalize"},
    )
    graph.add_edge("classify_domains", "decompose_hierarchy")
    graph.add_edge("decompose_hierarchy", "set_review_status")
    graph.add_edge("set_review_status", "compose_leaf_pages")
    graph.add_edge("compose_leaf_pages", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        should_heal,
        {"heal_pages": "heal_pages", "synthesize_overviews": "synthesize_overviews"},
    )
    graph.add_edge("heal_pages", "quality_gate")
    graph.add_edge("synthesize_overviews", "create_links")
    graph.add_edge("create_links", "finalize")

    graph.set_entry_point("classify_entity_roles")
    graph.set_finish_point("finalize")

    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return graph.compile(checkpointer=checkpointer)
