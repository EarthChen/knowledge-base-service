"""Wiki-related Cypher queries (search, lint, fusion, routes, graph-enhanced ask)."""

from __future__ import annotations

from typing import Any

from store.wiki_claim_store import WikiClaimStoreMixin
from store.wiki_contradiction_store import WikiContradictionStoreMixin
from store.wiki_coverage_store import WikiCoverageStoreMixin
from store.wiki_memory_store import WikiMemoryStoreMixin
from store.wiki_page_store import WikiPageStoreMixin
from store.wiki_qa_store import WikiQaStoreMixin
from store.wiki_store_common import _GraphQueryPort
from store.wiki_tree_store import WikiTreeStoreMixin


class WikiStore(
    WikiPageStoreMixin,
    WikiTreeStoreMixin,
    WikiCoverageStoreMixin,
    WikiQaStoreMixin,
    WikiMemoryStoreMixin,
    WikiContradictionStoreMixin,
    WikiClaimStoreMixin,
):
    """Wiki-related graph queries — facade over feature mixins."""

    def __init__(self, base_store: _GraphQueryPort) -> None:
        self._store = base_store

    async def get_wiki_generation_version(self, repository: str) -> int | None:
        """Get the last wiki generation version for a repository."""
        result = await self._store.execute_query(
            "MATCH (m:WikiMeta {repository: $repo}) RETURN m.generation_version AS generation_version",
            {"repo": repository},
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            return None
        row = rows[0]
        if isinstance(row, dict):
            raw = row.get("generation_version")
        else:
            raw = row[0] if row else None
        return int(raw) if raw is not None else None

    async def set_wiki_generation_version(self, repository: str, version: int) -> None:
        """Set the wiki generation version for a repository."""
        await self._store.execute_query(
            "MERGE (m:WikiMeta {repository: $repo}) SET m.generation_version = $ver",
            {"repo": repository, "ver": version},
        )

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Delegate Cypher to the underlying graph store (e.g. for MCP EntityExplainer)."""
        return await self._store.execute_query(cypher, params)

    async def list_wiki_pages_for_quality_evaluation(
        self, repository: str,
    ) -> list[dict[str, Any]]:
        """Load wiki page fields needed for documentation quality evaluation."""
        result = await self._store.execute_query(
            "MATCH (wp:WikiPage {repository: $repo}) "
            "RETURN wp.path AS path, wp.title AS title, wp.page_type AS page_type, "
            "coalesce(wp.content, '') AS content, "
            "coalesce(wp.importance_tier, '') AS importance_tier "
            "ORDER BY wp.path",
            {"repo": repository},
        )
        return list(getattr(result, "data", None) or [])

    async def save_quality_scores(self, repository: str, scores: list[Any]) -> int:
        if not scores:
            return 0
        rows = [
            {
                "path": s.page_path,
                "comp": s.completeness,
                "help": s.helpfulness,
                "truth": s.truthfulness,
                "overall": s.overall,
                "issues": ",".join(str(i) for i in s.issues),
            }
            for s in scores
        ]
        result = await self._store.execute_query(
            "UNWIND $rows AS row "
            "MATCH (p:WikiPage {repository: $repo, path: row.path}) "
            "SET p.quality_completeness = row.comp, "
            "    p.quality_helpfulness = row.help, "
            "    p.quality_truthfulness = row.truth, "
            "    p.quality_overall = row.overall, "
            "    p.quality_issues = row.issues "
            "RETURN count(p) AS matched",
            {"repo": repository, "rows": rows},
        )
        matched = 0
        data = getattr(result, "data", None) or []
        if data:
            row = data[0]
            matched = int(row.get("matched", 0) if isinstance(row, dict) else (row[0] or 0))
        return matched

    async def get_quality_summary(self, repository: str, min_score: float = 0.6) -> dict[str, Any]:
        result = await self._store.execute_query(
            "MATCH (p:WikiPage {repository: $repo}) "
            "WHERE p.quality_overall IS NOT NULL "
            "RETURN avg(p.quality_overall) AS avg_score, "
            "       count(p) AS evaluated_count, "
            "       count(CASE WHEN p.quality_overall < $threshold THEN 1 END) AS low_quality_count",
            {"repo": repository, "threshold": min_score},
        )
        rows = getattr(result, "data", None) or []
        if rows and rows[0]:
            row = rows[0]
            if isinstance(row, dict):
                return {
                    "avg_score": round(float(row.get("avg_score", 0) or 0), 3),
                    "evaluated_count": int(row.get("evaluated_count", 0) or 0),
                    "low_quality_count": int(row.get("low_quality_count", 0) or 0),
                }
            return {
                "avg_score": round(float(row[0] or 0), 3),
                "evaluated_count": int(row[1] or 0),
                "low_quality_count": int(row[2] or 0),
            }
        return {"avg_score": 0, "evaluated_count": 0, "low_quality_count": 0}
