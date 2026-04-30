"""Wiki generation pipeline state for LangGraph StateGraph."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_wiki_pages(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge wiki page dicts by ``path``; newer entries replace older with the same path.

    Preserves order: paths first seen in ``left``, then new paths introduced in ``right``.
    Used instead of ``operator.add`` so heal cycles can return only updated pages
    without growing the list with duplicates.
    """
    by_path: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for p in left:
        path = str(p.get("path") or "")
        if not path:
            continue
        if path not in by_path:
            order.append(path)
        by_path[path] = p
    for p in right:
        path = str(p.get("path") or "")
        if not path:
            continue
        if path not in by_path:
            order.append(path)
        by_path[path] = p
    return [by_path[path] for path in order]


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
    pages: Annotated[list[dict[str, Any]], merge_wiki_pages]

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

    # --- Phase 3-4 outputs ---
    generated_topic_pages: list[str]
    overview_pages: list[str]
    system_overview_uid: str
    # wiki [[link]] resolution metadata (applied when persisting pages)
    resolved_links: dict[str, list[dict[str, str]]]
