from __future__ import annotations

from wiki.rag.protocol import Chunk, RetrievalScope, Retriever


class CompositeRetriever:
    def __init__(self, children: list[Retriever]):
        self._children = children

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        merged: list[Chunk] = []
        for child in self._children:
            part = await child.retrieve(queries, scope, limit=limit, exclude_ids=exclude_ids)
            merged.extend(part)
        merged.sort(key=lambda c: c.relevance, reverse=True)
        return merged[:limit]
