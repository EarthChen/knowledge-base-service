"""Hybrid query interface — combines graph traversal with semantic search.

Provides compound queries that first find semantically relevant entities,
then expand them via graph relationships to discover related code.

Search uses a **layered hybrid** strategy:
  Layer 1 — exact & fuzzy name match via graph (keyword_search)
  Layer 2 — vector similarity search (semantic_search)
  Layer 3 — fusion & deduplication, then graph expansion
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from log import get_logger
from query.graph_query import GraphQueryService
from query.query_router import SearchStrategy, route_query
from query.semantic_query import SemanticQueryService
from search.fusion import position_aware_blend, rrf_fusion
from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel
from store.search_store import SearchStore

log = get_logger(__name__)

_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)

_IDENT_RE = re.compile(
    r"\b"
    r"(?:"
    r"[a-z]+(?:[A-Z][a-zA-Z0-9]*)+|"   # camelCase  e.g. loginV2
    r"[A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]*)+|"  # PascalCase e.g. MdpMoaWrapperService
    r"[a-z]+(?:_[a-z0-9]+)+|"           # snake_case e.g. get_user_info
    r"[a-zA-Z_][a-zA-Z0-9_]{2,}"        # plain identifier >=3 chars
    r")"
    r"\b"
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# Optional filter for POST /hybrid (kept in sync with main._HYBRID_ENTITY_TYPE_TO_LABEL)
_HYBRID_ENTITY_TYPE_TO_LABEL: dict[str, str] = {
    "function": "Function",
    "class": "Class",
    "module": "Module",
    "document": "Document",
    "flow": "BusinessFlow",
    "concept": "BusinessConcept",
}


def _filter_merged_by_entity_type(
    merged: list[dict[str, Any]],
    entity_type: str | None,
) -> list[dict[str, Any]]:
    if not entity_type:
        return merged
    key = str(entity_type).strip().lower()
    if not key:
        return merged
    label = _HYBRID_ENTITY_TYPE_TO_LABEL.get(key)
    if label is None:
        return merged
    return [m for m in merged if m.get("type") == label]


def _sort_semantic_matches(merged: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    key = (sort_by or "score").strip().lower()
    if key == "name":
        return sorted(merged, key=lambda m: str(m.get("name") or "").lower())
    if key in ("path", "file"):
        return sorted(merged, key=lambda m: str(m.get("file") or "").lower())
    # score: RRF / fusion score (and optional rerank), descending
    def _score(m: dict[str, Any]) -> float:
        raw = m.get("rrf_score", m.get("score", m.get("confidence")))
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    return sorted(merged, key=_score, reverse=True)


def _apply_offset_limit(merged: list[dict[str, Any]], offset: int, limit: int) -> tuple[list[dict[str, Any]], int, int, int]:
    """Slice ``merged`` for pagination; returns (page, total_count, clamped_offset, clamped_limit)."""
    total = len(merged)
    off = max(0, int(offset))
    lim = max(1, min(500, int(limit)))
    return merged[off : off + lim], total, off, lim


def _contains_cjk(text: str) -> bool:
    return _CJK_RE.search(text) is not None


def _extract_identifiers(query: str) -> list[str]:
    """Extract probable code identifiers from a natural-language query."""
    stop_words = {
        "the", "this", "that", "what", "where", "which", "how", "does",
        "function", "class", "method", "module", "file", "code", "find",
        "search", "show", "get", "set", "for", "from", "with", "and",
        "not", "are", "was", "has", "have", "all",
    }
    regex_tokens = _IDENT_RE.findall(query)
    regex_filtered = [t for t in regex_tokens if t.lower() not in stop_words]

    if not _contains_cjk(query):
        return regex_filtered

    import jieba

    chinese_tokens = [w.strip() for w in jieba.lcut_for_search(query) if w.strip()]
    merged: list[str] = []
    seen: set[str] = set()
    for t in regex_filtered + chinese_tokens:
        if t.lower() in stop_words:
            continue
        if t not in seen:
            seen.add(t)
            merged.append(t)
    return merged


async def _empty_list() -> list[dict[str, Any]]:
    return []


@dataclass
class HybridResult:
    semantic_matches: list[dict[str, Any]] = field(default_factory=list)
    graph_context: list[dict[str, Any]] = field(default_factory=list)
    query_text: str = ""
    total: int = 0
    confidence: float = 0.0
    no_results_reason: str = ""


class HybridQueryService:
    """Combines semantic search with graph traversal for richer results."""

    def __init__(
        self,
        store: FalkorDBStore,
        semantic_svc: SemanticQueryService,
        graph_svc: GraphQueryService,
        reranker=None,
        query_expansion_enabled: bool = True,
        use_child_chunks: bool = False,
        search_store: SearchStore | None = None,
        enable_bm25: bool = True,
        bm25_weight: float = 1.2,
    ) -> None:
        self._store = store
        self._semantic = semantic_svc
        self._graph = graph_svc
        self._reranker = reranker
        self._query_expansion_enabled = query_expansion_enabled
        self._use_child_chunks = use_child_chunks
        self._search_store = search_store
        self._enable_bm25 = enable_bm25
        self._bm25_weight = bm25_weight

    @property
    def semantic(self) -> SemanticQueryService:
        return self._semantic

    async def search_with_context(
        self,
        query_text: str,
        k: int = 5,
        expand_depth: int = 2,
        include_callers: bool = True,
        include_callees: bool = True,
        use_query_expansion: bool = True,
        use_query_router: bool = True,
        use_child_chunks: bool | None = None,
        repository: str | None = None,
        language: str | None = None,
        per_file_cap: int = 3,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "score",
        entity_type: str | None = None,
        enable_bm25: bool | None = None,
    ) -> dict[str, Any]:
        """Layered hybrid search with optional graph-based query expansion.

        Layer 1: exact & fuzzy name match (via FalkorDB keyword_search)
        Layer 2: vector similarity search (via embedding model)
        Layer 3: fusion (keyword hits scored higher), dedup, graph expansion

        When *use_child_chunks* is True, Layer 2 is replaced with chunk-level
        vector search that returns precise code excerpts grouped by parent entity.
        """
        if use_child_chunks is None:
            use_child_chunks = self._use_child_chunks

        if enable_bm25 is not None:
            do_bm25 = bool(enable_bm25) and self._search_store is not None
        else:
            do_bm25 = self._enable_bm25 and self._search_store is not None

        router_strategy = route_query(query_text) if use_query_router else None

        if use_child_chunks:
            return await self._search_with_child_chunks(
                query_text, k, expand_depth, include_callers, include_callees,
                repository=repository, language=language, per_file_cap=per_file_cap,
                router_strategy=router_strategy,
                use_query_router=use_query_router,
                offset=offset, limit=limit, sort_by=sort_by, entity_type=entity_type,
            )

        should_expand = use_query_expansion and self._query_expansion_enabled
        if should_expand:
            expansion_queries = await self._expand_query_with_graph(
                query_text, repository=repository, language=language,
            )
        else:
            expansion_queries = [query_text]

        kw_ranked_lists: list[list[tuple[str, float]]] = []
        sem_ranked_lists: list[list[tuple[str, float]]] = []
        bm25_ranked_lists: list[list[tuple[str, float]]] = []
        kw_weights: list[float] = []
        sem_weights: list[float] = []
        bm25_weights: list[float] = []
        doc_map: dict[str, dict[str, Any]] = {}

        for i, eq in enumerate(expansion_queries):
            fqn_matches = _FQN_RE.findall(eq)
            if fqn_matches:
                identifiers = [m.split("(")[0].strip() for m in fqn_matches]
            else:
                identifiers = _extract_identifiers(eq)

            kw_coro = (
                self._keyword_search_multi(identifiers, k, repository=repository, language=language)
                if identifiers else _empty_list()
            )
            sem_coro = self._semantic.search_all(eq, k, repository=repository, language=language)
            if do_bm25 and self._search_store is not None:
                bm25_lim = max(k * 3, 20)
                bm25_coro = self._search_store.fulltext_search(
                    eq, limit=bm25_lim, repository=repository, language=language,
                )
                kw_hits, sem_result, bm25_hits = await asyncio.gather(kw_coro, sem_coro, bm25_coro)
            else:
                kw_hits, sem_result = await asyncio.gather(kw_coro, sem_coro)
                bm25_hits = []

            if router_strategy is None:
                w = 1.5 if i == 0 else 0.75
                sw = 1.0 if i == 0 else 0.5
            else:
                w = router_strategy.keyword_weight if i == 0 else router_strategy.keyword_weight * 0.5
                sw = router_strategy.semantic_weight if i == 0 else router_strategy.semantic_weight * 0.5
            kw_ranked_lists.append([(self._doc_key(h), float(j)) for j, h in enumerate(kw_hits)])
            kw_weights.append(w)

            sem_ranked_lists.append([(self._doc_key(m), float(j)) for j, m in enumerate(sem_result.matches)])
            sem_weights.append(sw)

            if do_bm25 and self._search_store is not None:
                if router_strategy is None:
                    bw = self._bm25_weight * (1.0 if i == 0 else 0.5)
                else:
                    base = router_strategy.semantic_weight * self._bm25_weight
                    bw = base if i == 0 else base * 0.5
                bm25_ranked_lists.append([(self._doc_key(h), float(j)) for j, h in enumerate(bm25_hits)])
                bm25_weights.append(bw)

            for h in kw_hits:
                key = self._doc_key(h)
                if key not in doc_map:
                    doc_map[key] = {**h, "match_source": "keyword"}
            for m in sem_result.matches:
                key = self._doc_key(m)
                if key not in doc_map:
                    doc_map[key] = {**m, "match_source": "semantic"}
            if do_bm25 and self._search_store is not None:
                for h in bm25_hits:
                    key = self._doc_key(h)
                    if key not in doc_map:
                        doc_map[key] = {**h, "match_source": "bm25"}

        merged = await self._fuse_expansion_results(
            query_text,
            kw_ranked_lists,
            sem_ranked_lists,
            kw_weights,
            sem_weights,
            doc_map,
            k,
            per_file_cap=per_file_cap,
            bm25_ranked_lists=bm25_ranked_lists if bm25_ranked_lists else None,
            bm25_weights=bm25_weights if bm25_weights else None,
        )

        if router_strategy is not None and not router_strategy.expand_graph:
            graph_context = []
        else:
            graph_seed_matches = merged
            if router_strategy is not None and router_strategy.entity_priority:
                preferred = [
                    m for m in merged if str(m.get("type", "")) in router_strategy.entity_priority
                ]
                if preferred:
                    graph_seed_matches = preferred
            graph_context = await self._expand_graph(
                graph_seed_matches, expand_depth, include_callers, include_callees,
            )

        confidence, no_results_reason = self._confidence_and_reason(merged)
        return self._finalize_hybrid_response(
            merged,
            graph_context,
            query_text=query_text,
            confidence=confidence,
            no_results_reason=no_results_reason,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            entity_type=entity_type,
        )

    async def search_multi_repo(
        self,
        query_text: str,
        repositories: list[str],
        *,
        k: int = 5,
        expand_depth: int = 2,
        include_callers: bool = True,
        include_callees: bool = True,
        use_query_expansion: bool = True,
        use_query_router: bool = True,
        use_child_chunks: bool | None = None,
        language: str | None = None,
        per_file_cap: int = 3,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "score",
        entity_type: str | None = None,
        enable_bm25: bool | None = None,
    ) -> dict[str, Any]:
        """Run ``search_with_context`` per repository in parallel and merge results."""
        repos = [str(r).strip() for r in repositories if str(r).strip()]
        if len(repos) <= 1:
            single = repos[0] if repos else None
            return await self.search_with_context(
                query_text,
                k=k,
                expand_depth=expand_depth,
                include_callers=include_callers,
                include_callees=include_callees,
                use_query_expansion=use_query_expansion,
                use_query_router=use_query_router,
                use_child_chunks=use_child_chunks,
                repository=single,
                language=language,
                per_file_cap=per_file_cap,
                offset=offset,
                limit=limit,
                sort_by=sort_by,
                entity_type=entity_type,
                enable_bm25=enable_bm25,
            )

        fetch_limit = 500
        tasks = [
            self.search_with_context(
                query_text,
                k=k,
                expand_depth=expand_depth,
                include_callers=include_callers,
                include_callees=include_callees,
                use_query_expansion=use_query_expansion,
                use_query_router=use_query_router,
                use_child_chunks=use_child_chunks,
                repository=repo,
                language=language,
                per_file_cap=per_file_cap,
                offset=0,
                limit=fetch_limit,
                sort_by="score",
                entity_type=None,
                enable_bm25=enable_bm25,
            )
            for repo in repos
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        per_repo: list[dict[str, Any]] = []
        errors: list[str] = []
        for i, r in enumerate(raw_results):
            if isinstance(r, BaseException):
                errors.append(f"{repos[i]}: {r}")
                log.warning("multi_repo_search_partial_failure", repo=repos[i], error=str(r))
            else:
                per_repo.append(r)

        if not per_repo:
            return {
                "results": [], "semantic_matches": [], "total": 0,
                "offset": offset, "limit": limit, "graph_context": [],
                "query_text": query_text, "confidence": 0.0,
                "no_results_reason": "All repository searches failed",
                "errors": errors,
            }

        combined: list[dict[str, Any]] = []
        graph_all: list[dict[str, Any]] = []
        for r in per_repo:
            rows = r.get("semantic_matches") or r.get("results") or []
            combined.extend(rows)
            graph_all.extend(r.get("graph_context") or [])

        def _score_val(m: dict[str, Any]) -> float:
            raw = m.get("rrf_score", m.get("score", m.get("confidence")))
            if raw is None:
                return 0.0
            try:
                return float(raw)
            except (TypeError, ValueError):
                return 0.0

        combined.sort(key=_score_val, reverse=True)
        deduped: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for m in combined:
            uid = m.get("uid", "")
            dk = uid if uid else self._doc_key(m)
            if dk in seen_keys:
                continue
            seen_keys.add(dk)
            deduped.append(m)

        confidence, no_results_reason = self._confidence_and_reason(deduped)
        finalized = self._finalize_hybrid_response(
            deduped,
            self._deduplicate(graph_all),
            query_text=query_text,
            confidence=confidence,
            no_results_reason=no_results_reason,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            entity_type=entity_type,
        )
        if errors:
            finalized["errors"] = errors
        return finalized

    def _finalize_hybrid_response(
        self,
        merged: list[dict[str, Any]],
        graph_context: list[dict[str, Any]],
        *,
        query_text: str,
        confidence: float,
        no_results_reason: str,
        offset: int,
        limit: int,
        sort_by: str,
        entity_type: str | None,
    ) -> dict[str, Any]:
        """Sort + paginate semantic matches after full retrieval and graph expansion."""
        filtered = _filter_merged_by_entity_type(merged, entity_type)
        sorted_m = _sort_semantic_matches(filtered, sort_by)
        page_rows, total, off, lim = _apply_offset_limit(sorted_m, offset, limit)
        return {
            "results": page_rows,
            "semantic_matches": page_rows,
            "total": total,
            "offset": off,
            "limit": lim,
            "graph_context": graph_context,
            "query_text": query_text,
            "confidence": confidence,
            "no_results_reason": no_results_reason,
        }

    async def _search_with_child_chunks(
        self,
        query_text: str,
        k: int,
        expand_depth: int,
        include_callers: bool,
        include_callees: bool,
        *,
        repository: str | None = None,
        language: str | None = None,
        per_file_cap: int = 3,
        router_strategy: SearchStrategy | None = None,
        use_query_router: bool = True,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "score",
        entity_type: str | None = None,
    ) -> dict[str, Any]:
        """Chunk-aware hybrid search: keyword + chunk-vector + parent context."""
        if not use_query_router:
            router_strategy = None
        if router_strategy is None:
            kw_w, sem_w = 1.5, 1.0
            expand_graph = True
        else:
            kw_w = router_strategy.keyword_weight
            sem_w = router_strategy.semantic_weight
            expand_graph = router_strategy.expand_graph

        identifiers = _extract_identifiers(query_text)
        kw_coro = (
            self._keyword_search_multi(identifiers, k, repository=repository, language=language)
            if identifiers else _empty_list()
        )
        chunk_coro = self._semantic.search_with_parent_context(
            query_text, k=k, repository=repository, language=language,
        )

        kw_hits, chunk_result = await asyncio.gather(kw_coro, chunk_coro)

        doc_map: dict[str, dict[str, Any]] = {}
        kw_ranked: list[tuple[str, float]] = []
        sem_ranked: list[tuple[str, float]] = []

        for i, h in enumerate(kw_hits):
            key = self._doc_key(h)
            if key not in doc_map:
                doc_map[key] = {**h, "match_source": "keyword"}
            kw_ranked.append((key, float(i)))

        for i, m in enumerate(chunk_result.matches):
            key = self._doc_key(m)
            if key in doc_map:
                existing = doc_map[key]
                if "matched_excerpt" not in existing and "matched_excerpt" in m:
                    existing["matched_excerpt"] = m["matched_excerpt"]
                    existing["excerpt_lines"] = m.get("excerpt_lines")
            else:
                doc_map[key] = {**m, "match_source": "chunk_semantic"}
            sem_ranked.append((key, float(i)))

        merged = await self._fuse_expansion_results(
            query_text,
            [kw_ranked],
            [sem_ranked],
            [kw_w],
            [sem_w],
            doc_map,
            k,
            per_file_cap=per_file_cap,
        )

        if not expand_graph:
            graph_context = []
        else:
            graph_seed_matches = merged
            if router_strategy is not None and router_strategy.entity_priority:
                preferred = [
                    m for m in merged if str(m.get("type", "")) in router_strategy.entity_priority
                ]
                if preferred:
                    graph_seed_matches = preferred
            graph_context = await self._expand_graph(
                graph_seed_matches, expand_depth, include_callers, include_callees,
            )

        confidence, no_results_reason = self._confidence_and_reason(merged)
        return self._finalize_hybrid_response(
            merged,
            graph_context,
            query_text=query_text,
            confidence=confidence,
            no_results_reason=no_results_reason,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            entity_type=entity_type,
        )

    async def _expand_query_with_graph(
        self,
        query_text: str,
        max_expansions: int = 3,
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> list[str]:
        """Expand query using graph neighbor names for richer search.

        Given a query, find entities matching the query terms via keyword search,
        then collect their graph neighbors' names as expansion terms.
        Returns [original_query, expanded_query_1, ...].
        """
        queries = [query_text]

        try:
            identifiers = _extract_identifiers(query_text)
            if not identifiers:
                return queries

            hits = await self._keyword_search_multi(
                identifiers[:2], k=3, repository=repository, language=language,
            )
            if not hits:
                return queries

            neighbor_names: set[str] = set()
            for hit in hits[:2]:
                name = hit.get("name", "")
                entity_type = hit.get("type", "")
                if not name:
                    continue

                try:
                    if entity_type in ("Function", str(NodeLabel.FUNCTION)):
                        callees = await self._graph.find_call_chain(name, depth=1, direction="downstream")
                        for item in callees.data[:3]:
                            n = item.get("name", "")
                            if n and n != name:
                                neighbor_names.add(n)
                    elif entity_type in ("Class", str(NodeLabel.CLASS)):
                        methods = await self._graph.find_class_methods(name)
                        for item in methods.data[:3]:
                            n = item.get("name", "")
                            if n and n != name:
                                neighbor_names.add(n)
                except Exception:
                    log.debug("graph_expansion_failed", entity=name, exc_info=True)
                    continue

            for neighbor in list(neighbor_names)[:max_expansions]:
                queries.append(f"{query_text} {neighbor}")

        except Exception:
            log.debug("query_expansion_failed", exc_info=True)

        return queries

    async def _keyword_search_multi(
        self,
        identifiers: list[str],
        k: int,
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run keyword search for each extracted identifier and merge results."""
        all_hits: list[dict[str, Any]] = []
        seen_uids: set[str] = set()
        for ident in identifiers[:3]:
            hits = await self._store.keyword_search(ident, k=k, repository=repository, language=language)
            for hit in hits:
                uid = hit.get("uid", "")
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    all_hits.append(hit)
        return all_hits

    @staticmethod
    def _doc_key(match: dict[str, Any]) -> str:
        name = match.get("name") or ""
        file = match.get("file") or ""
        line = str(match.get("line") or "")
        return f"{name}:{file}:{line}"

    @staticmethod
    def _blend_rrf_rerank_confidence(
        rrf_normalized: float,
        *rerank_candidates: Any,
    ) -> float:
        """Combine normalized RRF confidence with an optional reranker score when present."""
        base = max(0.0, min(1.0, float(rrf_normalized)))
        rerank_raw = None
        for c in rerank_candidates:
            if c is None:
                continue
            try:
                rerank_raw = float(c)
                break
            except (TypeError, ValueError):
                continue
        if rerank_raw is None:
            return base
        rerank_norm = max(0.0, min(1.0, rerank_raw))
        return max(0.0, min(1.0, 0.55 * base + 0.45 * rerank_norm))

    @staticmethod
    def _attach_fusion_scores(
        ordered_pairs: list[tuple[str, float]],
        doc_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Copy matches from ``doc_map`` in fused order with ``score`` / ``confidence`` (0–1)."""
        out: list[dict[str, Any]] = []
        for doc_id, fused_score in ordered_pairs:
            if doc_id not in doc_map:
                continue
            item = dict(doc_map[doc_id])
            fs = float(fused_score)
            item["score"] = fs
            item["confidence"] = fs
            out.append(item)
        return out

    @staticmethod
    def _confidence_and_reason(semantic_matches: list[dict[str, Any]]) -> tuple[float, str]:
        """Aggregate confidence from per-result scores (normalized RRF ± reranker blend)."""
        if not semantic_matches:
            return 0.0, "No matching entities found for query"
        values: list[float] = []
        for m in semantic_matches:
            raw = m.get("confidence")
            if raw is None:
                raw = m.get("score")
            if raw is None:
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if not values:
            return 0.0, ""
        top = sorted(values, reverse=True)[:3]
        blended = 0.65 * top[0] + 0.35 * (sum(top) / len(top))
        return max(0.0, min(1.0, blended)), ""

    @staticmethod
    def _ensure_graph_location_fields(item: dict[str, Any]) -> dict[str, Any]:
        """Normalize graph_context rows so agents always see file / line range keys."""
        file_path = item.get("file") or ""
        line_single = item.get("line")
        start = item.get("start_line")
        end = item.get("end_line")
        if start is None and line_single is not None:
            try:
                start = int(line_single)
            except (TypeError, ValueError):
                start = 0
        if end is None:
            end = start if start is not None else 0
        try:
            start_i = int(start or 0)
        except (TypeError, ValueError):
            start_i = 0
        try:
            end_i = int(end or 0)
        except (TypeError, ValueError):
            end_i = start_i
        out = dict(item)
        out["file"] = file_path
        out["start_line"] = start_i
        out["end_line"] = end_i
        return out

    @staticmethod
    def _fuse_results_legacy(
        keyword_hits: list[dict[str, Any]],
        semantic_matches: list[dict[str, Any]],
        k: int,
    ) -> list[dict[str, Any]]:
        """Deprecated: merge keyword and semantic results by score sort (pre-RRF).

        Kept for backward compatibility; prefer :meth:`_fuse_results_rrf`.
        """
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        for hit in keyword_hits:
            key = HybridQueryService._doc_key(hit)
            if key not in seen:
                seen.add(key)
                merged.append({
                    "type": hit.get("type", ""),
                    "name": hit.get("name", ""),
                    "file": hit.get("file", ""),
                    "line": hit.get("line", 0),
                    "score": hit.get("score", 1.0),
                    "signature": hit.get("signature", ""),
                    "docstring": hit.get("docstring", ""),
                    "match_source": "keyword",
                })

        for m in semantic_matches:
            key = HybridQueryService._doc_key(m)
            if key not in seen:
                seen.add(key)
                entry = dict(m)
                entry["match_source"] = "semantic"
                merged.append(entry)

        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[:k]

    # Deprecated name; use :meth:`_fuse_results_rrf` for hybrid search.
    _fuse_results = _fuse_results_legacy

    async def _fuse_expansion_results(
        self,
        query_text: str,
        kw_ranked_lists: list[list[tuple[str, float]]],
        sem_ranked_lists: list[list[tuple[str, float]]],
        kw_weights: list[float],
        sem_weights: list[float],
        doc_map: dict[str, dict[str, Any]],
        k: int,
        per_file_cap: int = 3,
        bm25_ranked_lists: list[list[tuple[str, float]]] | None = None,
        bm25_weights: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Fuse multi-query results with per-query weighted RRF; optional reranker blend.

        Each expansion round produces separate ranked lists with distinct weights.
        Original query gets higher weights (kw=1.5, sem=1.0) than expansion
        queries (kw=0.75, sem=0.5) ensuring original matches dominate.
        """
        bm25_ranked_lists = bm25_ranked_lists or []
        bm25_weights = bm25_weights or []
        all_ranked = list(kw_ranked_lists) + list(sem_ranked_lists)
        all_weights = list(kw_weights) + list(sem_weights)
        if bm25_ranked_lists and bm25_weights:
            all_ranked += bm25_ranked_lists
            all_weights += bm25_weights

        candidate_k = k * 3 if self._reranker else k
        fused = rrf_fusion(all_ranked, all_weights)[:candidate_k]

        rrf_ordered = [(doc_id, score) for doc_id, score in fused if doc_id in doc_map]

        if self._reranker:
            try:
                if hasattr(self._reranker, "rerank_with_scores"):
                    merged_pre = [dict(doc_map[i]) for i, _ in rrf_ordered]
                    scored_pairs = await self._reranker.rerank_with_scores(
                        query_text, merged_pre, top_k=k, return_all_scores=True
                    )
                    re_scores = {self._doc_key(m): float(s) for m, s in scored_pairs}
                    final = position_aware_blend(rrf_ordered, re_scores, top_k=k)
                    merged = self._attach_fusion_scores(final, doc_map)
                else:
                    merged_raw = await self._reranker.rerank(
                        query_text,
                        [dict(doc_map[i]) for i, _ in rrf_ordered[:candidate_k]],
                        top_k=k,
                    )
                    rrf_lookup = dict(rrf_ordered)
                    merged = []
                    for m in merged_raw[:k]:
                        item = dict(m)
                        ky = self._doc_key(item)
                        rrf_s = float(rrf_lookup.get(ky, 0.0))
                        item["score"] = rrf_s
                        item["confidence"] = HybridQueryService._blend_rrf_rerank_confidence(
                            rrf_s,
                            item.get("rerank_score"),
                            item.get("reranker_score"),
                        )
                        merged.append(item)
            except Exception:
                log.warning("reranker_blend_failed", exc_info=True)
                merged = self._attach_fusion_scores(rrf_ordered[:k], doc_map)
        else:
            merged = self._attach_fusion_scores(rrf_ordered[:k], doc_map)

        if per_file_cap > 0:
            merged = self._apply_per_file_cap(merged, per_file_cap)

        return merged

    async def _fuse_results_rrf(
        self,
        query_text: str,
        keyword_hits: list[dict[str, Any]],
        semantic_matches: list[dict[str, Any]],
        k: int,
    ) -> list[dict[str, Any]]:
        """Fuse keyword and semantic hits with weighted RRF; optional reranker blend."""
        doc_map: dict[str, dict[str, Any]] = {}
        for h in keyword_hits:
            key = self._doc_key(h)
            if key not in doc_map:
                doc_map[key] = {**h, "match_source": "keyword"}
        for m in semantic_matches:
            key = self._doc_key(m)
            if key not in doc_map:
                doc_map[key] = {**m, "match_source": "semantic"}

        kw_ranked = [(self._doc_key(h), float(i)) for i, h in enumerate(keyword_hits)]
        sem_ranked = [(self._doc_key(m), float(i)) for i, m in enumerate(semantic_matches)]

        return await self._fuse_expansion_results(
            query_text, [kw_ranked], [sem_ranked], [1.5], [1.0], doc_map, k,
        )

    async def _expand_graph(
        self,
        matches: list[dict[str, Any]],
        expand_depth: int,
        include_callers: bool,
        include_callees: bool,
    ) -> list[dict[str, Any]]:
        """Expand matched entities through graph relationships."""
        graph_context: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for match in matches:
            name = match.get("name", "")
            entity_type = match.get("type", "")

            if name in seen_names or not name:
                continue
            seen_names.add(name)

            if entity_type == str(NodeLabel.FUNCTION) or entity_type == "Function":
                if include_callees:
                    callees = await self._graph.find_call_chain(name, depth=expand_depth, direction="downstream")
                    for item in callees.data:
                        enriched = self._ensure_graph_location_fields(item)
                        enriched["relationship"] = "called_by"
                        enriched["source"] = name
                        graph_context.append(enriched)

                if include_callers:
                    callers = await self._graph.find_call_chain(name, depth=expand_depth, direction="upstream")
                    for item in callers.data:
                        enriched = self._ensure_graph_location_fields(item)
                        enriched["relationship"] = "calls"
                        enriched["source"] = name
                        graph_context.append(enriched)

            elif entity_type == str(NodeLabel.CLASS) or entity_type == "Class":
                methods = await self._graph.find_class_methods(name)
                for item in methods.data:
                    enriched = self._ensure_graph_location_fields(item)
                    enriched["relationship"] = "method_of"
                    enriched["source"] = name
                    graph_context.append(enriched)

                children = await self._graph.find_inheritance_tree(name, direction="children")
                for item in children.data:
                    enriched = self._ensure_graph_location_fields(item)
                    enriched["relationship"] = "subclass_of"
                    enriched["source"] = name
                    graph_context.append(enriched)

        for match in matches:
            name = match.get("name", "")
            if not name:
                continue
            try:
                flows_result = await self._graph.find_flows_for_function(name)
                if flows_result.data:
                    for row in flows_result.data:
                        graph_context.append({
                            "type": "business_flow",
                            "source": "flow_association",
                            "data": row,
                            "related_function": name,
                        })
            except Exception:
                log.warning("business_flow_lookup_failed", function=name, exc_info=True)

        return self._deduplicate(graph_context)

    async def search_keyword_only(self, query_text: str, k: int = 10) -> list[dict[str, Any]]:
        """Convenience method: keyword-only search (no vector)."""
        identifiers = _extract_identifiers(query_text)
        if not identifiers:
            identifiers = [query_text.strip()]
        return await self._keyword_search_multi(identifiers, k)

    async def find_related_to_file(self, file_path: str) -> HybridResult:
        """Find all entities in a file and their graph relationships."""
        entities = await self._graph.find_file_entities(file_path)

        graph_context: list[dict[str, Any]] = []
        for entity in entities.data:
            name = entity.get("name", "")
            entity_type = entity.get("type", "")

            if entity_type == "Function":
                callees = await self._graph.find_call_chain(name, depth=1, direction="downstream")
                for item in callees.data:
                    enriched = self._ensure_graph_location_fields(item)
                    enriched["relationship"] = "called_by"
                    enriched["source"] = name
                    graph_context.append(enriched)

            elif entity_type == "Class":
                methods = await self._graph.find_class_methods(name)
                for item in methods.data:
                    enriched = self._ensure_graph_location_fields(item)
                    enriched["relationship"] = "method_of"
                    enriched["source"] = name
                    graph_context.append(enriched)

        return HybridResult(
            semantic_matches=[{"type": e.get("type", ""), "name": e.get("name", "")} for e in entities.data],
            graph_context=self._deduplicate(graph_context),
            query_text=f"file:{file_path}",
            total=len(entities.data) + len(graph_context),
        )

    @staticmethod
    def _apply_per_file_cap(
        items: list[dict[str, Any]], cap: int = 3,
    ) -> list[dict[str, Any]]:
        """Limit results per file to ensure diversity across the codebase.

        When *cap* <= 0 the filter is disabled and all items pass through.
        Note: this may return fewer than the requested ``k`` when a single
        file dominates the fused result set — that is by design.
        """
        if cap <= 0:
            return items
        file_counts: dict[str, int] = {}
        result: list[dict[str, Any]] = []
        for item in items:
            fpath = item.get("file") or ""
            count = file_counts.get(fpath, 0)
            if count < cap:
                file_counts[fpath] = count + 1
                result.append(item)
        return result

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            key = f"{item.get('name', '')}:{item.get('file', '')}:{item.get('line', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique
