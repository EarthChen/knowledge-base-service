"""Detect and merge similar concepts across repositories."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from log import get_logger

log = get_logger(__name__)


@dataclass
class MergeCandidate:
    page_uid_a: str
    page_uid_b: str
    similarity: float
    title_a: str
    title_b: str


class ConceptMerger:
    def __init__(self, wiki_store: Any, similarity_threshold: float = 0.9) -> None:
        self._store = wiki_store
        self._threshold = similarity_threshold

    async def find_candidates(self, business_id: str) -> list[MergeCandidate]:
        """Find cross-repo WikiPage pairs with embedding similarity above threshold."""
        cypher = (
            "MATCH (a:WikiPage), (b:WikiPage) "
            "WHERE a.business_id = $biz AND b.business_id = $biz "
            "AND a.repository <> b.repository "
            "AND id(a) < id(b) "
            "AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL "
            "RETURN a.uid AS a_uid, b.uid AS b_uid, "
            "a.title AS a_title, b.title AS b_title, "
            "vec.cosine_similarity(a.embedding, b.embedding) AS similarity "
            "ORDER BY similarity DESC LIMIT 50"
        )
        result = await self._store.execute_query(cypher, {"biz": business_id})
        rows = getattr(result, "data", []) or []
        candidates = []
        for row in rows:
            sim = row.get("similarity", 0)
            if sim >= self._threshold:
                candidates.append(
                    MergeCandidate(
                        page_uid_a=row["a_uid"],
                        page_uid_b=row["b_uid"],
                        similarity=sim,
                        title_a=row.get("a_title", ""),
                        title_b=row.get("b_title", ""),
                    )
                )
        return candidates

    async def generate_concept_page(self, candidate: MergeCandidate, llm: Any) -> dict[str, Any]:
        """Generate a consolidated ConceptPage from two similar entity pages."""
        prompt = (
            f"Consolidate these two related concepts into one unified description:\n"
            f"- {candidate.title_a} (from page {candidate.page_uid_a})\n"
            f"- {candidate.title_b} (from page {candidate.page_uid_b})\n\n"
            f"Create a concise, unified concept page."
        )
        if hasattr(llm, "generate"):
            content = await llm.generate(prompt)
        else:
            content = f"Consolidated concept: {candidate.title_a} / {candidate.title_b}"
        return {
            "title": f"Concept: {candidate.title_a}",
            "content": content,
            "sources": [candidate.page_uid_a, candidate.page_uid_b],
            "similarity": candidate.similarity,
        }
