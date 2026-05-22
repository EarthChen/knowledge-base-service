"""Wiki-driven domain reassembly node for the wiki pipeline."""
from __future__ import annotations

import itertools
from typing import Any

import numpy as np
from langchain_core.runnables import RunnableConfig

from core.config import get_settings
from core.log import get_logger
from indexer.embedding_generator import EmbeddingGenerator
from wiki.json_robust import parse_json_robust_sync

log = get_logger(__name__)

_CONTENT_TRUNCATE_LEN = 2000


def _extract_domain_slug(path: str) -> str | None:
    """Extract domain slug from a page path ending with /_overview."""
    if not path.endswith("/_overview"):
        return None
    parts = path.rsplit("/", 1)
    return parts[0] if parts else None


async def _extract_domain_embeddings(
    pages: list[dict[str, Any]],
    embedding_generator: Any,
) -> dict[str, np.ndarray]:
    """Embed each domain's overview page content."""
    overview_pages: list[tuple[str, str]] = []
    for page in pages:
        path = str(page.get("path") or "")
        slug = _extract_domain_slug(path)
        if slug is None:
            continue
        content = str(page.get("content") or "")[:_CONTENT_TRUNCATE_LEN]
        if content.strip():
            overview_pages.append((slug, content))

    if not overview_pages:
        return {}

    texts = [content for _, content in overview_pages]
    embeddings_list = await embedding_generator.generate(texts)

    result: dict[str, np.ndarray] = {}
    for (slug, _), emb in zip(overview_pages, embeddings_list):
        result[slug] = np.array(emb, dtype=np.float32)
    return result


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _find_merge_candidates(
    embeddings: dict[str, np.ndarray],
    threshold: float,
    pinned_domains: set[str],
) -> list[dict[str, Any]]:
    """Find domain pairs with cosine similarity above threshold."""
    candidates: list[dict[str, Any]] = []
    for (d1, e1), (d2, e2) in itertools.combinations(embeddings.items(), 2):
        if d1 in pinned_domains or d2 in pinned_domains:
            continue
        sim = _cosine_similarity(e1, e2)
        if sim > threshold:
            candidates.append({"source": d1, "target": d2, "similarity": sim})

    candidates.sort(key=lambda x: -x["similarity"])
    return candidates


async def _match_orphan_pages(
    orphan_pages: list[dict[str, Any]],
    domain_embeddings: dict[str, np.ndarray],
    embedding_generator: Any,
    threshold: float,
    pinned_domains: set[str],
) -> list[dict[str, Any]]:
    """Match orphan pages to the closest domain by embedding similarity."""
    if not orphan_pages or not domain_embeddings:
        return []

    texts = [str(p.get("content") or "")[:_CONTENT_TRUNCATE_LEN] for p in orphan_pages]
    orphan_embeddings = await embedding_generator.generate(texts)

    assignments: list[dict[str, Any]] = []
    for page, emb_list in zip(orphan_pages, orphan_embeddings):
        orphan_emb = np.array(emb_list, dtype=np.float32)
        best_domain: str | None = None
        best_score = -1.0

        for slug, domain_emb in domain_embeddings.items():
            if slug in pinned_domains:
                continue
            score = _cosine_similarity(orphan_emb, domain_emb)
            if score > best_score:
                best_score = score
                best_domain = slug

        if best_domain and best_score >= threshold:
            assignments.append({
                "orphan_path": page.get("path", ""),
                "assigned_domain": best_domain,
                "similarity": best_score,
            })

    return assignments


def _get_embedding_generator() -> Any:
    """Get shared embedding generator instance."""
    config = get_settings().embedding
    return EmbeddingGenerator.shared(config)


def _get_llm_provider(config: RunnableConfig | None = None) -> Any:
    """Get LLM provider from config."""
    configurable = (config or {}).get("configurable", {}) or {}
    return configurable.get("llm")


