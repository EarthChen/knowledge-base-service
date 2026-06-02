"""LangGraph StateGraph definition for Wiki generation pipeline."""
# NOTE: Do NOT add `from __future__ import annotations` here.
# LangGraph needs real type objects (not strings) to detect RunnableConfig
# parameters and automatically inject config into nodes.

import inspect
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy, TimeoutPolicy

try:
    from langgraph.errors import NodeTimeoutError
except ImportError:
    NodeTimeoutError = TimeoutError

from core.log import get_logger
from wiki.nodes.classify_architecture import classify_architecture_layers_node
from wiki.nodes.compose_error_handler import compose_error_fallback
from wiki.nodes.finalize import finalize_node
from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node
from wiki.nodes.quality_gate import quality_gate_node
from wiki.nodes.reassemble_domains import reassemble_domains_node
from wiki.pipeline_nodes import (
    assign_canonical_keys_node,
    classify_entities_node,
    compose_domain_agents_node,
    compose_flow_agents_node,
    compose_leaf_modules_node,
    compose_parent_pages_node,
    create_links_node,
    detect_reorg_node,
    generate_titles_node,
    generate_tour_node,
    graph_decompose_node,
    heal_pages_node,
    merge_flow_pages_node,
    persist_classification_node,
    set_review_status_node,
    summarize_leaves_node,
)
from wiki.pipeline_state import WikiPipelineState

log = get_logger(__name__)

