"""Persistent WikiQ&A nodes and vector search (memory loop)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from store.falkordb_store import QueryResultWrapper


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
        # Pass embedding as a query parameter (same pattern as search_wiki_qa: vecf32($vec)).
        # set_node_embedding uses string interpolation because that path only receives uid as a param;
        # here the full vector is a single parameter list.
        q = (
            "CREATE (q:WikiQA {uid: $uid, business_id: $business_id, question: $question, "
            "answer: $answer, source_pages: $source_pages, quality_score: $quality_score, created_at: $created_at, "
            "tier: $tier, memory_status: $memory_status, access_count: $access_count, "
            "confirmation_count: $confirmation_count, confidence: $confidence, "
            "embedding: vecf32($embedding)}) RETURN q.uid AS uid"
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
                "tier": 0,
                "memory_status": "active",
                "access_count": 0,
                "confirmation_count": 0,
                "confidence": 0.0,
                "embedding": embedding,
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
            "q.created_at AS created_at, coalesce(q.tier, 1) AS tier, "
            "coalesce(q.memory_status, 'active') AS memory_status, "
            "coalesce(q.confidence, 0.0) AS confidence, "
            "coalesce(q.access_count, 0) AS access_count, "
            "coalesce(q.confirmation_count, 0) AS confirmation_count, "
            "coalesce(q.last_accessed, '') AS last_accessed, "
            "coalesce(q.promoted_at, '') AS promoted_at, "
            "coalesce(q.stability_factor, 7.0) AS stability_factor, "
            "score AS similarity "
            "ORDER BY score DESC LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"k": k, "vec": embedding, "business_id": business_id, "limit": limit},
        )

    async def list_wiki_qa(self, business_id: str, skip: int, limit: int) -> QueryResultWrapper:
        q = (
            "MATCH (q:WikiQA {business_id: $business_id}) "
            "RETURN q.uid AS uid, q.question AS question, q.answer AS answer, "
            "q.source_pages AS source_pages, q.quality_score AS quality_score, q.created_at AS created_at, "
            "coalesce(q.tier, 1) AS tier, coalesce(q.memory_status, 'active') AS memory_status, "
            "coalesce(q.confidence, 0.0) AS confidence, "
            "coalesce(q.access_count, 0) AS access_count, "
            "coalesce(q.confirmation_count, 0) AS confirmation_count, "
            "coalesce(q.last_accessed, '') AS last_accessed, "
            "coalesce(q.promoted_at, '') AS promoted_at, "
            "coalesce(q.stability_factor, 7.0) AS stability_factor "
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
