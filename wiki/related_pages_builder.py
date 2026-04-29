"""Build cross-page references based on graph proximity, domain co-membership, and structural siblings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from log import get_logger

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


@dataclass
class RelatedPageInfo:
    entity_uid: str
    title: str
    relevance_score: float
    strategy: str


class RelatedPagesBuilder:
    MAX_RELATED = 10

    _GRAPH_WEIGHT = 1.0
    _DOMAIN_WEIGHT = 0.6
    _SIBLING_WEIGHT = 0.4

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def build(
        self,
        entity_uid: str,
        business_domain: str | None = None,
    ) -> list[RelatedPageInfo]:
        candidates: dict[str, float] = {}
        strategies: dict[str, str] = {}

        try:
            graph_neighbors = await self._store.find_related_entities(
                entity_uid, edge_types=["CALLS", "IMPORTS", "INHERITS"], max_hops=1,
            )
            for uid, etype in graph_neighbors:
                candidates[uid] = candidates.get(uid, 0) + self._GRAPH_WEIGHT
                strategies.setdefault(uid, f"graph:{etype}")
        except Exception:
            log.debug("related_pages_graph_lookup_failed", uid=entity_uid, exc_info=True)

        if business_domain:
            try:
                domain_siblings = await self._store.find_entities_by_domain(
                    business_domain, exclude_uid=entity_uid,
                )
                for uid in domain_siblings:
                    candidates[uid] = candidates.get(uid, 0) + self._DOMAIN_WEIGHT
                    strategies.setdefault(uid, "domain")
            except Exception:
                log.debug("related_pages_domain_lookup_failed", uid=entity_uid, exc_info=True)

        try:
            structural_siblings = await self._store.find_siblings(entity_uid)
            for uid in structural_siblings:
                candidates[uid] = candidates.get(uid, 0) + self._SIBLING_WEIGHT
                strategies.setdefault(uid, "sibling")
        except Exception:
            log.debug("related_pages_sibling_lookup_failed", uid=entity_uid, exc_info=True)

        ranked = sorted(candidates.items(), key=lambda x: -x[1])[:self.MAX_RELATED]

        results: list[RelatedPageInfo] = []
        for uid, score in ranked:
            results.append(RelatedPageInfo(
                entity_uid=uid,
                title=uid.split("/")[-1] if "/" in uid else uid,
                relevance_score=round(score, 2),
                strategy=strategies.get(uid, "unknown"),
            ))

        return results