async def _get_pinned_domains(
    config: RunnableConfig | None = None,
    state: dict[str, Any] | None = None,
) -> set[str]:
    """Query wiki tree store for user_modified sections."""
    configurable = (config or {}).get("configurable", {}) or {}
    wiki_tree_store = configurable.get("wiki_tree_store")
    if not wiki_tree_store:
        return set()
    try:
        business_id = configurable.get("business_id", "")
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})"
            "-[:HAS_CHILD*1..8]->(sec:WikiSection) "
            "WHERE sec.user_modified = true "
            "RETURN sec.title AS title"
        )
        result = await wiki_tree_store._store.execute_query(q, {"business_id": business_id})
        rows = getattr(result, "data", None) or []

        domain_display_names = (state or {}).get("domain_display_names") or {}
        display_to_slug = {v: k for k, v in domain_display_names.items()}

        pinned: set[str] = set()
        for row in rows:
            title = row.get("title", "") if isinstance(row, dict) else ""
            if title in domain_display_names:
                pinned.add(title)
            elif title in display_to_slug:
                pinned.add(display_to_slug[title])
        return pinned
    except Exception:
        log.warning("reassembly_pinned_domains_query_failed", exc_info=True)
        return set()


def _execute_merges(
    domain_mapping: dict[str, list[Any]],
    domain_display_names: dict[str, str],
    domain_tree: list[dict[str, Any]],
    approved_merges: list[dict[str, str]],
) -> tuple[dict[str, list[Any]], dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute approved merges and return updated structures + action log."""
    actions: list[dict[str, Any]] = []
    merged_away: set[str] = set()

    for merge in approved_merges:
        source = merge.get("source", "")
        target = merge.get("target", "")
        if source in merged_away or target in merged_away:
            continue
        if source not in domain_mapping or target not in domain_mapping:
            continue

        domain_mapping.setdefault(target, []).extend(domain_mapping.pop(source, []))
        domain_display_names.pop(source, None)
        merged_away.add(source)
        actions.append({"type": "merge", "source": source, "target": target})

    new_tree = [node for node in domain_tree if node.get("name") not in merged_away]
    return domain_mapping, domain_display_names, new_tree, actions


async def _llm_review_merges(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    llm: Any,
) -> list[dict[str, str]]:
    """Call LLM to approve/reject merge candidates."""
    page_by_slug: dict[str, str] = {}
    for p in pages:
        slug = _extract_domain_slug(str(p.get("path") or ""))
        if slug:
            page_by_slug[slug] = str(p.get("content") or "")[:500]

    candidate_desc = []
    for c in candidates[:5]:
        s_content = page_by_slug.get(c["source"], "")[:200]
        t_content = page_by_slug.get(c["target"], "")[:200]
        candidate_desc.append(
            f"- Source domain '{c['source']}' (similarity={c['similarity']:.3f}):\n"
            f"  Content: {s_content}\n"
            f"  Target domain '{c['target']}':\n"
            f"  Content: {t_content}"
        )

    prompt = (
        "Review the following domain merge candidates. Each pair has high semantic similarity.\n"
        "Approve merges ONLY if the domains genuinely describe the same business functionality.\n"
        'Respond in JSON: {"approved_merges": [{"source": "...", "target": "..."}]}\n\n'
        + "\n".join(candidate_desc)
    )

    response = await llm.complete([{"role": "user", "content": prompt}])
    parsed = parse_json_robust_sync(str(response))
    if isinstance(parsed, dict):
        return parsed.get("approved_merges", [])
    return []


async def reassemble_domains_node(
    state: dict[str, Any], config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Post-wiki domain reassembly: merge similar domains + match orphans."""
    pipeline_config = state.get("config") or {}

    if pipeline_config.get("reassembly_enabled") is False:
        log.info("reassembly_skipped", reason="disabled")
        return {"reassembly_actions": []}

    settings = get_settings().wiki
    if not settings.domain_reassembly_enabled:
        log.info("reassembly_skipped", reason="disabled_in_settings")
        return {"reassembly_actions": []}

    merge_threshold = pipeline_config.get(
        "reassembly_merge_threshold", settings.reassembly_merge_threshold
    )
    orphan_threshold = pipeline_config.get(
        "reassembly_orphan_threshold", settings.reassembly_orphan_threshold
    )
    max_moves_pct = pipeline_config.get(
        "reassembly_max_moves_pct", settings.reassembly_max_moves_pct
    )
    respect_pinned = pipeline_config.get(
        "reassembly_respect_user_modified",
        settings.reassembly_respect_user_modified,
    )

    pages = state.get("pages") or []
    domain_mapping = {k: list(v) for k, v in (state.get("domain_mapping") or {}).items()}
    domain_tree = list(state.get("domain_tree") or [])
    domain_display_names = dict(state.get("domain_display_names") or {})
    original_module_count = sum(len(v) for v in domain_mapping.values())

    # --- Step 1: Embed domain overviews ---
    try:
        generator = _get_embedding_generator()
        domain_embeddings = await _extract_domain_embeddings(pages, generator)
    except Exception:
        log.warning("reassembly_embedding_failed", exc_info=True)
        return {"reassembly_actions": []}

    if len(domain_embeddings) < 2:
        log.info("reassembly_skipped", reason="insufficient_domains", count=len(domain_embeddings))
        return {"reassembly_actions": []}

    # --- Step 2: Find pinned domains ---
    pinned_domains: set[str] = set()
    if respect_pinned:
        pinned_domains = await _get_pinned_domains(config, state)

    # --- Step 3: Find merge candidates ---
    merge_candidates = _find_merge_candidates(domain_embeddings, merge_threshold, pinned_domains)

    # --- Step 4: LLM review (only if candidates exist) ---
    approved_merges: list[dict[str, str]] = []
    if merge_candidates:
        llm = _get_llm_provider(config)
        if llm:
            try:
                approved_merges = await _llm_review_merges(merge_candidates, pages, llm)
            except Exception:
                log.warning("reassembly_llm_review_failed", exc_info=True)

    # --- Step 5: Execute merges ---
    actions: list[dict[str, Any]] = []
    if approved_merges:
        domain_mapping, domain_display_names, domain_tree, merge_actions = _execute_merges(
            domain_mapping, domain_display_names, domain_tree, approved_merges,
        )
        actions.extend(merge_actions)

    # --- Step 6: Orphan matching ---
    known_slugs = set(domain_mapping.keys())
    merged_sources = {a["source"] for a in actions if a["type"] == "merge"}
    orphan_pages = [
        p for p in pages
        if (slug := _extract_domain_slug(str(p.get("path") or ""))) is not None
        and slug not in known_slugs
        and slug not in merged_sources
    ]
    if orphan_pages and domain_embeddings:
        try:
            orphan_assignments = await _match_orphan_pages(
                orphan_pages, domain_embeddings, generator, orphan_threshold, pinned_domains,
            )
            for assignment in orphan_assignments:
                actions.append({"type": "orphan_match", **assignment})
        except Exception:
            log.warning("reassembly_orphan_matching_failed", exc_info=True)

    # --- Step 7: Rollback check ---
    actual_moves = len(actions)
    max_allowed_moves = max(1, max_moves_pct * original_module_count)
    if original_module_count > 0 and actual_moves > max_allowed_moves:
        log.warning(
            "reassembly_rollback",
            moved=actual_moves,
            total=original_module_count,
            max_pct=max_moves_pct,
        )
        return {"reassembly_actions": [{"type": "rollback", "reason": "too_many_moves"}]}

    # --- Step 8: Persist reassembly results ---
    if actions:
        configurable = (config or {}).get("configurable", {}) or {}
        wiki_store = configurable.get("wiki_store")
        graph_store = configurable.get("graph_store")
        business_id = state.get("business_id", "")

        if wiki_store and business_id:
            try:
                from wiki.nodes.persist_classification import _persist_domain_tree_to_wiki

                await _persist_domain_tree_to_wiki(
                    wiki_store, business_id, domain_mapping,
                    domain_display_names, domain_tree,
                )
                log.info("reassembly_persisted_tree", business_id=business_id)
            except Exception:
                log.warning("reassembly_persist_tree_failed", exc_info=True)

        if graph_store and business_id:
            try:
                from wiki.nodes.persist_classification import _persist_domain_labels_on_modules

                await _persist_domain_labels_on_modules(
                    graph_store, business_id, domain_mapping, state.get("modules", {}),
                )
                log.info("reassembly_persisted_labels", business_id=business_id)
            except Exception:
                log.warning("reassembly_persist_labels_failed", exc_info=True)

    log.info("reassembly_complete", actions_count=len(actions))
    return {
        "domain_mapping": domain_mapping,
        "domain_tree": domain_tree,
        "domain_display_names": domain_display_names,
        "reassembly_actions": actions,
    }
