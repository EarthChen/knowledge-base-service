"""Garbage-collect empty WikiSection nodes after tree linking."""
from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)


async def prune_empty_domain_sections(
    wiki_store: Any,
    *,
    business_id: str,
    space_uid: str,
) -> int:
    """Delete WikiSection nodes with section_type='business_domain' that have zero HAS_CHILD edges.

    Skips __root__ section. Returns number of deleted sections.
    """
    # Step 1: Find sections with no outgoing HAS_CHILD edges
    find_q = (
        "MATCH (s:WikiSection) "
        "WHERE s.uid CONTAINS $business_id "
        "AND s.section_type = 'business_domain' "
        "AND NOT s.title = '__root__' "
        "AND NOT (s)-[:HAS_CHILD]->() "
        "RETURN s.uid AS uid, s.title AS title"
    )
    find_result = await wiki_store.execute_query(find_q, {"business_id": business_id})
    rows = getattr(find_result, "data", None) or []
    uids = [str(r["uid"]) for r in rows if r.get("uid")]

    if not uids:
        return 0

    # Step 2: Delete empty sections
    del_q = (
        "UNWIND $uids AS uid "
        "MATCH (s:WikiSection {uid: uid}) "
        "DETACH DELETE s "
        "RETURN count(s) AS deleted"
    )
    del_result = await wiki_store.execute_query(del_q, {"uids": uids})
    del_rows = getattr(del_result, "data", None) or []
    deleted = int(del_rows[0].get("deleted", 0)) if del_rows else 0

    log.info("empty_sections_pruned", business_id=business_id, deleted=deleted, uids=uids)
    return deleted
