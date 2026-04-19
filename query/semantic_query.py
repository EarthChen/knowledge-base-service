"""Semantic search interface — vector similarity search over code and docs.

Uses FalkorDB's vector index to find semantically similar code entities
and documentation sections based on natural language queries.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from indexer.embedding_generator import EmbeddingGenerator
from log import get_logger
from store.falkordb_store import FalkorDBStore
from store.search_store import SearchStore
from store.schema import NodeLabel

log = get_logger(__name__)


@dataclass
class SemanticResult:
    matches: list[dict[str, Any]] = field(default_factory=list)
    query_text: str = ""
    total: int = 0


class SemanticQueryService:
    """Provides semantic (vector similarity) search over the knowledge graph."""

    def __init__(
        self,
        store: FalkorDBStore,
        embedding_gen: EmbeddingGenerator,
        *,
        include_raw_docs_in_results: bool | None = None,
        search_store: SearchStore | None = None,
    ) -> None:
        self._store = store
        self._embedding = embedding_gen
        self._search = search_store or SearchStore(store)
        if include_raw_docs_in_results is None:
            try:
                from config import get_settings

                self._include_raw_docs_in_results = bool(
                    get_settings().hybrid_search.include_raw_docs_in_results,
                )
            except (ImportError, AttributeError):
                self._include_raw_docs_in_results = False
        else:
            self._include_raw_docs_in_results = bool(include_raw_docs_in_results)

    async def search_functions(self, query_text: str, k: int = 10) -> SemanticResult:
        """Find functions semantically similar to the query."""
        return await self._search_by_label(query_text, NodeLabel.FUNCTION, k)

    async def search_classes(self, query_text: str, k: int = 10) -> SemanticResult:
        """Find classes semantically similar to the query."""
        return await self._search_by_label(query_text, NodeLabel.CLASS, k)

    async def search_documents(self, query_text: str, k: int = 10) -> SemanticResult:
        """Find document sections semantically similar to the query."""
        return await self._search_by_label(query_text, NodeLabel.DOCUMENT, k)

    async def search_business_flows(self, query_text: str, k: int = 10) -> SemanticResult:
        return await self._search_by_label(query_text, NodeLabel.BUSINESS_FLOW, k)

    async def search_business_concepts(self, query_text: str, k: int = 10) -> SemanticResult:
        return await self._search_by_label(query_text, NodeLabel.BUSINESS_CONCEPT, k)

    async def search_modules(self, query_text: str, k: int = 10) -> SemanticResult:
        return await self._search_by_label(query_text, NodeLabel.MODULE, k)

    async def search_chunks(
        self,
        query_text: str,
        k: int = 15,
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> SemanticResult:
        """Search Chunk vector index for fine-grained matches."""
        return await self._search_by_label(
            query_text, NodeLabel.CHUNK, k, repository=repository, language=language,
        )

    async def search_with_parent_context(
        self,
        query_text: str,
        k: int = 10,
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> SemanticResult:
        """Search chunks first, group by parent, fetch parent metadata.

        Falls back to standard Function/Class search when no chunk hits are found.
        Returns results enriched with ``matched_excerpt`` and ``excerpt_lines``.
        """
        chunk_result = await self.search_chunks(
            query_text, k=k * 3, repository=repository, language=language,
        )

        if not chunk_result.matches:
            func_r, cls_r = await asyncio.gather(
                self._search_by_label(query_text, NodeLabel.FUNCTION, k, repository=repository, language=language),
                self._search_by_label(query_text, NodeLabel.CLASS, k, repository=repository, language=language),
            )
            all_matches = func_r.matches + cls_r.matches
            all_matches.sort(key=lambda x: x.get("score", 0), reverse=True)
            for m in all_matches:
                m.setdefault("matched_excerpt", "")
                m.setdefault("excerpt_lines", [])
            return SemanticResult(
                matches=all_matches[:k],
                query_text=query_text,
                total=min(len(all_matches), k),
            )

        grouped = self._group_chunks_by_parent(chunk_result.matches)
        valid_groups = {uid: chunks for uid, chunks in grouped.items() if uid}

        parent_meta_map = await self._fetch_parent_metadata_batch(list(valid_groups.keys()))

        enriched: list[dict[str, Any]] = []
        for parent_uid, chunks in valid_groups.items():
            best_chunk = chunks[0]
            parent_meta = parent_meta_map.get(parent_uid)

            excerpt_texts = [c["text"] for c in chunks[:3]]
            merged_excerpt = "\n---\n".join(excerpt_texts)

            line_pairs = [(c.get("start_line", 0), c.get("end_line", 0)) for c in chunks[:3]]
            excerpt_start = min(p[0] for p in line_pairs)
            excerpt_end = max(p[1] for p in line_pairs)

            entry: dict[str, Any] = {
                "type": best_chunk.get("parent_label", "Function"),
                "name": best_chunk.get("parent_name", ""),
                "file": best_chunk.get("file", ""),
                "line": excerpt_start,
                "score": best_chunk.get("score", 0.0),
                "matched_excerpt": merged_excerpt,
                "excerpt_lines": [excerpt_start, excerpt_end],
                "uid": parent_uid,
            }
            if parent_meta:
                entry["signature"] = parent_meta.get("signature", "")
                entry["docstring"] = parent_meta.get("docstring", "")[:200]
                entry["start_line"] = parent_meta.get("start_line", excerpt_start)
                entry["end_line"] = parent_meta.get("end_line", excerpt_end)
            enriched.append(entry)

        enriched.sort(key=lambda x: x.get("score", 0), reverse=True)
        return SemanticResult(
            matches=enriched[:k],
            query_text=query_text,
            total=min(len(enriched), k),
        )

    @staticmethod
    def _group_chunks_by_parent(matches: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group chunk matches by parent_uid, preserving score order within each group."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for m in matches:
            parent_uid = m.get("parent_uid", "")
            if parent_uid not in groups:
                groups[parent_uid] = []
            groups[parent_uid].append(m)
        return groups

    async def _fetch_parent_metadata_batch(self, parent_uids: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-fetch signature/docstring/line-range of parent entities by UID."""
        if not parent_uids:
            return {}
        try:
            result = await self._search.fetch_parent_metadata_batch(parent_uids)
            return {row["uid"]: row for row in result.data if row.get("uid")}
        except Exception:
            log.debug("parent_metadata_batch_fetch_failed", count=len(parent_uids), exc_info=True)
            return {}

    async def search_all(
        self,
        query_text: str,
        k: int = 10,
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> SemanticResult:
        """Search across all entity types and merge results by score."""
        fkw = {"repository": repository, "language": language}
        (
            func_results,
            class_results,
            doc_results,
            flow_results,
            concept_results,
            module_results,
        ) = await asyncio.gather(
            self._search_by_label(query_text, NodeLabel.FUNCTION, k, **fkw),
            self._search_by_label(query_text, NodeLabel.CLASS, k, **fkw),
            self._search_by_label(query_text, NodeLabel.DOCUMENT, k, **fkw),
            self._search_by_label(query_text, NodeLabel.BUSINESS_FLOW, k, **fkw),
            self._search_by_label(query_text, NodeLabel.BUSINESS_CONCEPT, k, **fkw),
            self._search_by_label(query_text, NodeLabel.MODULE, k, **fkw),
        )

        doc_hits = doc_results.matches if self._include_raw_docs_in_results else []
        all_matches = (
            func_results.matches
            + class_results.matches
            + doc_hits
            + flow_results.matches
            + concept_results.matches
            + module_results.matches
        )
        all_matches.sort(key=lambda x: x.get("score", 0), reverse=True)
        top_matches = all_matches[:k]

        return SemanticResult(
            matches=top_matches,
            query_text=query_text,
            total=len(top_matches),
        )

    async def _search_by_label(
        self,
        query_text: str,
        label: NodeLabel,
        k: int,
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> SemanticResult:
        embeddings = await self._embedding.generate_for_query([query_text])
        if not embeddings:
            return SemanticResult(query_text=query_text)

        query_vec = embeddings[0]

        try:
            results = await self._store.vector_search(
                label, query_vec, k, repository=repository, language=language,
            )
        except Exception as exc:
            log.warning("vector_search_error", label=label, error=str(exc))
            return SemanticResult(query_text=query_text)

        matches = []
        for node, score in results:
            match: dict[str, Any] = {
                "type": str(label),
                "score": float(score),
            }
            if hasattr(node, "properties"):
                props = node.properties
                match["name"] = props.get("name", "")
                match["file"] = props.get("file", "")
                _sl = props.get("start_line") or 0
                _el = props.get("end_line") or _sl
                match["line"] = _sl
                match["start_line"] = _sl
                match["end_line"] = _el
                match["uid"] = props.get("uid", "")
                if label == NodeLabel.CHUNK:
                    match["text"] = props.get("text", "")
                    match["parent_uid"] = props.get("parent_uid", "")
                    match["parent_name"] = props.get("parent_name", "")
                    match["parent_label"] = props.get("parent_label", "")
                    match["chunk_index"] = props.get("chunk_index", 0)
                else:
                    match["docstring"] = props.get("docstring", "")[:200]
                    match["fqn"] = props.get("fqn", "")
                    if label == NodeLabel.FUNCTION:
                        match["signature"] = props.get("signature", "")
                    elif label == NodeLabel.DOCUMENT:
                        match["content"] = props.get("content", "")[:500]
                match["repository"] = props.get("repository", "")
                match["commit_sha"] = props.get("commit_sha")
                match["indexed_at"] = props.get("indexed_at")
            matches.append(match)

        return SemanticResult(matches=matches, query_text=query_text, total=len(matches))
