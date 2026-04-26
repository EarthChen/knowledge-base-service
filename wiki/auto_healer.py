"""Auto-heal actions for wiki quality maintenance."""
from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class AutoHealer:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    async def heal_stale_pages(self, repository: str, max_age_days: int = 30) -> dict[str, Any]:
        cutoff = time.time() - max_age_days * 86400
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE wp.generated_at < $cutoff "
            "SET wp.stale = true "
            "RETURN count(wp) AS cnt"
        )
        result = await self._graph.execute_query(q, {"repo": repository, "cutoff": cutoff})
        rows = getattr(result, "data", []) or []
        cnt = rows[0].get("cnt", 0) if rows and isinstance(rows[0], dict) else 0
        return {"pages_marked": cnt}

    async def remove_broken_references(self, repository: str) -> dict[str, Any]:
        q = (
            "MATCH (wp:WikiPage {repository: $repo})-[r:WIKI_REFERENCES]->(target) "
            "WHERE target IS NULL OR NOT EXISTS(target.uid) "
            "DELETE r RETURN count(r) AS cnt"
        )
        try:
            result = await self._graph.execute_query(q, {"repo": repository})
            rows = getattr(result, "data", []) or []
            cnt = rows[0].get("cnt", 0) if rows and isinstance(rows[0], dict) else 0
        except Exception:
            cnt = 0
        return {"refs_removed": cnt}

    async def deprecate_orphan_pages(self, repository: str) -> dict[str, Any]:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE NOT (wp)-[:SOURCE_ENTITY]->() "
            "SET wp.deprecated = true "
            "RETURN count(wp) AS cnt"
        )
        result = await self._graph.execute_query(q, {"repo": repository})
        rows = getattr(result, "data", []) or []
        cnt = rows[0].get("cnt", 0) if rows and isinstance(rows[0], dict) else 0
        return {"pages_deprecated": cnt}

    async def run_all(self, repository: str) -> dict[str, Any]:
        stale = await self.heal_stale_pages(repository)
        refs = await self.remove_broken_references(repository)
        orphans = await self.deprecate_orphan_pages(repository)
        return {**stale, **refs, **orphans}
