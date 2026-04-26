"""Graph persistence for WikiContradiction nodes linked from WikiPage."""

from __future__ import annotations

from typing import Any


class WikiContradictionStoreMixin:
    """CRUD-style helpers for :WikiContradiction. Expects ``self._store`` graph port."""

    async def upsert_wiki_contradiction(
        self,
        uid: str,
        page_uid_a: str,
        page_uid_b: str,
        description: str,
        severity: str,
        *,
        status: str = "detected",
    ) -> None:
        q = (
            "MERGE (c:WikiContradiction {uid: $uid}) "
            "SET c.page_uid_a = $page_uid_a, "
            "c.page_uid_b = $page_uid_b, "
            "c.description = $description, "
            "c.severity = $severity, "
            "c.status = $status, "
            "c.detected_at = coalesce(c.detected_at, timestamp()) "
            "WITH c "
            "MATCH (pa:WikiPage {uid: $page_uid_a}) "
            "MATCH (pb:WikiPage {uid: $page_uid_b}) "
            "MERGE (pa)-[:HAS_CONTRADICTION]->(c) "
            "MERGE (pb)-[:HAS_CONTRADICTION]->(c)"
        )
        await self._store.execute_query(
            q,
            {
                "uid": uid,
                "page_uid_a": page_uid_a,
                "page_uid_b": page_uid_b,
                "description": description,
                "severity": severity,
                "status": status,
            },
        )

    async def list_wiki_contradictions_for_page(
        self,
        page_uid: str,
        *,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        if include_resolved:
            status_filter = ""
        else:
            status_filter = "AND c.status <> 'resolved' "
        q = (
            "MATCH (w:WikiPage {uid: $page_uid})-[:HAS_CONTRADICTION]->(c:WikiContradiction) "
            f"WHERE 1=1 {status_filter}"
            "RETURN c.uid AS uid, c.page_uid_a AS page_uid_a, c.page_uid_b AS page_uid_b, "
            "c.description AS description, c.severity AS severity, c.status AS status, "
            "c.detected_at AS detected_at, c.resolved_at AS resolved_at"
        )
        res = await self._store.execute_query(q, {"page_uid": page_uid})
        return [dict(r) for r in getattr(res, "data", None) or []]

    async def set_wiki_contradiction_status(
        self,
        uid: str,
        status: str,
        *,
        resolved_at: int | None = None,
    ) -> None:
        if resolved_at is not None:
            q = (
                "MATCH (c:WikiContradiction {uid: $uid}) "
                "SET c.status = $status, c.resolved_at = $resolved_at"
            )
            await self._store.execute_query(
                q, {"uid": uid, "status": status, "resolved_at": resolved_at},
            )
        else:
            q = "MATCH (c:WikiContradiction {uid: $uid}) SET c.status = $status"
            await self._store.execute_query(q, {"uid": uid, "status": status})

    async def get_wiki_contradiction(self, uid: str) -> dict[str, Any] | None:
        q = (
            "MATCH (c:WikiContradiction {uid: $uid}) "
            "RETURN c.uid AS uid, c.page_uid_a AS page_uid_a, c.page_uid_b AS page_uid_b, "
            "c.description AS description, c.severity AS severity, c.status AS status, "
            "c.detected_at AS detected_at, c.resolved_at AS resolved_at "
            "LIMIT 1"
        )
        res = await self._store.execute_query(q, {"uid": uid})
        data = getattr(res, "data", None) or []
        if not data:
            return None
        return dict(data[0])
