"""LangGraph StateGraph definition for Wiki generation pipeline."""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from log import get_logger
from wiki.models import ImportanceTier, WikiPage
from wiki.pipeline_nodes import classify_entities_node
from wiki.pipeline_state import WikiPipelineState
from wiki.quality_evaluator import WikiQualityEvaluator

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def should_heal(state: WikiPipelineState) -> str:
    """Route to heal_pages if quality_gate_node identified pages to heal."""
    if state.get("pages_to_heal"):
        return "heal_pages"
    return "finalize"


# ---------------------------------------------------------------------------
# Stub nodes (to be replaced with real logic in later Sprints)
# ---------------------------------------------------------------------------

async def classify_domains_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="classify_domains")
    return {}


async def decompose_hierarchy_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="decompose_hierarchy")
    return {}


async def plan_structure_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="plan_structure")
    return {}


async def compose_pages_node(state: WikiPipelineState) -> dict[str, Any]:
    log.info("pipeline_node_stub", node="compose_pages")
    return {}


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


async def heal_pages_node(state: WikiPipelineState) -> dict[str, Any]:
    """Increment heal attempts and persist heal hints for recomposition."""
    evaluator = WikiQualityEvaluator()
    heal_attempts = dict(state.get("heal_attempts", {}))
    heal_hints: dict[str, str] = dict(state.get("heal_hints", {}))
    seen: set[str] = set()

    for page_path in state.get("pages_to_heal", []):
        if page_path in seen:
            continue
        seen.add(page_path)
        heal_attempts[page_path] = heal_attempts.get(page_path, 0) + 1

        page_dict = next((p for p in state.get("pages", []) if p.get("path") == page_path), None)
        if page_dict:
            try:
                page = WikiPage.from_dict(page_dict)
                score = evaluator.structural_check(page)
                hint = evaluator.build_heal_prompt_hint(score)
                heal_hints[page_path] = hint
                log.info(
                    "page_heal_scheduled",
                    page=page_path,
                    attempt=heal_attempts[page_path],
                    hint_length=len(hint),
                )
            except Exception:
                log.warning("heal_page_analysis_failed", page=page_path, exc_info=True)

    log.info("heal_pages_done", healed_count=len(seen))
    return {"pages_to_heal": [], "heal_attempts": heal_attempts, "heal_hints": heal_hints}


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

def build_wiki_pipeline(checkpointer: Any | None = None) -> Any:
    """Build and compile the Wiki generation StateGraph.

    Args:
        checkpointer: Checkpoint backend. Defaults to in-memory
            ``MemorySaver``. For production persistence, pass
            ``AsyncSqliteSaver`` or ``RedisSaver``::

                async with AsyncSqliteSaver.from_conn_string(path) as saver:
                    pipeline = build_wiki_pipeline(checkpointer=saver)
    """
    graph = StateGraph(WikiPipelineState)

    graph.add_node("collect_modules", classify_entities_node)
    graph.add_node("classify_domains", classify_domains_node)
    graph.add_node("decompose_hierarchy", decompose_hierarchy_node)
    graph.add_node("plan_structure", plan_structure_node)
    graph.add_node("compose_pages", compose_pages_node)
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("heal_pages", heal_pages_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge("collect_modules", "classify_domains")
    graph.add_edge("classify_domains", "decompose_hierarchy")
    graph.add_edge("decompose_hierarchy", "plan_structure")
    graph.add_edge("plan_structure", "compose_pages")
    graph.add_edge("compose_pages", "quality_gate")

    graph.add_conditional_edges(
        "quality_gate",
        should_heal,
        {"heal_pages": "heal_pages", "finalize": "finalize"},
    )
    graph.add_edge("heal_pages", "compose_pages")

    graph.set_entry_point("collect_modules")
    graph.set_finish_point("finalize")

    if checkpointer is None:
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
