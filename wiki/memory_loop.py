"""Persisted Q&A memory for wiki: similar lookup and generation context injection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from store.wiki_store import WikiStore


@dataclass
class MemoryEntry:
    question: str
    answer: str
    source_pages: list[str]
    created_at: str
    quality_score: float
    uid: str = ""
    memory_status: str = "active"
    tier: int = 1
    confidence: float = 0.0
    similarity: float = 0.0


@runtime_checkable
class _Embed(Protocol):
    async def __call__(self, text: str) -> list[float]: ...


def _default_quality(source_pages: list[str]) -> float:
    if not source_pages:
        return 0.4
    return min(0.4 + 0.15 * min(len(source_pages), 4), 1.0)


def _tier_rank_score(similarity: float, tier: int) -> float:
    """Weight vector similarity to prefer higher consolidation tiers (0–3)."""
    return float(similarity) * (1.0 + 0.3 * float(tier))


class MemoryLoop:
    """Store wiki Q&A in the graph, retrieve by embedding similarity, enrich prompts."""

    def __init__(
        self,
        wiki_store: WikiStore,
        embed: _Embed,
        *,
        business_id: str = "default",
        vector_index_top_k: int = 30,
        memory_tiers_enabled: bool = False,
    ) -> None:
        self._store = wiki_store
        self._embed = embed
        self._business_id = business_id
        self._vector_index_top_k = vector_index_top_k
        self._memory_tiers_enabled = memory_tiers_enabled

    @property
    def business_id(self) -> str:
        return self._business_id

    def with_business(self, business_id: str) -> MemoryLoop:
        return MemoryLoop(
            self._store,
            self._embed,
            business_id=business_id,
            vector_index_top_k=self._vector_index_top_k,
            memory_tiers_enabled=self._memory_tiers_enabled,
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
        fetch_limit = limit
        if self._memory_tiers_enabled:
            fetch_limit = min(100, max(limit * 10, 30))
        res = await self._store.search_wiki_qa(
            vec, bid, k=self._vector_index_top_k, limit=fetch_limit,
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
            tier_raw = row.get("tier")
            try:
                tier = int(tier_raw) if tier_raw is not None else 1
            except (TypeError, ValueError):
                tier = 1
            mem_st = str(row.get("memory_status") or "active")
            out.append(
                MemoryEntry(
                    question=str(row.get("question") or ""),
                    answer=str(row.get("answer") or ""),
                    source_pages=pages,
                    created_at=str(row.get("created_at") or ""),
                    quality_score=float(row.get("quality_score") or 0.0),
                    uid=str(row.get("uid") or ""),
                    memory_status=mem_st,
                    tier=tier,
                    confidence=float(row.get("confidence") or 0.0),
                    similarity=float(row.get("similarity") or 0.0),
                )
            )
        if not self._memory_tiers_enabled:
            return out
        active: list[MemoryEntry] = []
        for m in out:
            if m.memory_status == "expired":
                continue
            active.append(m)
        faded: list[MemoryEntry] = []
        sharp: list[MemoryEntry] = []
        for m in active:
            (faded if m.memory_status == "faded" else sharp).append(m)
        def sort_key(m: MemoryEntry) -> float:
            return _tier_rank_score(m.similarity, m.tier)
        sharp.sort(key=sort_key, reverse=True)
        faded.sort(key=sort_key, reverse=True)
        ranked = sharp + faded
        return ranked[:limit]

    async def inject_into_generation(self, entity_name: str, repository: str) -> str:
        """Retrieve relevant Q&A memories and format for wiki generation context."""
        _ = repository  # reserved for future repository-scoped memory filtering
        memories = await self.get_relevant_memories(entity_name, limit=5)
        if not memories:
            return ""
        parts: list[str] = ["## Previous Q&A Knowledge"]
        for m in memories:
            q = m.question
            a = m.answer
            if q and a:
                parts.append(f"**Q:** {q}\n**A:** {a[:500]}")
        return "\n\n".join(parts)
