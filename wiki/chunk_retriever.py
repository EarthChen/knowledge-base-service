"""Semantic code chunk retrieval for wiki context enrichment."""

from __future__ import annotations

import logging
from typing import Any

from config import EmbeddingConfig
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from store.schema import GraphNode
from wiki.models import ChunkSnippet

logger = logging.getLogger(__name__)


class ChunkRetriever:
    """Retrieves semantically related code chunks for a given entity."""

    def __init__(
        self,
        wiki_store: Any,
        embedding_config: EmbeddingConfig,
        top_k: int = 5,
        min_score: float = 0.3,
        exclude_same_parent: bool = True,
    ) -> None:
        self._store = wiki_store
        self._embedding_config = embedding_config
        self._top_k = top_k
        self._min_score = min_score
        self._exclude_same_parent = exclude_same_parent

    async def retrieve(
        self,
        node: GraphNode,
        repository: str,
        exclude_uids: set[str] | None = None,
    ) -> list[ChunkSnippet]:
        query_text = self._build_query_text(node)
        if not query_text:
            return []

        emb_gen = EmbeddingGenerator.shared(config=self._embedding_config)
        query_docs = [doc_dict_for_embedding({"title": "", "content": query_text})]
        embeddings = await emb_gen.generate_for_docs(query_docs)
        if not embeddings or not embeddings[0]:
            return []

        result = await self._store.vector_search_chunks(
            k=self._top_k * 2,
            vec=embeddings[0],
            repository=repository,
            limit=self._top_k * 2,
        )
        if not result or not result.result_set:
            return []

        exclude = exclude_uids or set()
        snippets: list[ChunkSnippet] = []

        for row in result.result_set:
            text, file_path, start_line, end_line, parent_uid, parent_name, score = row
            score_f = float(score)

            if score_f < self._min_score:
                continue
            if self._exclude_same_parent and str(parent_uid) == node.uid:
                continue
            if str(parent_uid) in exclude:
                continue

            snippets.append(ChunkSnippet(
                text=str(text),
                file_path=str(file_path),
                score=score_f,
                parent_name=str(parent_name or ""),
                parent_uid=str(parent_uid or ""),
                start_line=int(start_line or 0),
                end_line=int(end_line or 0),
            ))

            if len(snippets) >= self._top_k:
                break

        return snippets

    def _build_query_text(self, node: GraphNode) -> str:
        parts: list[str] = []
        name = node.properties.get("name")
        if isinstance(name, str) and name:
            parts.append(name)
        fqn = node.properties.get("fqn")
        if isinstance(fqn, str) and fqn:
            parts.append(fqn)
        sig = node.properties.get("signature")
        if isinstance(sig, str) and sig:
            parts.append(sig)
        doc = node.properties.get("docstring")
        if isinstance(doc, str) and doc:
            parts.append(doc[:200])
        return " ".join(parts)
