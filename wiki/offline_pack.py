"""Build an offline JSON package of wiki content for a repository."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.log import get_logger

log = get_logger(__name__)


_MAX_OFFLINE_PAGES = 2000
_SCHEMA_VERSION = "1.0"


class WikiOfflinePack:
    def __init__(self, store: Any) -> None:
        self._store = store

    async def build(self, repository: str, business_id: str) -> dict[str, Any]:
        """Build a complete offline package with pages, tree, and metadata."""
        pages = await self._fetch_pages(repository)
        truncated = len(pages) > _MAX_OFFLINE_PAGES
        if truncated:
            pages = pages[:_MAX_OFFLINE_PAGES]
        tree = await self._fetch_tree(repository)

        snapshot_content = None
        try:
            snapshot_q = (
                "MATCH (wp:WikiPage {repository: $repo, path: 'wiki_snapshot.md'}) "
                "RETURN wp.content AS content"
            )
            r = await self._store.execute_query(snapshot_q, {"repo": repository})
            rows = getattr(r, "data", None) or []
            if rows and isinstance(rows[0], dict):
                snapshot_content = rows[0].get("content")
        except Exception:
            log.warning("offline_pack_snapshot_fetch_failed", repository=repository, exc_info=True)

        now = datetime.now(UTC)
        result: dict[str, Any] = {
            "repository": repository,
            "business_id": business_id,
            "schema_version": _SCHEMA_VERSION,
            "built_at": now.isoformat(),
            "generated_at": now.isoformat(),
            "page_count": len(pages),
            "pages": pages,
            "tree": tree,
            "wiki_snapshot": snapshot_content,
        }
        if truncated:
            result["truncated"] = True
            result["max_pages"] = _MAX_OFFLINE_PAGES
        return result

    async def _fetch_pages(self, repository: str) -> list[dict[str, Any]]:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE coalesce(wp.deprecated, false) = false "
            "AND coalesce(wp.page_type, '') <> 'snapshot' "
            "RETURN wp.path AS path, wp.title AS title, wp.content AS content, "
            "coalesce(wp.page_type, '') AS page_type, "
            "coalesce(wp.importance_tier, 'standard') AS importance_tier, "
            "coalesce(wp.confidence, null) AS confidence "
            "ORDER BY wp.path"
        )
        r = await self._store.execute_query(q, {"repo": repository})
        rows = getattr(r, "data", None) or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    async def _fetch_tree(self, repository: str) -> list[dict[str, Any]]:
        q = (
            "MATCH (ws:WikiSpace)-[:HAS_CHILD*1..10]->(wp:WikiPage {repository: $repo}) "
            "WHERE coalesce(wp.deprecated, false) = false "
            "RETURN wp.path AS path, wp.title AS title, "
            "coalesce(wp.page_type, '') AS page_type, "
            "coalesce(wp.importance_tier, 'standard') AS importance_tier "
            "ORDER BY wp.path"
        )
        try:
            r = await self._store.execute_query(q, {"repo": repository})
            return [dict(row) for row in (getattr(r, "data", None) or []) if isinstance(row, dict)]
        except Exception:
            log.warning("offline_pack_tree_fetch_failed", repository=repository, exc_info=True)
            return []
