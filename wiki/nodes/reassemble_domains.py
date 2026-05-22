"""Wiki-driven domain reassembly node for the wiki pipeline."""
from __future__ import annotations

import itertools
from typing import Any

import numpy as np

from core.log import get_logger

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
