"""Persisted Q&A memory for wiki: similar lookup and generation context injection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from store.wiki_store import WikiStore


@dataclass
class MemoryEntry:
    question: str
    answer: str
    source_pages: list[str]
    created_at: str
    quality_score: float


@runtime_checkable
class _Embed(Protocol):
    async def __call__(self, text: str) -> list[float]: ...


def _default_quality(source_pages: list[str]) -> float:
    if not source_pages:
        return 0.4
    return min(0.4 + 0.15 * min(len(source_pages), 4), 1.0)


class MemoryLoop:
    """Store wiki Q&A in the graph, retrieve by embedding similarity, enrich prompts."""

    def __init__(
        self,
        wiki_store: WikiStore,
        embed: _Embed,
        *,
        business_id: str = "default",
        vector_index_top_k: int = 30,
    ) -> None:
        self._store = wiki_store
        self._embed = embed
        self._business_id = business_id
        self._vector_index_top_k = vector_index_top_k

    @property
    def business_id(self) -> str:
        return self._business_id

    def with_business(self, business_id: str) -> MemoryLoop:
        return MemoryLoop(
            self._store,
            self._embed,
            business_id=business_id,
            vector_index_top_k=self._vector_index_top_k,
        )

    async def record(
        self,
        question: str,
        answer: str,
        source_pages: list[str],
        *,
        business_id: str | None = None,
    ) -> str:
        """Persist Q&A; returns new WikiQA uid."""
        bid = business_id or self._business_id
        text = f"{question.strip()}\n{answer.strip()}"
        emb = await self._embed(text)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return await self._store.persist_wiki_qa(
            business_id=bid,
            question=question.strip(),
            answer=answer.strip(),
            source_pages=list(source_pages),
            quality_score=_default_quality(source_pages),
            created_at=ts,
            embedding=emb,
        )

    async def get_relevant_memories(
        self,
        topic: str,
        limit: int = 5,
        *,
        business_id: str | None = None,
    ) -> list[MemoryEntry]:
        bid = business_id or self._business_id
        vec = await self._embed(topic.strip())
        res = await self._store.search_wiki_qa(
            vec, bid, k=self._vector_index_top_k, limit=limit,
        )
        out: list[MemoryEntry] = []
        for row in res.data or []:
            raw_pages = row.get("source_pages") or "[]"
            if isinstance(raw_pages, str):
                try:
                    pages: list[str] = json.loads(raw_pages)
                except json.JSONDecodeError:
                    pages = []
            else:
                pages = list(raw_pages) if raw_pages is not None else []
            out.append(
                MemoryEntry(
                    question=str(row.get("question") or ""),
                    answer=str(row.get("answer") or ""),
                    source_pages=pages,
                    created_at=str(row.get("created_at") or ""),
                    quality_score=float(row.get("quality_score") or 0.0),
                )
            )
        return out

    async def inject_into_generation(
        self,
        page_context: str,
        *,
        business_id: str | None = None,
        max_memories: int = 5,
    ) -> str:
        """Append related Q&A snippets to a wiki generation context string."""
        ctx = (page_context or "").strip()
        if not ctx:
            return ""
        # Use start of page context as the retrieval query (title / outline).
        topic = ctx[:1500] if len(ctx) > 1500 else ctx
        mems = await self.get_relevant_memories(topic, limit=max_memories, business_id=business_id)
        if not mems:
            return ctx
        lines: list[str] = [ctx, "", "## Relevant past Q&A (memory loop)", ""]
        for i, m in enumerate(mems, 1):
            lines.append(f"### {i}. Q: {m.question}\nA: {m.answer[:1200]}\n")
        return "\n".join(lines).strip()
