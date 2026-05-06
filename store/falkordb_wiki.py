from __future__ import annotations

from typing import Any


class FalkorDBWikiMixin:
    async def persist_wiki_pages(self, repository: str, pages: list[dict[str, Any]]) -> int:
        """MERGE WikiPage nodes from generated wiki output. Returns count of upserted nodes."""
        if not pages:
            return 0
        batch: list[dict[str, Any]] = []
        for page in pages:
            path = page["path"]
            batch.append(
                {
                    "uid": f"WikiPage:{repository}:{path}",
                    "repository": repository,
                    "path": path,
                    "title": page["title"],
                    "content": page["content"],
                    "page_type": page["page_type"],
                    "generated_at": page["generated_at"],
                    "version": page.get("version", 1),
                    "content_hash": page.get("content_hash", ""),
                    "importance_tier": page.get("importance_tier", ""),
                    "enrichment_level": ""
                    if page.get("enrichment_level") is None
                    else str(page.get("enrichment_level")),
                    "repositories": page.get("repositories", [repository]),
                    "confidence_score": page.get("confidence_score"),
                    "source_origin": page.get("source_origin", ""),
                    "navigation_json": page.get("navigation_json") or "",
                    "executive_summary": str(
                        (page.get("metadata") or {}).get("executive_summary", "")
                        or ""
                    ),
                }
            )
        cypher = (
            "UNWIND $batch AS page "
            "MERGE (w:WikiPage {uid: page.uid}) "
            "SET w.repository = page.repository, "
            "w.path = page.path, "
            "w.title = page.title, "
            "w.content = page.content, "
            "w.page_type = page.page_type, "
            "w.generated_at = page.generated_at, "
            "w.version = page.version, "
            "w.content_hash = page.content_hash, "
            "w.importance_tier = page.importance_tier, "
            "w.enrichment_level = page.enrichment_level, "
            "w.repositories = page.repositories, "
            "w.confidence_score = coalesce(page.confidence_score, w.confidence_score), "
            "w.navigation_json = page.navigation_json, "
            "w.executive_summary = page.executive_summary, "
            "w.source_origin = CASE "
            "WHEN page.source_origin IS NULL OR page.source_origin = '' "
            "THEN w.source_origin ELSE page.source_origin END "
            "RETURN count(*) AS cnt"
        )
        result = await self.execute_query(cypher, {"batch": batch})
        if not result.data:
            return len(batch)
        cnt = result.data[0].get("cnt")
        if cnt is None:
            return len(batch)
        return int(cnt)
