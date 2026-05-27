"""Wiki generation pipeline state for LangGraph StateGraph."""
from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from core.log import get_logger

log = get_logger(__name__)


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
            log.warning("merge_wiki_pages_skip_no_path", page_title=p.get("title", ""))
            continue
        if path not in by_path:
            order.append(path)
        by_path[path] = p
    for p in right:
        path = str(p.get("path") or "")
        if not path:
            log.warning("merge_wiki_pages_skip_no_path", page_title=p.get("title", ""))
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
    run_id: str

    # --- Stage outputs (accumulated by nodes) ---
    modules: dict[str, list[Any]]
    domain_mapping: dict[str, list[Any]]
    domain_tree: list[dict[str, Any]] | None
    topic_structure: list[dict[str, Any]] | None
    pages: Annotated[list[dict[str, Any]], merge_wiki_pages]

    # --- Quality tracking ---
    quality_scores: dict[str, dict[str, Any]]
    pages_to_heal: list[str]
    # Per-page total inner-round heal attempts across all outer cycles.
    heal_attempts: dict[str, int]
    # Per-page outer quality-gate → heal loop iterations.
    heal_cycles: NotRequired[dict[str, int]]
    heal_hints: dict[str, str]

    # --- Observability ---
    errors: list[str]

    # --- Entity classification (Phase 1) ---
    entity_roles: dict[str, str]
    role_stats: dict[str, int]

    # --- Incremental / reorg ---
    is_incremental: bool
    reorg_type: str
    affected_domains: list[str]
    existing_domain_mapping: NotRequired[dict[str, list[tuple[str, str]]]]
    pinned_modules: NotRequired[dict[str, str]]
    anchored_slugs: NotRequired[set[str]]
    anchor_display_names: NotRequired[dict[str, str]]
    affected_modules: NotRequired[set[str]]

    # --- Review tracking ---
    review_status: dict[str, str]
    review_notes: dict[str, str]

    # --- Phase 3-4 outputs ---
    generated_topic_pages: list[str]
    overview_pages: list[str]
    system_overview_uid: str
    # wiki [[link]] resolution metadata (applied when persisting pages)
    resolved_links: dict[str, list[dict[str, str]]]

    # Module-level summaries (populated by compose_leaf_modules_node, used by compose_leaf_pages)
    module_summaries: NotRequired[dict[str, dict[str, Any]]]

    # Leaf domain summaries (populated by summarize_leaves_node)
    leaf_summaries: NotRequired[dict[str, Any]]

    # --- Graph-based decomposition (v2 pipeline) ---
    module_tree: NotRequired[list[dict[str, Any]]]  # serialized ModuleTree
    canonical_keys: NotRequired[dict[str, str]]  # canonical_key → readable title
    domain_cache: NotRequired[dict[str, str]]  # pipeline-level shared domain cache
    # --- Domain reassembly (post-wiki-generation correction) ---
    reassembly_actions: NotRequired[list[dict[str, Any]]]
    module_call_edges: NotRequired[list[dict[str, Any]]]  # cross-module call edges for parent overview stats

    # --- Domain display names (set by graph_domain_decompose, consumed by persist_classification + service) ---
    domain_display_names: NotRequired[dict[str, str]]  # slug → localized display name

    # English slug phrases → Chinese display names for term consistency (graph_domain_decompose)
    term_glossary: NotRequired[dict[str, str]]

    # Module-level architecture layer classification (classify_architecture_layers node)
    architecture_layers: NotRequired[dict[str, dict[str, Any]]]

    # --- Structural check cache (avoids redundant quality_evaluator calls) ---
    _structural_check_cache: NotRequired[dict[str, dict[str, Any]]]  # path -> {score, content_hash}

    # --- Flow composition + guided tour (Batch 3) ---
    flow_pages: NotRequired[list[dict[str, Any]]]
    guided_tour: NotRequired[dict[str, Any]]

    # --- Persistence handle ---
    persistence: NotRequired[Any]

    # --- Existing module summaries for incremental reuse ---
    existing_summaries: NotRequired[dict[str, dict[str, Any]]]

    # --- Embedding cache (SHA-256 text hash → vector; shared across pipeline nodes) ---
    embedding_cache: NotRequired[dict[str, list[float]]]

    # --- Per-node status tracking for dashboard visualization ---
    # node_name → {status, started_at, completed_at, elapsed_sec, detail}
    node_statuses: NotRequired[dict[str, dict[str, Any]]]
