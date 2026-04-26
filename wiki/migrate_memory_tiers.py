"""One-shot migration: flat :WikiQA nodes → tiered memory fields."""

from __future__ import annotations

from store.wiki_store import WikiStore


async def migrate_flat_wiki_qa_to_tiered(store: WikiStore, *, business_id: str | None = None) -> int:
    """Set ``tier=1`` (Episodic) and ``access_count=1`` for nodes missing ``tier``."""
    q = """
    MATCH (q:WikiQA)
    WHERE q.tier IS NULL
      AND ($business_id IS NULL OR q.business_id = $business_id)
    SET q.tier = 1,
        q.access_count = coalesce(q.access_count, 1),
        q.memory_status = coalesce(q.memory_status, 'active')
    RETURN count(q) AS updated
    """
    r = await store.execute_query(q, {"business_id": business_id})
    row = (r.data or [{}])[0]
    return int(row.get("updated", 0) or 0)
