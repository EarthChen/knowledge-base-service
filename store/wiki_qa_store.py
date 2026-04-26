"""Persistent WikiQ&A nodes and vector search (memory loop)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from store.falkordb_store import QueryResultWrapper


def _cypher_vec_literal(vec: list[float]) -> str:
    return ", ".join(str(v) for v in vec)


class WikiQaStoreMixin:
    """WikiQA node CRUD and embedding-backed similarity search."""

    async def persist_wiki_qa(
        self,
        *,
        business_id: str,
        question: str,
        answer: str,
        source_pages: list[str],
        quality_score: float,
        created_at: str,
        embedding: list[float],
    ) -> str:
        """Create a :WikiQA node with embedding. Returns the node uid."""
        uid = f"WikiQA:{business_id}:{uuid.uuid4().hex}"
        pages_json = json.dumps(source_pages, ensure_ascii=True)
        vec_lit = _cypher_vec_literal(embedding)
        q = (
            f"CREATE (q:WikiQA {{uid: $uid, business_id: $business_id, question: $question, "
            f"answer: $answer, source_pages: $source_pages, quality_score: $quality_score, created_at: $created_at, "
            f"embedding: vecf32([{vec_lit}])}}) RETURN q.uid AS uid"
        )
        r = await self._store.execute_query(
            q,
            {
                "uid": uid,
                "business_id": business_id,
                "question": question,
                "answer": answer,
                "source_pages": pages_json,
                "quality_score": float(quality_score),
                "created_at": created_at,
            },
        )
        if r.data and r.data[0].get("uid"):
            return str(r.data[0]["uid"])
        return uid

    async def search_wiki_qa(
        self, embedding: list[float], business_id: str, k: int, limit: int
    ) -> QueryResultWrapper:
        q = (
            "CALL db.idx.vector.queryNodes('WikiQA', 'embedding', $k, vecf32($vec)) "
            "YIELD node AS q, score "
            "WHERE q.business_id = $business_id "
            "RETURN q.uid AS uid, q.question AS question, q.answer AS answer, "
            "q.source_pages AS source_pages, q.quality_score AS quality_score, "
            "q.created_at AS created_at, score AS similarity "
            "ORDER BY score DESC LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"k": k, "vec": embedding, "business_id": business_id, "limit": limit},
        )

    async def list_wiki_qa(self, business_id: str, skip: int, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (q:WikiQA {business_id: $business_id}) "
            "RETURN q.uid AS uid, q.question AS question, q.answer AS answer, "
            "q.source_pages AS source_pages, q.quality_score AS quality_score, q.created_at AS created_at "
            "ORDER BY q.created_at DESC "
            "SKIP $skip LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"business_id": business_id, "skip": skip, "limit": limit},
        )

    async def count_wiki_qa(self, business_id: str) -> int:
        q = "MATCH (q:WikiQA {business_id: $business_id}) RETURN count(q) AS c"
        r = await self._store.execute_query(q, {"business_id": business_id})
        if not r.data:
            return 0
        return int(r.data[0].get("c", 0) or 0)
