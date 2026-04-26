"""Graph persistence for memory tier fields on :WikiQA nodes."""

from __future__ import annotations

from typing import Any


class WikiMemoryStoreMixin:
    """Update tiering / access metadata for wiki Q&A memory nodes."""

    async def update_wiki_qa_memory(
        self,
        *,
        uid: str,
        tier: int | None = None,
        memory_status: str | None = None,
        promoted_at: str | None = None,
        access_count: int | None = None,
        confirmation_count: int | None = None,
        last_accessed: str | None = None,
        confidence: float | None = None,
    ) -> None:
        """SET provided fields on the WikiQA node identified by ``uid``."""
        sets: list[str] = []
        params: dict[str, Any] = {"uid": uid}
        if tier is not None:
            sets.append("q.tier = $tier")
            params["tier"] = int(tier)
        if memory_status is not None:
            sets.append("q.memory_status = $memory_status")
            params["memory_status"] = memory_status
        if promoted_at is not None:
            sets.append("q.promoted_at = $promoted_at")
            params["promoted_at"] = promoted_at
        if access_count is not None:
            sets.append("q.access_count = $access_count")
            params["access_count"] = int(access_count)
        if confirmation_count is not None:
            sets.append("q.confirmation_count = $confirmation_count")
            params["confirmation_count"] = int(confirmation_count)
        if last_accessed is not None:
            sets.append("q.last_accessed = $last_accessed")
            params["last_accessed"] = last_accessed
        if confidence is not None:
            sets.append("q.confidence = $confidence")
            params["confidence"] = float(confidence)
        if not sets:
            return
        q = f"MATCH (q:WikiQA {{uid: $uid}}) SET {', '.join(sets)}"
        await self._store.execute_query(q, params)

    async def increment_wiki_qa_access(self, *, uid: str, at_iso: str) -> None:
        """Increment ``access_count`` and set ``last_accessed`` (ISO UTC)."""
        cypher = (
            "MATCH (q:WikiQA {uid: $uid}) "
            "SET q.access_count = coalesce(q.access_count, 0) + 1, q.last_accessed = $at_iso"
        )
        await self._store.execute_query(cypher, {"uid": uid, "at_iso": at_iso})


__all__ = ["WikiMemoryStoreMixin"]
