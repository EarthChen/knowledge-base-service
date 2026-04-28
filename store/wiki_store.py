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
