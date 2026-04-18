"""Wiki hybrid search: graph + vector + FTS with RRF fusion."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)

# Graph path ×2, vector ×1, FTS ×1.5 (hybrid)
_WEIGHT_GRAPH = 2.0
_WEIGHT_VECTOR = 1.0
_WEIGHT_FTS = 1.5

_PASCAL = re.compile(r"\b(?:[A-Z][a-z0-9]+){2,}\b")
_DOTTED = re.compile(r"\b[a-z][a-z0-9]*(?:\.[A-Za-z_][\w]*)+\b")


@dataclass
class SearchResult:
    page_path: str
    title: str
    score: float
    snippet: str
    source_locations: list[dict[str, Any]]
    context: dict[str, str]


@dataclass
class SearchResponse:
    results: list[SearchResult]
    query_expansion: dict[str, Any]
    total: int


@runtime_checkable
class GraphSearchPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


@runtime_checkable
class VectorSearchPort(Protocol):
    async def search_all(self, query_text: str, k: int = 10) -> list[dict]: ...


@runtime_checkable
class FTSPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


def _extract_entity_names(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for pattern in (_PASCAL, _DOTTED):
        for m in pattern.finditer(text):
            val = m.group(0)
            if val not in seen:
                seen.add(val)
                out.append(val)
    return out


def _neighbor_cypher() -> str:
    return (
        "MATCH (n)-[:CALLS|INHERITS|IMPORTS]->(m) "
        "WHERE n.name = $name "
        "RETURN DISTINCT m.name AS neighbor LIMIT 5"
    )


def _graph_path_cypher() -> str:
    return (
        "UNWIND $terms AS term "
        "MATCH (seed)-[:CALLS|INHERITS|IMPORTS*1..3]-(related) "
        "WHERE (seed:Function OR seed:Class OR seed:Module) "
        "AND (seed.name = term OR seed.fqn = term OR seed.fqn ENDS WITH term) "
        "MATCH (wp:WikiPage) "
        "WHERE wp.repository = $repository "
        "AND (wp.title CONTAINS related.name OR wp.content CONTAINS related.name) "
        "RETURN DISTINCT wp.path AS page_path, wp.title AS title, "
        "left(wp.content, 240) AS snippet "
        "LIMIT $limit"
    )


def _fts_cypher() -> str:
    return (
        "CALL db.idx.fulltext.queryNodes('WikiPage', $text) YIELD node, score "
        "RETURN node, score LIMIT $limit"
    )


class WikiSearchService:
    """3-path fusion wiki search with optional graph query expansion."""

    def __init__(self, graph: GraphSearchPort, vector: VectorSearchPort, fts: FTSPort) -> None:
        self._graph = graph
        self._vector = vector
        self._fts = fts

    async def ensure_fulltext_index(self) -> None:
        """Create FalkorDB full-text index on WikiPage content and title."""
        await self._fts.execute_query(
            "CALL db.idx.fulltext.createNodeIndex('WikiPage', 'content', 'title')"
        )

    @staticmethod
    def rrf_fusion(
        ranked_lists: list[list[tuple[str, float]]],
        weights: list[float],
        k: int = 60,
    ) -> list[tuple[str, float]]:
        """Weighted RRF plus top-rank bonus (#1 +0.05, #2–3 +0.02)."""
        scores: dict[str, float] = {}
        best_rank: dict[str, int] = {}

        for li, ranked in enumerate(ranked_lists):
            w = weights[li] if li < len(weights) else 1.0
            for rank, (doc_id, _inner) in enumerate(ranked):
                contrib = w * (1.0 / (k + rank + 1))
                scores[doc_id] = scores.get(doc_id, 0.0) + contrib
                prev = best_rank.get(doc_id)
                if prev is None or rank < prev:
                    best_rank[doc_id] = rank

        for doc_id, br in best_rank.items():
            if br == 0:
                scores[doc_id] += 0.05
            elif br in (1, 2):
                scores[doc_id] += 0.02

        merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return merged

    async def expand_query_with_graph(self, query: str) -> list[str]:
        """Extract entities and append graph neighbor names (P1.5 graph-only expansion)."""
        entities = _extract_entity_names(query)
        if not entities:
            return [query]

        neighbors: list[str] = []
        seen: set[str] = set()
        cy = _neighbor_cypher()
        for name in entities:
            try:
                res = await self._graph.execute_query(cy, {"name": name})
            except Exception as exc:
                log.warning("graph_expand_failed", name=name, error=str(exc))
                continue
            rows = getattr(res, "data", None) or []
            for row in rows:
                nb = row.get("neighbor")
                if nb and nb not in seen:
                    seen.add(nb)
                    neighbors.append(nb)

        if not neighbors:
            return [query]
        tail = " ".join(neighbors)
        expanded = f"{query} {tail}".strip()
        return [query, expanded]

    async def search(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        *,
        expand_mode: str = "graph",
        scope: str | None = None,
    ) -> SearchResponse:
        _ = expand_mode  # LLM expansion reserved for future opt-in

        if mode in ("hybrid", "graph"):
            expansion_list = await self.expand_query_with_graph(query)
        else:
            expansion_list = [query]
        search_query = expansion_list[-1] if len(expansion_list) > 1 else query
        terms = _extract_entity_names(search_query)
        if not terms:
            terms = [t for t in re.split(r"\W+", query) if len(t) > 2][:8]

        meta: dict[str, dict[str, Any]] = {}

        async def run_graph() -> list[tuple[str, float]]:
            if mode not in ("hybrid", "graph"):
                return []
            cy = _graph_path_cypher()
            try:
                res = await self._graph.execute_query(
                    cy,
                    {"repository": repository, "terms": terms, "limit": max(limit * 5, limit)},
                )
            except Exception as exc:
                log.warning("wiki_graph_path_error", error=str(exc))
                return []
            rows = getattr(res, "data", None) or []
            ranked: list[tuple[str, float]] = []
            for i, row in enumerate(rows):
                pid = row.get("page_path") or row.get("path")
                if not pid:
                    continue
                ranked.append((str(pid), float(i)))
                meta.setdefault(str(pid), {}).update({
                    "title": row.get("title", ""),
                    "snippet": row.get("snippet", ""),
                    "source_locations": row.get("source_locations", []) or [],
                })
            return ranked

        async def run_vector() -> list[tuple[str, float]]:
            if mode not in ("hybrid", "semantic"):
                return []
            try:
                hits = await self._vector.search_all(search_query, k=max(limit * 5, limit))
            except Exception as exc:
                log.warning("wiki_vector_path_error", error=str(exc))
                return []
            if mode == "semantic" and min_score > 0:
                hits = [h for h in hits if float(h.get("score", 0.0)) >= min_score]
            ranked = []
            for i, hit in enumerate(hits):
                pid = _vector_hit_to_page(hit)
                if not pid:
                    continue
                ranked.append((pid, float(i)))
                meta.setdefault(pid, {}).update({
                    "title": hit.get("title") or hit.get("name") or "",
                    "snippet": (hit.get("docstring") or hit.get("content") or "")[:240],
                    "source_locations": [],
                    "inner_score": float(hit.get("score", 0.0)),
                })
            return ranked

        async def run_fts() -> list[tuple[str, float]]:
            if mode not in ("hybrid", "keyword"):
                return []
            cy = _fts_cypher()
            try:
                res = await self._fts.execute_query(
                    cy,
                    {"text": search_query.replace("\n", " "), "limit": max(limit * 5, limit)},
                )
            except Exception as exc:
                log.warning("wiki_fts_path_error", error=str(exc))
                return []
            rows = getattr(res, "data", None) or []
            ranked = []
            for i, row in enumerate(rows):
                node = row.get("node")
                props = getattr(node, "properties", None) or {}
                if isinstance(props, dict):
                    pid = props.get("path") or props.get("page_path")
                    title = props.get("title", "")
                    content = props.get("content", "")
                else:
                    pid = None
                    title = ""
                    content = ""
                if not pid:
                    continue
                snippet = (content or "")[:240]
                ranked.append((str(pid), float(i)))
                meta.setdefault(str(pid), {}).update({
                    "title": title,
                    "snippet": snippet,
                    "source_locations": [],
                })
            return ranked

        if mode == "hybrid":
            g_ranked, v_ranked, f_ranked = await asyncio.gather(
                run_graph(),
                run_vector(),
                run_fts(),
            )
            fused = WikiSearchService.rrf_fusion(
                [g_ranked, v_ranked, f_ranked],
                [_WEIGHT_GRAPH, _WEIGHT_VECTOR, _WEIGHT_FTS],
            )
        elif mode == "graph":
            fused = WikiSearchService.rrf_fusion([await run_graph()], [_WEIGHT_GRAPH])
        elif mode == "semantic":
            fused = WikiSearchService.rrf_fusion([await run_vector()], [_WEIGHT_VECTOR])
        elif mode == "keyword":
            fused = WikiSearchService.rrf_fusion([await run_fts()], [_WEIGHT_FTS])
        else:
            fused = []

        results: list[SearchResult] = []
        for page_path, score in fused:
            m = meta.get(page_path, {})
            if mode == "semantic":
                inner = float(m.get("inner_score", 0.0))
                if min_score > 0 and inner < min_score:
                    continue
                out_score = inner
            elif score < min_score:
                continue
            else:
                out_score = score
            results.append(
                SearchResult(
                    page_path=page_path,
                    title=str(m.get("title", "")),
                    score=out_score,
                    snippet=str(m.get("snippet", "")),
                    source_locations=list(m.get("source_locations", []) or []),
                    context={"repository": repository},
                )
            )
            if len(results) >= limit:
                break

        if scope:
            sn = scope.strip().rstrip("/")
            filtered: list[SearchResult] = []
            for r in results:
                pp = r.page_path.strip()
                if pp == sn or pp.startswith(sn + "/") or pp.startswith(sn):
                    filtered.append(r)
            results = filtered

        return SearchResponse(
            results=results,
            query_expansion={
                "original": query,
                "expanded_queries": expansion_list,
                "terms": terms,
            },
            total=len(results),
        )


def _vector_hit_to_page(hit: dict[str, Any]) -> str | None:
    for key in ("page_path", "wiki_path", "path"):
        v = hit.get(key)
        if v:
            return str(v)
    fqn = hit.get("fqn")
    if isinstance(fqn, str) and fqn:
        simple = fqn.split("#")[0].split(".")[-1]
        return f"classes/{simple}.md"
    name = hit.get("name")
    if isinstance(name, str) and name:
        return f"entities/{name}.md"
    return None
