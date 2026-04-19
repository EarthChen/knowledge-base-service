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
    ) -> None:
        self._store = store
        self._embedding = embedding_gen
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

    async def search_all(self, query_text: str, k: int = 10) -> SemanticResult:
        """Search across all entity types and merge results by score."""
        (
            func_results,
            class_results,
            doc_results,
            flow_results,
            concept_results,
            module_results,
        ) = await asyncio.gather(
            self._search_by_label(query_text, NodeLabel.FUNCTION, k),
            self._search_by_label(query_text, NodeLabel.CLASS, k),
            self._search_by_label(query_text, NodeLabel.DOCUMENT, k),
            self._search_by_label(query_text, NodeLabel.BUSINESS_FLOW, k),
            self._search_by_label(query_text, NodeLabel.BUSINESS_CONCEPT, k),
            self._search_by_label(query_text, NodeLabel.MODULE, k),
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

    async def _search_by_label(self, query_text: str, label: NodeLabel, k: int) -> SemanticResult:
        embeddings = await self._embedding.generate_for_query([query_text])
        if not embeddings:
            return SemanticResult(query_text=query_text)

        query_vec = embeddings[0]

        try:
            results = await self._store.vector_search(label, query_vec, k)
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
                match["line"] = props.get("start_line", 0)
                match["docstring"] = props.get("docstring", "")[:200]
                match["uid"] = props.get("uid", "")
                match["fqn"] = props.get("fqn", "")
                if label == NodeLabel.FUNCTION:
                    match["signature"] = props.get("signature", "")
                elif label == NodeLabel.DOCUMENT:
                    match["content"] = props.get("content", "")[:500]
            matches.append(match)

        return SemanticResult(matches=matches, query_text=query_text, total=len(matches))
