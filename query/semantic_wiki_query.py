"""Multi-strategy wiki + code graph semantic search (fulltext, graph paths, entities, call chains).

v1 merges results from multiple strategies via simple deduplication and score-based
sorting.  A full Reciprocal Rank Fusion (RRF) approach is planned for v2 once we
have relevance-feedback data to tune the weights.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from wiki.search import _extract_entity_names

log = logging.getLogger(__name__)


@dataclass
class WikiSearchHit:
    page_path: str
    title: str
    snippet: str
    score: float
    source: str  # "wiki_fulltext" | "wiki_graph" | "entity_match"


@dataclass
class EntitySearchHit:
    name: str
    entity_type: str
    repository: str
    file_path: str
    summary: str
    score: float


@dataclass
class CallChainHit:
    caller: str
    callee: str
    relationship: str


@dataclass
class SemanticSearchResult:
    wiki_hits: list[WikiSearchHit] = field(default_factory=list)
    entity_hits: list[EntitySearchHit] = field(default_factory=list)
    call_chain_hits: list[CallChainHit] = field(default_factory=list)
    # Sum of all hit lists; not deduplicated across strategies.
    total_count: int = 0


def semantic_search_result_to_dict(result: SemanticSearchResult) -> dict[str, Any]:
    return {
        "wiki_hits": [asdict(h) for h in result.wiki_hits],
        "entity_hits": [asdict(h) for h in result.entity_hits],
        "call_chain_hits": [asdict(h) for h in result.call_chain_hits],
        "total_count": result.total_count,
    }


def _entity_labels_to_type(labels: object) -> str:
    if labels is None:
        return ""
    labs: list[str]
    if isinstance(labels, (list, tuple)):
        labs = [str(x) for x in labels]
    else:
        labs = [str(labels)]
    for prefer in ("Function", "Class", "Module"):
        if prefer in labs:
            return prefer
    return labs[0] if labs else ""


def _wiki_search_terms(query: str, *, cap: int = 8) -> list[str]:
    terms = _extract_entity_names(query)
    if not terms:
        terms = [t for t in re.split(r"\W+", query) if len(t) > 2][:cap]
    return terms


class SemanticWikiQuery:
    """Combines multiple search strategies for comprehensive wiki search.

    Search strategies:
    1. Wiki vector search (preferred, supports CJK)
    2. Wiki fulltext search (fallback for keyword matching)
    3. Graph path search
    4. Code entity name matching
    5. Call chain traversal
    """

    def __init__(
        self,
        wiki_store: Any,
        graph_store: Any | None = None,
        embedding_generator: Any | None = None,
    ) -> None:
        self._wiki = wiki_store
        self._graph = graph_store
        self._emb_gen = embedding_generator

    async def search(
        self,
        query: str,
        repository: str,
        *,
        limit: int = 20,
    ) -> SemanticSearchResult:
        """Execute multi-strategy search and merge results."""
        text = (query or "").strip()
        if not text:
            return SemanticSearchResult(total_count=0)

        cap = max(limit, 1)
        if self._graph is not None:
            wiki_hits, entity_hits = await asyncio.gather(
                self._search_wiki_pages(text, repository, cap),
                self._search_code_entities(text, repository, cap),
            )
        else:
            wiki_hits = await self._search_wiki_pages(text, repository, cap)
            entity_hits = []

        call_chain_hits: list[CallChainHit] = []
        if self._graph is not None:
            names = [h.name for h in entity_hits if h.name]
            if not names:
                names = _extract_entity_names(text)[:cap]
            if names:
                call_chain_hits = await self._search_call_chains(names, cap)

        total = len(wiki_hits) + len(entity_hits) + len(call_chain_hits)
        return SemanticSearchResult(
            wiki_hits=wiki_hits,
            entity_hits=entity_hits,
            call_chain_hits=call_chain_hits,
            total_count=total,
        )

    async def _search_wiki_pages(self, query: str, repository: str, limit: int) -> list[WikiSearchHit]:
        """Vector + fulltext wiki page search + graph-linked wiki pages."""
        coros = [
            self._wiki_vector_hits(query, repository, limit),
            self._wiki_fulltext_hits(query, repository, limit),
            self._wiki_graph_path_hits(query, repository, limit),
        ]
        vec_hits, fts_hits, graph_hits = await asyncio.gather(*coros)
        merged_text = _merge_wiki_hits(fts_hits, graph_hits, limit * 2)
        return _merge_wiki_hits(vec_hits, merged_text, limit)

    async def _wiki_vector_hits(
        self, query: str, repository: str, limit: int,
    ) -> list[WikiSearchHit]:
        if self._emb_gen is None:
            log.warning("wiki_vector_search_skipped reason=%s", "no_embedding_generator")
            return []
        try:
            vecs = await self._emb_gen.generate_for_query([query])
            if not vecs or not vecs[0]:
                return []
            res = await self._wiki.vector_wiki_search(
                k=max(limit * 3, 30),
                vec=vecs[0],
                repository=repository,
                limit=max(limit * 3, limit),
            )
        except Exception:  # noqa: BLE001
            log.warning("wiki_vector_search_failed", exc_info=True)
            return []
        rows = getattr(res, "data", None) or []
        hits: list[WikiSearchHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            node = row.get("node")
            props = getattr(node, "properties", None) or {}
            if not isinstance(props, dict):
                props = {}
            pid = props.get("path") or props.get("page_path")
            if not pid:
                continue
            title = str(props.get("title", "") or "")
            content = str(props.get("content", "") or "")
            snippet = content[:240]
            score = float(row.get("score", 0.0) or 0.0)
            hits.append(
                WikiSearchHit(
                    page_path=str(pid),
                    title=title,
                    snippet=snippet,
                    score=score,
                    source="wiki_vector",
                ),
            )
        return hits

    async def _wiki_fulltext_hits(
        self, query: str, repository: str, limit: int,
    ) -> list[WikiSearchHit]:
        try:
            res = await self._wiki.fulltext_wiki_search(
                query.replace("\n", " "),
                repository,
                max(limit * 5, limit),
            )
        except Exception:  # noqa: BLE001
            log.warning("wiki_fulltext_search_failed", exc_info=True)
            return []
        rows = getattr(res, "data", None) or []
        hits: list[WikiSearchHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            node = row.get("node")
            props = getattr(node, "properties", None) or {}
            if not isinstance(props, dict):
                props = {}
            pid = props.get("path") or props.get("page_path")
            if not pid:
                continue
            title = str(props.get("title", "") or "")
            content = str(props.get("content", "") or "")
            snippet = content[:240]
            score = float(row.get("score", 0.0) or 0.0)
            hits.append(
                WikiSearchHit(
                    page_path=str(pid),
                    title=title,
                    snippet=snippet,
                    score=score,
                    source="wiki_fulltext",
                ),
            )
        return hits

    async def _wiki_graph_path_hits(
        self, query: str, repository: str, limit: int,
    ) -> list[WikiSearchHit]:
        terms = _wiki_search_terms(query)
        if not terms:
            return []
        try:
            res = await self._wiki.graph_path_search(
                repository,
                terms,
                max(limit * 5, limit),
            )
        except Exception:  # noqa: BLE001
            log.warning("wiki_graph_path_search_failed", exc_info=True)
            return []
        rows = getattr(res, "data", None) or []
        hits: list[WikiSearchHit] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            pid = row.get("page_path") or row.get("path")
            if not pid:
                continue
            title = str(row.get("title", "") or "")
            snippet = str(row.get("snippet", "") or "")
            base = 0.72
            score = base * (1.0 - min(i, limit * 5) / max(limit * 5, 1))
            hits.append(
                WikiSearchHit(
                    page_path=str(pid),
                    title=title,
                    snippet=snippet[:240],
                    score=score,
                    source="wiki_graph",
                ),
            )
        return hits

    async def _search_code_entities(self, query: str, repository: str, limit: int) -> list[EntitySearchHit]:
        if self._graph is None:
            return []
        q = (
            "MATCH (e) WHERE (e:Function OR e:Class OR e:Module) "
            "AND e.repository = $repository "
            "AND (e.name CONTAINS $query OR e.business_summary CONTAINS $query) "
            "RETURN e.name AS name, labels(e) AS labels, "
            "coalesce(e.file, '') AS file_path, "
            "coalesce(e.business_summary, e.docstring, '') AS summary, "
            "coalesce(e.repository, '') AS repository "
            "LIMIT $limit"
        )
        try:
            res = await self._graph.execute_query(
                q,
                {"repository": repository, "query": query, "limit": limit},
            )
        except Exception:  # noqa: BLE001
            log.warning("code_entity_search_failed", exc_info=True)
            return []
        rows = getattr(res, "data", None) or []
        hits: list[EntitySearchHit] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if not name:
                continue
            et = _entity_labels_to_type(row.get("labels"))
            score = max(0.55, 0.92 - i * 0.02)
            hits.append(
                EntitySearchHit(
                    name=name,
                    entity_type=et,
                    repository=str(row.get("repository") or repository),
                    file_path=str(row.get("file_path") or ""),
                    summary=str(row.get("summary") or ""),
                    score=score,
                ),
            )
        return hits

    async def _search_call_chains(self, entity_names: list[str], limit: int) -> list[CallChainHit]:
        if self._graph is None or not entity_names:
            return []
        q = (
            "MATCH (n) "
            "WHERE n.name IN $entity_names AND (n:Function OR n:Class OR n:Module) "
            "MATCH (n)-[r:CALLS]->(m) "
            "RETURN coalesce(n.name, '') AS caller, coalesce(m.name, '') AS callee, type(r) AS relationship "
            "LIMIT $limit"
        )
        try:
            res = await self._graph.execute_query(
                q,
                {"entity_names": list(dict.fromkeys(entity_names))[:50], "limit": limit},
            )
        except Exception:  # noqa: BLE001
            log.warning("call_chain_search_failed", exc_info=True)
            return []
        rows = getattr(res, "data", None) or []
        hits: list[CallChainHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            caller = str(row.get("caller") or "")
            callee = str(row.get("callee") or "")
            if not caller or not callee:
                continue
            hits.append(
                CallChainHit(
                    caller=caller,
                    callee=callee,
                    relationship=str(row.get("relationship") or "CALLS"),
                ),
            )
        return hits


def _merge_wiki_hits(
    fulltext: list[WikiSearchHit],
    graph: list[WikiSearchHit],
    limit: int,
) -> list[WikiSearchHit]:
    by_path: dict[str, WikiSearchHit] = {}
    for h in fulltext:
        by_path[h.page_path] = h
    for h in graph:
        prev = by_path.get(h.page_path)
        if prev is None:
            by_path[h.page_path] = h
        elif h.score > prev.score:
            by_path[h.page_path] = h
        elif h.score == prev.score and prev.source != "wiki_fulltext":
            by_path[h.page_path] = h
    merged = sorted(by_path.values(), key=lambda x: x.score, reverse=True)
    return merged[:limit]
