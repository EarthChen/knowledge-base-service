from __future__ import annotations

import logging
from typing import Any

from wiki.rag.protocol import Chunk, RetrievalScope

logger = logging.getLogger(__name__)


class HybridGraphRetriever:
    """Wraps HybridQueryService + optional graph service as a Retriever."""

    def __init__(
        self,
        hybrid_service: Any,
        graph_service: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_service
        self._graph = graph_service

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for query in queries:
            hybrid_results = await self._hybrid.search_with_context(
                query,
                limit=limit,
            )
            if isinstance(hybrid_results, dict):
                rows = (
                    hybrid_results.get("semantic_matches")
                    or hybrid_results.get("results")
                    or []
                )
            else:
                rows = hybrid_results or []

            for r in rows:
                if isinstance(r, dict):
                    content = str(
                        r.get("content")
                        or r.get("summary")
                        or r.get("name")
                        or r
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
                    )
                )

            if self._graph is not None and hasattr(self._graph, "find_entity"):
                try:
                    terms = query.split()[:3]
                    for term in terms:
                        result = await self._graph.find_entity(term)
                        for r in getattr(result, "rows", []):
                            content = str(r) if not isinstance(r, dict) else str(r.get("name", r))
                            chunks.append(
                                Chunk(
                                    content=content,
                                    source="graph",
                                    title="graph",
                                    relevance=0.4,
                                )
                            )
                except Exception:
                    logger.debug("graph_retriever_entity_lookup_failed", exc_info=True)
        return chunks[:limit]
