"""Shared search fusion utilities: RRF, score normalization, and position-aware blending."""

from __future__ import annotations


def _min_max_normalize(scores: list[float]) -> list[float]:
    """Normalize scores to [0, 1] using min-max scaling.

    If all scores are identical (or list is empty), returns 1.0 for all.
    """
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def rrf_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    weights: list[float],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Weighted Reciprocal Rank Fusion with top-rank bonus.

    Each ranked_list is [(doc_id, original_score), ...] in rank order.
    The original_score is not used in RRF computation (only rank matters),
    but is accepted for API compatibility.

    Top-rank bonus: #1 in any list gets +0.05, #2-3 get +0.02.

    Args:
        ranked_lists: Per-source ranked result lists.
        weights: Per-list weight multipliers.
        k: RRF constant (default 60).

    Returns:
        Merged list sorted by fused score descending.
    """
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}

    for li, ranked in enumerate(ranked_lists):
        w = weights[li] if li < len(weights) else 1.0
        for rank, (doc_id, _) in enumerate(ranked):
            contrib = w * (1.0 / (k + rank + 1))
            scores[doc_id] = scores.get(doc_id, 0.0) + contrib
            prev = best_rank.get(doc_id)
            if prev is None or rank < prev:
                best_rank[doc_id] = rank

    for doc_id, br in best_rank.items():
        if br == 0:
            scores[doc_id] += 0.05
        elif br in (1, 2):
            scores[doc_id] += 0.02

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    max_score = ranked[0][1]
    if max_score <= 0:
        return [(doc_id, 0.0) for doc_id, _ in ranked]

    return [(doc_id, s / max_score) for doc_id, s in ranked]


def position_aware_blend(
    rrf_scores: list[tuple[str, float]],
    reranker_scores: dict[str, float],
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Blend RRF and reranker scores with position-aware weights.

    Both RRF scores and reranker scores are min-max normalized to [0,1]
    before blending to handle different score scales.

    Blending weights by RRF rank position:
      - Rank 0-2 (top 3):   75% retrieval, 25% reranker (protect exact matches)
      - Rank 3-9 (4th-10th): 60% retrieval, 40% reranker
      - Rank 10+:            40% retrieval, 60% reranker (trust reranker more)
    """
    rrf_vals = [s for _, s in rrf_scores]
    rrf_norm = _min_max_normalize(rrf_vals)

    re_vals = list(reranker_scores.values())
    re_norm_map: dict[str, float] = {}
    if re_vals:
        re_normed = _min_max_normalize(re_vals)
        re_keys = list(reranker_scores.keys())
        re_norm_map = dict(zip(re_keys, re_normed))

    blended: list[tuple[str, float]] = []
    for rank, ((doc_id, _), norm_rrf) in enumerate(zip(rrf_scores, rrf_norm)):
        norm_re = re_norm_map.get(doc_id, 0.0)
        if rank < 3:
            final = 0.75 * norm_rrf + 0.25 * norm_re
        elif rank < 10:
            final = 0.60 * norm_rrf + 0.40 * norm_re
        else:
            final = 0.40 * norm_rrf + 0.60 * norm_re
        blended.append((doc_id, final))
    blended.sort(key=lambda x: x[1], reverse=True)
    return blended[:top_k]
