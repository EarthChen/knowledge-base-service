"""Wiki-related Cypher queries (search, lint, fusion, routes, graph-enhanced ask)."""

from __future__ import annotations

from store.wiki_coverage_store import WikiCoverageStoreMixin
from store.wiki_page_store import WikiPageStoreMixin
from store.wiki_qa_store import WikiQaStoreMixin
from store.wiki_store_common import _GraphQueryPort
from store.wiki_tree_store import WikiTreeStoreMixin


class WikiStore(
    WikiPageStoreMixin, WikiTreeStoreMixin, WikiCoverageStoreMixin, WikiQaStoreMixin,
):
    """Wiki-related graph queries — facade over feature mixins."""

    def __init__(self, base_store: _GraphQueryPort) -> None:
        self._store = base_store
