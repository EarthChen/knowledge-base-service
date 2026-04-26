"""Coverage, knowledge gaps, and stale-page analytics."""

from __future__ import annotations

from typing import Any

from store.schema import EdgeType
class WikiCoverageStoreMixin:
    """Coverage-related Cypher."""

    async def get_entity_coverage_stats(self, business_id: str) -> dict[str, int]:
        """Count wiki pages by importance tier for :class:`wiki.coverage_analyzer.WikiCoverageAnalyzer`.

        Keys align with :class:`wiki.coverage_analyzer.CoverageReport` / the analyzer's ``stats.get(...)`` usage:
        - ``total_entities`` — all :WikiPage nodes (denominator for tier ratios in the analyzer)
        - ``covered_entities`` — pages at core or standard tier (non-skeleton)
        - ``core_total`` / ``standard_total`` / ``skeleton_total`` — per-tier counts
        """
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
            "RETURN wp.importance_tier AS tier, count(wp) AS cnt"
        )
        result = await self._store.execute_query(q, {"business_id": business_id})
        core = 0
        standard = 0
        skeleton = 0
        for row in result.data:
            tier = str(row.get("tier") or "")
            cnt = int(row.get("cnt", 0))
            if tier == "core":
                core += cnt
            elif tier == "standard":
                standard += cnt
            else:
                skeleton += cnt
        total = core + standard + skeleton
        return {
            "total_entities": total,
            "covered_entities": core + standard,
            "core_total": core,
            "standard_total": standard,
            "skeleton_total": skeleton,
        }

    async def get_knowledge_gaps(
        self, business_id: str, min_in_degree: int = 5
    ) -> list[dict[str, Any]]:
        """Find entities with high in-degree but weak/missing wiki documentation."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})"
            f"-[:HAS_CHILD*1..10]->(wp:WikiPage)-[:{_se}]->(e) "
            "WHERE wp.importance_tier = 'skeleton' OR wp.importance_tier IS NULL "
            "OPTIONAL MATCH (caller)-[:CALLS]->(e) "
            "WITH e.name AS entity_name, wp.importance_tier AS wiki_tier, "
            "count(DISTINCT caller) AS in_degree "
            "WHERE in_degree >= $min_in_degree "
            "RETURN entity_name, in_degree, wiki_tier "
            "ORDER BY in_degree DESC"
        )
        result = await self._store.execute_query(
            q, {"business_id": business_id, "min_in_degree": min_in_degree}
        )
        return [
            {
                "entity_name": str(r.get("entity_name") or ""),
                "in_degree": int(r.get("in_degree", 0)),
                "wiki_tier": r.get("wiki_tier"),
            }
            for r in result.data
        ]

    async def get_stale_wiki_pages(self, business_id: str) -> list[dict[str, Any]]:
        """Find wiki pages whose source entities have been updated since generation."""
        _se = EdgeType.SOURCE_ENTITY.value
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})"
            f"-[:HAS_CHILD*1..10]->(wp:WikiPage)-[:{_se}]->(e) "
            "WHERE e.commit_sha IS NOT NULL AND wp.content_hash IS NOT NULL "
            "AND e.indexed_at > wp.generated_at "
            "RETURN wp.path AS page_path, wp.title AS page_title, "
            "e.commit_sha AS entity_commit, wp.generated_at AS page_generated_at "
            "ORDER BY wp.path"
        )
        result = await self._store.execute_query(q, {"business_id": business_id})
        return [
            {
                "page_path": str(r.get("page_path") or ""),
                "page_title": str(r.get("page_title") or ""),
                "entity_commit": str(r.get("entity_commit") or ""),
                "page_generated_at": str(r.get("page_generated_at") or ""),
            }
            for r in result.data
        ]

    async def get_wiki_reference_and_enrichment_stats(self, business_id: str) -> dict[str, int]:
        """Counts for quality score: WIKI_REFERENCES among business pages, and enriched wiki pages.

        *enriched* — ``enrichment_level`` is non-empty (async enrichment / depth proxy).
        """
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(s:WikiPage) "
            "MATCH (s)-[r:WIKI_REFERENCES]->(t:WikiPage) "
            "MATCH (ws)-[:HAS_CHILD*1..10]->(t) "
            "RETURN count(r) AS ref_count"
        )
        r1 = await self._store.execute_query(q, {"business_id": business_id})
        ref_count = 0
        if r1.data:
            ref_count = int(r1.data[0].get("ref_count", 0) or 0)

        q2 = (
            "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
            "WITH count(wp) AS total, "
            "sum(CASE WHEN coalesce(wp.enrichment_level, '') <> '' THEN 1 ELSE 0 END) AS enriched "
            "RETURN total, enriched"
        )
        r2 = await self._store.execute_query(q2, {"business_id": business_id})
        total = 0
        enriched = 0
        if r2.data:
            total = int(r2.data[0].get("total", 0) or 0)
            enriched = int(r2.data[0].get("enriched", 0) or 0)

        return {"ref_edge_count": ref_count, "total_pages": total, "enriched_pages": enriched}
