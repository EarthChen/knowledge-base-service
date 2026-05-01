from __future__ import annotations

from typing import Any

from wiki.rag.protocol import Chunk, RetrievalScope


class HybridGraphRetriever:
    """Wraps HybridQueryService + GraphQueryService as a Retriever."""

    def __init__(
        self,
        hybrid_service: Any,
        graph_service: Any,
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

            try:
                graph_results = await self._graph.query(
                    query,
                    business_id=scope.business_id,
                )
            except Exception:
                graph_results = []
            for r in graph_results:
                chunks.append(
                    Chunk(
                        content=str(r),
                        source="graph",
                        title="graph",
                        relevance=0.5,
                    )
                )
        return chunks[:limit]
