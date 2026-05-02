"""Search operations for FalkorDB: vector, keyword, and BM25 full-text."""

from __future__ import annotations

import asyncio
from typing import Any

from core.log import get_logger
from store.falkordb_store import FalkorDBStore, QueryResultWrapper
from store.schema import NodeLabel

log = get_logger(__name__)

_DEFAULT_FULLTEXT_LABELS = ("Function", "Class", "Module", "Document")

_FULLTEXT_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Function", ("name", "fqn", "docstring", "business_summary")),
    ("Class", ("name", "fqn", "docstring", "business_summary")),
    ("Module", ("name", "fqn")),
    ("Document", ("title", "content")),
    ("Chunk", ("content",)),
    ("WikiPage", ("title", "content")),
)

_ALLOWED_FULLTEXT_LABELS: frozenset[str] = frozenset(
    lbl for lbl, _ in _FULLTEXT_INDEXES
)


def _fulltext_row_cypher(label: str) -> str:
    """CALL fulltext … YIELD node, score → RETURN row dict.

    ``label`` MUST be pre-validated against ``_ALLOWED_FULLTEXT_LABELS``.
    """
    return (
        f"CALL db.idx.fulltext.queryNodes('{label}', $q) YIELD node, score "
        "WHERE ($repo IS NULL OR node.repository = $repo) "
        "AND ($lang IS NULL OR node.language = $lang) "
        "RETURN node.uid AS uid, "
        "coalesce(node.name, node.title, '') AS name, "
        "coalesce(node.file, node.path, '') AS file, "
        "coalesce(node.start_line, 0) AS line, "
        "labels(node)[0] AS type, "
        "coalesce(node.signature, '') AS signature, "
        "coalesce(node.docstring, '') AS docstring, "
        "coalesce(node.fqn, '') AS fqn, "
        "score AS score ORDER BY score DESC LIMIT $limit"
    )


class SearchStore:
    """Encapsulates all search-related FalkorDB operations: vector, keyword, BM25."""

    def __init__(self, base_store: FalkorDBStore):
        self._store = base_store

    async def ensure_fulltext_indexes(self) -> None:
        """Create full-text indexes for BM25 search on code entities and wiki."""
        for label, props in _FULLTEXT_INDEXES:
            quoted = ", ".join(f"'{p}'" for p in props)
            cypher = f"CALL db.idx.fulltext.createNodeIndex('{label}', {quoted})"
            try:
                await self._store.execute_query(cypher)
            except Exception as exc:
                log.debug(
                    "fulltext_index_create_skipped_or_exists",
                    label=label,
                    error=str(exc),
                )

    async def fulltext_search(
        self,
        query: str,
        labels: list[str] | None = None,
        limit: int = 20,
        repository: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 full-text search across specified labels; merged and sorted by score."""
        q = (query or "").strip()
        if not q:
            return []

        raw_labels = tuple(labels) if labels else _DEFAULT_FULLTEXT_LABELS
        use_labels = [lbl for lbl in raw_labels if lbl in _ALLOWED_FULLTEXT_LABELS]
        if not use_labels:
            return []

        repo = (repository or "").strip() or None
        lang = (language or "").strip() or None
        lim = max(1, min(500, int(limit)))

        params: dict[str, Any] = {"q": q, "repo": repo, "lang": lang, "limit": lim}

        async def _search_label(lbl: str) -> list[dict[str, Any]]:
            cypher = _fulltext_row_cypher(lbl)
            try:
                result = await self._store.execute_query(cypher, params)
            except Exception as exc:
                log.warning("fulltext_search_label_failed", label=lbl, error=str(exc))
                return []
            rows: list[dict[str, Any]] = []
            for row in result.data:
                uid = row.get("uid")
                if not uid:
                    continue
                rows.append({
                    "uid": uid,
                    "name": row.get("name") or "",
                    "file": row.get("file") or "",
                    "line": row.get("line") if row.get("line") is not None else 0,
                    "type": row.get("type") or lbl,
                    "signature": row.get("signature") or "",
                    "docstring": row.get("docstring") or "",
                    "fqn": row.get("fqn") or "",
                    "score": float(row.get("score") or 0.0),
                })
            return rows

        label_results = await asyncio.gather(*[_search_label(lbl) for lbl in use_labels])

        by_uid: dict[str, dict[str, Any]] = {}
        for rows in label_results:
            for rec in rows:
                uid = rec["uid"]
                prev = by_uid.get(uid)
                if prev is None or rec["score"] > prev["score"]:
                    by_uid[uid] = rec

        merged = sorted(by_uid.values(), key=lambda r: r["score"], reverse=True)
        return merged[:lim]

    async def vector_search(
        self,
        label: NodeLabel,
        embedding: list[float],
        k: int = 10,
        attribute: str = "embedding",
        *,
        repository: str | None = None,
        language: str | None = None,
    ):
        return await self._store.vector_search(
            label,
            embedding,
            k,
            attribute,
            repository=repository,
            language=language,
        )

    async def keyword_search(
        self,
        keyword: str,
        k: int = 10,
        *,
        exact_only: bool = False,
        repository: str | None = None,
        language: str | None = None,
    ):
        return await self._store.keyword_search(
            keyword,
            k,
            exact_only=exact_only,
            repository=repository,
            language=language,
        )

    async def fetch_parent_metadata_batch(self, parent_uids: list[str]) -> QueryResultWrapper:
        """Batch-fetch signature/docstring/line-range of parent entities by UID."""
        q = (
            "UNWIND $uids AS uid "
            "MATCH (n {uid: uid}) "
            "RETURN n.uid AS uid, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring, "
            "coalesce(n.file, '') AS file, "
            "n.start_line AS start_line, n.end_line AS end_line"
        )
        return await self._store.execute_query(q, {"uids": parent_uids})
