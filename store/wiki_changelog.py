"""WikiChangeLog audit trail persistence."""
from __future__ import annotations

import time
import uuid
from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class WikiChangeLogStore:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    async def persist_changelog(
        self,
        repository: str,
        trigger: str,
        pages_affected: list[str],
        pages_regenerated: int,
        files_changed: list[str] | None = None,
        errors: list[str] | None = None,
        *,
        heal_refs_removed: int | None = None,
        heal_pages_deprecated: int | None = None,
    ) -> str:
        uid = f"WikiChangeLog:{uuid.uuid4().hex[:12]}"
        cypher = (
            "CREATE (cl:WikiChangeLog {"
            "  uid: $uid, repository: $repo, trigger: $trigger,"
            "  pages_affected: $pages_affected, pages_regenerated: $pages_regen,"
            "  files_changed: $files, errors: $errors,"
            "  heal_refs_removed: $heal_refs, heal_pages_deprecated: $heal_pages,"
            "  timestamp: $ts"
            "})"
        )
        await self._graph.execute_query(cypher, {
            "uid": uid,
            "repo": repository,
            "trigger": trigger,
            "pages_affected": len(pages_affected),
            "pages_regen": pages_regenerated,
            "files": files_changed or [],
            "errors": errors or [],
            "heal_refs": int(heal_refs_removed) if heal_refs_removed is not None else 0,
            "heal_pages": int(heal_pages_deprecated) if heal_pages_deprecated is not None else 0,
            "ts": time.time(),
        })
        return uid

    async def list_changelogs(
        self,
        repository: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        cypher = (
            "MATCH (cl:WikiChangeLog {repository: $repo}) "
            "RETURN cl ORDER BY cl.timestamp DESC LIMIT $limit"
        )
        result = await self._graph.execute_query(cypher, {"repo": repository, "limit": limit})
        rows = getattr(result, "data", []) or []
        return [row if isinstance(row, dict) else {} for row in rows]
