"""Wiki generation pipeline state for LangGraph StateGraph."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class WikiPipelineState(TypedDict):
    """State flowing through the Wiki generation pipeline.

    Each LangGraph node reads from and writes to this state.
    Only fields returned by a node are updated; others are preserved.
    """

    # --- Input (set once at pipeline start) ---
    business_id: str
    repositories: list[str]
    config: dict[str, Any]

    # --- Stage outputs (accumulated by nodes) ---
    modules: dict[str, list[Any]]
    domain_mapping: dict[str, list[Any]]
    domain_tree: list[dict[str, Any]] | None
    topic_structure: list[dict[str, Any]] | None
    pages: Annotated[list[dict[str, Any]], operator.add]

    # --- Quality tracking ---
    quality_scores: dict[str, float]
    pages_to_heal: list[str]
    heal_attempts: dict[str, int]
    heal_hints: dict[str, str]

    # --- Observability ---
    stage_timings: dict[str, float]
    llm_call_count: int
    errors: list[str]

    # --- Entity classification (Phase 1) ---
    entity_roles: dict[str, str]
    role_stats: dict[str, int]

    # --- Incremental / reorg ---
    is_incremental: bool
    reorg_type: str
    affected_domains: list[str]

    # --- Review tracking ---
    review_status: dict[str, str]
    review_notes: dict[str, str]
