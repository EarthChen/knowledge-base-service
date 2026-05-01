"""Cross-repository retriever using HybridQueryService.search_multi_repo."""
from __future__ import annotations

import logging
from typing import Any

from wiki.rag.hybrid_graph_retriever import _format_cypher_row
from wiki.rag.protocol import Chunk, RetrievalScope

logger = logging.getLogger(__name__)


def _hybrid_result_to_chunks(result: dict[str, Any]) -> list[Chunk]:
    """Convert HybridQueryService hybrid result dict to Chunk list."""
    rows = result.get("semantic_matches") or result.get("results") or []
    chunks: list[Chunk] = []
    for r in rows:
        if isinstance(r, dict):
            content = str(
                r.get("content") or r.get("summary") or r.get("name") or r,
            )
            title = str(r.get("title") or r.get("name") or "")
            rel = float(r.get("score", r.get("rrf_score", 0.5)) or 0.5)
            path = str(r.get("path") or r.get("file") or "")
        else:
            content = getattr(r, "content", str(r))
            title = getattr(r, "title", "") or ""
            rel = float(getattr(r, "score", 0.5) or 0.5)
            path = getattr(r, "path", "") or ""
        chunks.append(
            Chunk(
                content=content,
                source="wiki",
                title=title,
                relevance=rel,
                metadata={"path": path},
            ),
        )
    return chunks


class MultiRepoRetriever:
    """Global-scope retriever: parallel search across all registered repositories."""

    def __init__(
        self,
        hybrid_service: Any,
        repo_registry: Any | None = None,
        graph_service: Any | None = None,
        nl_cypher: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_service
        self._registry = repo_registry
        self._graph = graph_service
        self._nl_cypher = nl_cypher

    def _list_repo_names(self) -> list[str]:
        if self._registry is None:
            return []
        entries = self._registry.list_all()
        out: list[str] = []
        for e in entries:
            raw = e.get("repository")
            if raw is None:
                continue
            name = str(raw).strip()
            if name:
                out.append(name)
        return out

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        repos = self._list_repo_names()

        if scope.repository or len(repos) <= 1:
            return await self._single_repo_retrieve(queries, scope, limit=limit)

        combined = " ".join(q.strip() for q in queries if q.strip())
        if not combined:
            return []

        result = await self._hybrid.search_multi_repo(
            combined,
            repos,
            limit=limit,
        )
        chunks = _hybrid_result_to_chunks(result)
        await self._append_cypher_chunks(combined, chunks, repository=scope.repository)
        return chunks[:limit]

    async def _single_repo_retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for query in queries:
            if not query.strip():
                continue
            result = await self._hybrid.search_with_context(
                query,
                limit=limit,
                repository=scope.repository,
            )
            chunks.extend(_hybrid_result_to_chunks(result))
            await self._append_cypher_chunks(query, chunks, repository=scope.repository)
        return chunks[:limit]

    async def _append_cypher_chunks(
        self,
        query: str,
        chunks: list[Chunk],
        *,
        repository: str | None = None,
    ) -> None:
        if self._nl_cypher is None or not hasattr(self._nl_cypher, "query"):
            return
        try:
            query_fn = self._nl_cypher.query
            payload = await query_fn(query, repository=repository)
            rows = payload.get("results") or []
            for r in rows:
                content = _format_cypher_row(r) if isinstance(r, dict) else str(r)
                chunks.append(
                    Chunk(
                        content=content,
                        source="graph_cypher",
                        title="graph_cypher",
                        relevance=0.4,
                    ),
                )
        except Exception:
            logger.debug("multi_repo_nl_cypher_failed", exc_info=True)
