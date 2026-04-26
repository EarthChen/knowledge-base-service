"""Wiki-related Cypher queries (search, lint, fusion, routes, graph-enhanced ask)."""

from __future__ import annotations

from typing import Any

from store.wiki_contradiction_store import WikiContradictionStoreMixin
from store.wiki_coverage_store import WikiCoverageStoreMixin
from store.wiki_page_store import WikiPageStoreMixin
from store.wiki_qa_store import WikiQaStoreMixin
from store.wiki_store_common import _GraphQueryPort
from store.wiki_tree_store import WikiTreeStoreMixin


class WikiStore(
    WikiPageStoreMixin,
    WikiTreeStoreMixin,
    WikiCoverageStoreMixin,
    WikiQaStoreMixin,
    WikiContradictionStoreMixin,
):
    """Wiki-related graph queries — facade over feature mixins."""

    def __init__(self, base_store: _GraphQueryPort) -> None:
        self._store = base_store

    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Delegate Cypher to the underlying graph store (e.g. for MCP EntityExplainer)."""
        return await self._store.execute_query(cypher, params)
