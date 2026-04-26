"""Graph persistence for WikiClaimHistory and page-level supersedes metadata."""

from __future__ import annotations

from typing import Any


class WikiClaimStoreMixin:
    """WikiClaimHistory nodes under WikiPage. Expects ``self._store`` graph port."""

    async def create_wiki_claim_history(
        self,
        uid: str,
        page_uid: str,
        claim_text: str,
        version: int,
        *,
        superseded_by: str | None = None,
        created_at: int,
        superseded_at: int | None = None,
    ) -> None:
        q = (
            "MERGE (h:WikiClaimHistory {uid: $uid}) "
            "SET h.page_uid = $page_uid, "
            "h.claim_text = $claim_text, "
            "h.version = $version, "
            "h.superseded_by = $superseded_by, "
            "h.created_at = $created_at, "
            "h.superseded_at = $superseded_at "
            "WITH h "
            "MATCH (p:WikiPage {uid: $page_uid}) "
            "MERGE (p)-[:HAS_CLAIM]->(h)"
        )
        await self._store.execute_query(
            q,
            {
                "uid": uid,
                "page_uid": page_uid,
                "claim_text": claim_text,
                "version": version,
                "superseded_by": superseded_by,
                "created_at": created_at,
                "superseded_at": superseded_at,
            },
        )

    async def set_wiki_claim_superseded(
        self,
        claim_uid: str,
        superseded_by: str,
        superseded_at: int,
    ) -> None:
        q = (
            "MATCH (h:WikiClaimHistory {uid: $uid}) "
            "SET h.superseded_by = $by, h.superseded_at = $at"
        )
        await self._store.execute_query(
            q,
            {"uid": claim_uid, "by": superseded_by, "at": superseded_at},
        )

    async def list_wiki_claims_for_page(self, page_uid: str) -> list[dict[str, Any]]:
        q = (
            "MATCH (p:WikiPage {uid: $page_uid})-[:HAS_CLAIM]->(h:WikiClaimHistory) "
            "RETURN h.uid AS uid, h.claim_text AS claim_text, h.version AS version, "
            "h.superseded_by AS superseded_by, h.created_at AS created_at, "
            "h.superseded_at AS superseded_at "
            "ORDER BY h.created_at ASC"
        )
        res = await self._store.execute_query(q, {"page_uid": page_uid})
        return [dict(r) for r in getattr(res, "data", None) or []]

    async def set_wiki_page_supersedes(self, page_uid: str, supersedes_json: str) -> None:
        q = "MATCH (p:WikiPage {uid: $uid}) SET p.supersedes = $json"
        await self._store.execute_query(q, {"uid": page_uid, "json": supersedes_json})

    async def find_wiki_claim_by_text(
        self,
        page_uid: str,
        claim_text: str,
    ) -> str | None:
        text = claim_text.strip()
        q = (
            "MATCH (p:WikiPage {uid: $page_uid})-[:HAS_CLAIM]->(h:WikiClaimHistory) "
            "WHERE trim(h.claim_text) = $text AND h.superseded_by IS NULL "
            "RETURN h.uid AS uid LIMIT 1"
        )
        res = await self._store.execute_query(
            q,
            {"page_uid": page_uid, "text": text},
        )
        rows = getattr(res, "data", None) or []
        if not rows:
            return None
        u = rows[0].get("uid")
        return str(u) if u else None

    async def find_or_create_wiki_claim(
        self,
        page_uid: str,
        claim_text: str,
        version: int,
        *,
        new_claim_uid: str,
        created_at: int,
    ) -> str:
        """Return an existing active claim uid when text matches, else create and return new uid."""
        text = claim_text.strip()
        existing = await self.find_wiki_claim_by_text(page_uid, text)
        if existing:
            return existing
        await self.create_wiki_claim_history(
            new_claim_uid,
            page_uid,
            text,
            version,
            superseded_by=None,
            created_at=created_at,
            superseded_at=None,
        )
        return new_claim_uid

    async def next_claim_version(self, page_uid: str) -> int:
        q = (
            "MATCH (p:WikiPage {uid: $uid})-[:HAS_CLAIM]->(h:WikiClaimHistory) "
            "RETURN coalesce(max(h.version), 0) AS m"
        )
        res = await self._store.execute_query(q, {"uid": page_uid})
        rows = getattr(res, "data", None) or []
        if not rows:
            return 1
        return int(rows[0].get("m") or 0) + 1
