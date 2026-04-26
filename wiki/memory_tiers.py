"""Memory consolidation tiers (0–3) for wiki Q&A graph nodes.

Age windows for promotion use ``created_at`` (ISO-8601 UTC string), per Phase 3 plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


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
        return MemoryNode(
            uid=uid,
            tier=tier,
            content=content,
            entity_name=str(row.get("entity_name") or ""),
            repository=str(row.get("repository") or ""),
            access_count=int(row.get("access_count") or 0),
            confirmation_count=int(row.get("confirmation_count") or 0),
            last_accessed=row.get("last_accessed") if row.get("last_accessed") is not None else None,
            created_at=str(row.get("created_at") or ""),
            promoted_at=row.get("promoted_at") if row.get("promoted_at") is not None else None,
            stability_factor=float(row.get("stability_factor") or 7.0),
            confidence=float(row.get("confidence") or 0.0),
            status=str(row.get("memory_status") or row.get("status") or "active"),
        )
