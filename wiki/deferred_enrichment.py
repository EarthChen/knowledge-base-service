"""Wiki-stage batch enrichment for entities missing ``business_summary``."""

from __future__ import annotations

from typing import Any

from indexer.enrichment import CodeSummaryEnricher, is_trivial_enrichment_entity
from indexer.embedding_generator import EmbeddingGenerator
from store.falkordb_store import FalkorDBStore, QueryResultWrapper
from store.schema import NodeLabel


class DeferredEnrichmentService:
    """Batch-completes business_summary for entities missing it before wiki generation."""

    def __init__(
        self,
        store: FalkorDBStore,
        enricher: CodeSummaryEnricher,
        embedding_gen: EmbeddingGenerator | None = None,
    ) -> None:
        self._store = store
        self._enricher = enricher
        self._embedding = embedding_gen

    def _query_rows(self, result: QueryResultWrapper) -> list[list[Any]]:
        return list(result.raw or [])

    async def enrich_remaining(self, repository: str) -> int:
        """Find all Function/Class without business_summary, batch enrich, and backfill."""
        unenriched = await self._find_unenriched_entities(repository)
        items = [it for it in unenriched if not is_trivial_enrichment_entity(it)]
        if not items:
            return 0
        summaries = await self._enricher.enrich_batch(items)
        count = 0
        for item, summary in zip(items, summaries, strict=True):
            if summary:
                label = NodeLabel.FUNCTION if item.get("entity_kind") == "function" else NodeLabel.CLASS
                await self._store.update_node_property(label, item["uid"], "business_summary", summary)
                count += 1
        return count

    async def refresh_stale_embeddings(self, repository: str) -> int:
        """Re-embed entities that gained business_summary after wiki-stage enrichment."""
        if not self._embedding:
            return 0
        stale = await self._find_newly_enriched(repository)
        if not stale:
            return 0
        items = [
            {
                "name": n["name"],
                "signature": n.get("signature", ""),
                "docstring": n.get("docstring", ""),
                "code_snippet": n.get("code_snippet", ""),
                "business_summary": n.get("business_summary", ""),
            }
            for n in stale
        ]
        embeddings = await self._embedding.generate_for_code(items)
        for node_info, emb in zip(stale, embeddings, strict=True):
            label = NodeLabel.FUNCTION if node_info.get("label") == "Function" else NodeLabel.CLASS
            await self._store.set_node_embedding(node_info["uid"], label, emb)
        return len(stale)

    async def _find_unenriched_entities(self, repository: str) -> list[dict[str, Any]]:
        """Query graph for Function/Class nodes missing business_summary."""
        q = (
            "MATCH (n) WHERE (n:Function OR n:Class) "
            "AND n.repository = $repo "
            "AND (n.business_summary IS NULL OR n.business_summary = '') "
            "RETURN n.uid AS uid, n.name AS name, n.signature AS signature, "
            "n.docstring AS docstring, n.code_snippet AS code_snippet, "
            "n.file AS file, labels(n)[0] AS label"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        rows: list[dict[str, Any]] = []
        for row in self._query_rows(result):
            lbl = row[6] if len(row) > 6 else "Function"
            lbl_s = str(lbl) if lbl is not None else "Function"
            rows.append(
                {
                    "uid": row[0],
                    "name": row[1] or "",
                    "signature": row[2] or "",
                    "docstring": row[3] or "",
                    "code_snippet": row[4] or "",
                    "file": row[5] or "",
                    "entity_kind": "function" if lbl_s == "Function" else "class",
                },
            )
        return rows

    async def _find_newly_enriched(self, repository: str) -> list[dict[str, Any]]:
        """Find entities that got business_summary but need embedding refresh."""
        q = (
            "MATCH (n) WHERE (n:Function OR n:Class) "
            "AND n.repository = $repo "
            "AND n.business_summary IS NOT NULL AND n.business_summary <> '' "
            "AND (n.embedding IS NULL) "
            "RETURN n.uid AS uid, n.name AS name, n.business_summary AS summary, "
            "n.code_snippet AS code, n.signature AS sig, n.docstring AS doc, "
            "labels(n)[0] AS label"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        rows: list[dict[str, Any]] = []
        for row in self._query_rows(result):
            lbl = row[6] if len(row) > 6 else "Function"
            lbl_s = str(lbl) if lbl is not None else "Function"
            rows.append(
                {
                    "uid": row[0],
                    "name": row[1] or "",
                    "business_summary": row[2] or "",
                    "code_snippet": row[3] or "",
                    "signature": row[4] or "",
                    "docstring": row[5] or "",
                    "label": lbl_s,
                },
            )
        return rows
