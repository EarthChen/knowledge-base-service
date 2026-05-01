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
                business_id=scope.business_id,
            )
            for r in hybrid_results:
                chunks.append(
                    Chunk(
                        content=getattr(r, "content", str(r)),
                        source="wiki",
                        title=getattr(r, "title", ""),
                        relevance=getattr(r, "score", 0.5),
                        metadata={"path": getattr(r, "path", "")},
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
