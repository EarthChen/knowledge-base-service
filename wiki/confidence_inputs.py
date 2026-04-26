"""Graph-backed inputs for :class:`wiki.confidence_scorer.ConfidenceScorer`."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from store.schema import EdgeType
from store.wiki_feedback_store import WikiFeedbackStore
from store.wiki_store import WikiStore
from wiki.confidence_scorer import ConfidenceInputs, ConfidenceScorer


@runtime_checkable
class _GraphQueryPort(Protocol):
    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any: ...


def days_since_generated(generated_at_iso: str) -> int:
    """Day delta from a wiki ``generated_at`` string to now (non-negative)."""
    if not generated_at_iso or not str(generated_at_iso).strip():
        return 90
    s = str(generated_at_iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0, int(delta.total_seconds() // 86400))
    except (ValueError, OSError, TypeError):
        return 90


def _count_from_query(result: Any, key: str = "cnt") -> int:
    rows = getattr(result, "data", None) or []
    if not rows or not isinstance(rows[0], dict):
        return 0
    raw = rows[0].get(key)
    if raw is None:
        return 0
    try:
        c = int(raw)
    except (TypeError, ValueError):
        if isinstance(raw, float) and not math.isnan(raw):
            c = int(raw)
        else:
            c = 0
    return max(0, c)


async def gather_confidence_inputs(
    store: _GraphQueryPort,
    page_uid: str,
    repository: str,
    generated_at_iso: str,
    *,
    business_id: str = "default",
) -> ConfidenceInputs:
    """Build inputs from the graph and feedback (call after the WikiPage node exists)."""
    se = EdgeType.SOURCE_ENTITY.value
    q_src = (
        f"MATCH (w:WikiPage {{uid: $uid}}) "
        f"OPTIONAL MATCH (w)-[:{se}]->(e) "
        "RETURN count(e) AS cnt"
    )
    src_r = await store.execute_query(q_src, {"uid": page_uid})
    source_n = _count_from_query(src_r, "cnt")

    q_in = (
        "MATCH (src:WikiPage {repository: $repo})-[:WIKILINK]->(w:WikiPage {uid: $uid}) "
        "RETURN count(DISTINCT src) AS cnt"
    )
    in_r = await store.execute_query(q_in, {"repo": repository, "uid": page_uid})
    inbound = _count_from_query(in_r, "cnt")

    q_con = (
        "MATCH (w:WikiPage {uid: $uid}) "
        "MATCH (w)-[:HAS_CONTRADICTION]->(c) "
        "WHERE coalesce(c.status, '') <> 'resolved' "
        "RETURN count(c) AS cnt"
    )
    con_r = await store.execute_query(q_con, {"uid": page_uid})
    contradictions = _count_from_query(con_r, "cnt")

    fb = WikiFeedbackStore(store)
    summary = await fb.get_feedback_summary(page_uid, business_id)
    up = int(summary.get("up") or 0)
    down = int(summary.get("down") or 0)
    days = days_since_generated(generated_at_iso)

    return ConfidenceInputs(
        source_entity_count=source_n,
        days_since_generated=days,
        up_votes=up,
        down_votes=down,
        inbound_wikilink_count=inbound,
        contradiction_count=contradictions,
    )


async def set_wiki_page_confidence_scores(
    store: _GraphQueryPort,
    path_scores: list[tuple[str, float]],
    *,
    repository: str,
) -> None:
    """UNWIND batch SET ``confidence_score`` on WikiPage nodes (uid = WikiPage:repo:path)."""
    if not path_scores:
        return
    batch = [
        {
            "uid": f"WikiPage:{repository}:{path}",
            "score": float(score),
        }
        for path, score in path_scores
    ]
    q = (
        "UNWIND $batch AS row "
        "MATCH (w:WikiPage {uid: row.uid}) "
        "SET w.confidence_score = row.score"
    )
    await store.execute_query(q, {"batch": batch})


async def recalculate_confidence_scores_for_repo(
    store: _GraphQueryPort,
    repository: str,
    *,
    wiki_store: WikiStore,
    scorer: ConfidenceScorer,
    business_id: str = "default",
) -> int:
    """Recompute and persist confidence for every ``WikiPage`` in ``repository``."""
    rows = await wiki_store.list_wiki_pages_for_repo(repository)
    data = getattr(rows, "data", None) or []
    path_scores: list[tuple[str, float]] = []
    for r in data:
        path = str(r.get("path", "") or "")
        if not path:
            continue
        uid = f"WikiPage:{repository}:{path}"
        gen_at = str(r.get("generated_at", "") or "")
        inputs = await gather_confidence_inputs(
            store, uid, repository, gen_at, business_id=business_id,
        )
        path_scores.append((path, scorer.compute(inputs)))
    await set_wiki_page_confidence_scores(store, path_scores, repository=repository)
    return len(path_scores)
