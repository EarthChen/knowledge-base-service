"""Memory consolidation tiers (0–3) for wiki Q&A graph nodes.

Age windows for promotion use ``created_at`` (ISO-8601 UTC string), per Phase 3 plan.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any


def _parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class MemoryTier(IntEnum):
    """0=Working, 1=Episodic, 2=Semantic, 3=Procedural."""

    WORKING = 0
    EPISODIC = 1
    SEMANTIC = 2
    PROCEDURAL = 3


@dataclass
class MemoryNode:
    """In-graph memory (persisted as :WikiQA with these fields; see spec MemoryNode)."""

    uid: str
    tier: MemoryTier
    content: str
    entity_name: str
    repository: str
    access_count: int = 0
    confirmation_count: int = 0
    last_accessed: str | None = None
    created_at: str = ""
    promoted_at: str | None = None
    stability_factor: float = 7.0
    confidence: float = 0.0
    status: str = "active"  # active | expired | archived | faded

    @staticmethod
    def from_wiki_qa_row(row: dict[str, Any]) -> MemoryNode:
        """Map a ``search_wiki_qa`` / ``list_wiki_qa`` row to :class:`MemoryNode`.

        Combines ``question`` and ``answer`` into ``content``. Defaults ``tier`` to
        episodic (1) when absent (flat → tiered migration).
        """
        q = str(row.get("question") or "")
        a = str(row.get("answer") or "")
        content = f"{q}\n{a}" if q or a else ""
        raw_tier = row.get("tier")
        if raw_tier is None:
            tier = MemoryTier.EPISODIC
        else:
            try:
                tier = MemoryTier(int(raw_tier))
            except (TypeError, ValueError):
                tier = MemoryTier.EPISODIC
        uid = str(row.get("uid") or "")

        def _opt_str(key: str) -> str | None:
            v = row.get(key)
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        return MemoryNode(
            uid=uid,
            tier=tier,
            content=content,
            entity_name=str(row.get("entity_name") or ""),
            repository=str(row.get("repository") or ""),
            access_count=int(row.get("access_count") or 0),
            confirmation_count=int(row.get("confirmation_count") or 0),
            last_accessed=_opt_str("last_accessed"),
            created_at=str(row.get("created_at") or ""),
            promoted_at=_opt_str("promoted_at"),
            stability_factor=float(row.get("stability_factor") if row.get("stability_factor") is not None else 7.0),
            confidence=float(row.get("confidence") or 0.0),
            status=str(row.get("memory_status") or row.get("status") or "active"),
        )


@dataclass
class MemoryTierManager:
    """Promotion and expiration per design spec (Phase 3)."""

    def apply_promotion_rules(self, node: MemoryNode, *, now: datetime | None = None) -> MemoryNode:
        if now is None:
            now = datetime.now(UTC)
        n = node
        created = _parse_iso(n.created_at) if n.created_at else now
        age = now - created

        if n.tier == MemoryTier.WORKING:
            if age > timedelta(hours=24):
                if n.access_count >= 2:
                    return replace(n, tier=MemoryTier.EPISODIC, promoted_at=_iso_utc(now), status="active")
                return replace(n, status="expired")
        elif n.tier == MemoryTier.EPISODIC:
            if age > timedelta(days=7):
                if n.confirmation_count >= 3:
                    return replace(n, tier=MemoryTier.SEMANTIC, promoted_at=_iso_utc(now), status="active")
                return replace(n, status="expired")
        elif n.tier == MemoryTier.SEMANTIC:
            if n.access_count >= 10 and n.confidence >= 0.8:
                return replace(n, tier=MemoryTier.PROCEDURAL, promoted_at=_iso_utc(now), status="active")
        return n