# Node name → (API phase label, baseline progress 0..1 for task status / UI)
_NODE_PHASE_MAP: dict[str, tuple[str, float]] = {
    "classify_entity_roles": ("classify_entities", 0.0),
    "detect_reorg": ("detect_reorg", 0.02),
    "graph_decompose": ("graph_decompose", 0.05),
    "assign_canonical_keys": ("assign_keys", 0.07),
    "generate_titles": ("generate_titles", 0.08),
    "compose_leaf_modules": ("compose_leaf_modules", 0.10),
    "classify_architecture_layers": ("classify_architecture_layers", 0.15),
    "graph_domain_decompose": ("graph_domain_decompose", 0.18),
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


async def _notify_progress(
    cb: Any,
    phase: str,
    pct: float,
    node_name: str,
    status: str,
    statuses: dict,
    elapsed: float | None = None,
) -> None:
    """Fire a progress callback, swallowing failures."""
    if not cb:
        return
    detail = f"{phase} {status}"
    if status == "completed" and elapsed is not None:
        detail = f"{phase} 完成 ({elapsed:.1f}s)"
    elif status == "failed":
        detail = f"{phase} 失败"
    elif status == "running":
        detail = f"{phase} 开始"
    payload: dict[str, Any] = {
        "phase": phase,
        "progress_pct": pct,
        "detail": detail,
        "node_name": node_name,
        "node_status": status,
        "node_statuses": statuses,
    }
    if elapsed is not None:
        payload["elapsed_sec"] = round(elapsed, 2)
    try:
        await cb(payload)
    except Exception:
        log.debug("progress_callback_failed", phase=phase, exc_info=True)


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
    pass_runtime = any(
        p.name == "runtime" and p.kind == inspect.Parameter.KEYWORD_ONLY
        for p in _sig.parameters.values()
    )

    if pass_config and pass_runtime:
        async def _wrapper(
            state: WikiPipelineState,
            config: RunnableConfig | None = None,
            *,
            runtime: Any = None,
        ) -> dict[str, Any]:
            configurable = (config or {}).get("configurable", {}) or {}
            cb = configurable.get("progress_callback")
            now = time.time()
            statuses = dict(state.get("node_statuses") or {})
            statuses[node_name] = {"status": "running", "started_at": now}
            await _notify_progress(cb, phase, pct, node_name, "running", statuses)
            log.info("pipeline_node_enter", node=node_name, phase=phase)
            t0 = time.monotonic()
            try:
                result = await func(state, config, runtime=runtime)
            except Exception:
                elapsed = time.monotonic() - t0
                statuses[node_name] = {
                    "status": "failed", "started_at": now,
                    "completed_at": time.time(), "elapsed_sec": round(elapsed, 2),
                }
                await _notify_progress(cb, phase, pct, node_name, "failed", statuses, elapsed)
                raise
            elapsed = time.monotonic() - t0
            log.info("pipeline_node_exit", node=node_name, phase=phase, elapsed_sec=round(elapsed, 1))
            statuses[node_name] = {
                "status": "completed", "started_at": now,
                "completed_at": time.time(), "elapsed_sec": round(elapsed, 2),
            }
            await _notify_progress(cb, phase, pct, node_name, "completed", statuses, elapsed)
            return result
    elif pass_config:
        async def _wrapper(
            state: WikiPipelineState,
            config: RunnableConfig | None = None,
        ) -> dict[str, Any]:
            configurable = (config or {}).get("configurable", {}) or {}
            cb = configurable.get("progress_callback")
            now = time.time()
            statuses = dict(state.get("node_statuses") or {})
            statuses[node_name] = {"status": "running", "started_at": now}
            await _notify_progress(cb, phase, pct, node_name, "running", statuses)
            log.info("pipeline_node_enter", node=node_name, phase=phase)
            t0 = time.monotonic()
            try:
                result = await func(state, config)
            except Exception:
                elapsed = time.monotonic() - t0
                statuses[node_name] = {
                    "status": "failed", "started_at": now,
                    "completed_at": time.time(), "elapsed_sec": round(elapsed, 2),
                }
                await _notify_progress(cb, phase, pct, node_name, "failed", statuses, elapsed)
                raise
            elapsed = time.monotonic() - t0
            log.info("pipeline_node_exit", node=node_name, phase=phase, elapsed_sec=round(elapsed, 1))
            statuses[node_name] = {
                "status": "completed", "started_at": now,
                "completed_at": time.time(), "elapsed_sec": round(elapsed, 2),
            }
            await _notify_progress(cb, phase, pct, node_name, "completed", statuses, elapsed)
            return result
    else:
        async def _wrapper(state: WikiPipelineState) -> dict[str, Any]:  # type: ignore[misc]
            log.info("pipeline_node_enter", node=node_name, phase=phase)
            t0 = time.monotonic()
            result = await func(state)
            elapsed = time.monotonic() - t0
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
    return "classify_entity_roles"


def should_heal(state: WikiPipelineState) -> str:
    """Route to heal_pages if quality_gate_node identified pages to heal.

    Counter semantics (see also ``WikiPipelineState`` and ``quality_gate_node``):
    - ``heal_attempts[page]``: total inner-round attempts across all cycles.
    - ``heal_cycles[page]``: outer quality-gate → heal loop iterations.

    The outer safety limit sums ``heal_cycles`` when present; ``heal_attempts`` is
    only used as a legacy fallback when ``heal_cycles`` was never initialized.
    """
    if state.get("pages_to_heal"):
        cfg = state.get("config") or {}
        max_total = cfg.get("heal_loop_max_total_attempts", 10)
        heal_cycles = state.get("heal_cycles")
        if heal_cycles is not None:
            total_heal_cycles = sum(heal_cycles.values())
        else:
            total_heal_cycles = sum(state.get("heal_attempts", {}).values())
        if total_heal_cycles > max_total:
            log.warning(
                "heal_loop_safety_limit",
                total_cycles=total_heal_cycles,
                limit=max_total,
            )
            return "create_links"
        return "heal_pages"
    return "create_links"


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
    graph.add_node(
        "graph_domain_decompose",
        _with_progress("graph_domain_decompose", graph_driven_domain_decompose_node),
    )
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
        timeout=TimeoutPolicy(
            run_timeout=3600,
            idle_timeout=180,
        ),
        retry_policy=RetryPolicy(max_attempts=2, retry_on=(NodeTimeoutError, TimeoutError)),
        error_handler=compose_error_fallback,
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

    graph.add_edge("classify_entity_roles", "graph_decompose")
    graph.add_conditional_edges(
        "detect_reorg",
        route_by_reorg_type,
        {"classify_entity_roles": "classify_entity_roles", "finalize": "finalize"},
    )
    graph.add_edge("graph_decompose", "assign_canonical_keys")
    graph.add_edge("assign_canonical_keys", "generate_titles")
    graph.add_edge("generate_titles", "compose_leaf_modules")
    graph.add_edge("compose_leaf_modules", "classify_architecture_layers")
    graph.add_edge("classify_architecture_layers", "graph_domain_decompose")
    graph.add_edge("graph_domain_decompose", "persist_classification")
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

    graph.set_entry_point("detect_reorg")
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
