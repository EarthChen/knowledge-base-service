"""Batch generates embeddings for Chunk nodes to enable RAG retrieval."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.config import EmbeddingConfig
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from store.schema import NodeLabel

logger = logging.getLogger(__name__)


class CodeChunkIndexer:
    """Indexes Chunk nodes with vector embeddings for semantic search."""

    def __init__(
        self,
        wiki_store: Any,
        store: Any,
        embedding_config: EmbeddingConfig,
        chunk_embedding_max_length: int,
        batch_size: int = 64,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self._wiki_store = wiki_store
        self._store = store
        self._embedding_config = embedding_config
        self._chunk_embedding_max_length = chunk_embedding_max_length
        self._batch_size = batch_size
        self._on_progress = on_progress

    async def index_all_chunks(self, repository: str) -> dict[str, int]:
        count_result = await self._wiki_store.count_chunks_without_embedding(repository)
        total = 0
        if count_result and count_result.result_set:
            total = int(count_result.result_set[0][0])

        if total == 0:
            logger.info("chunk_index_skip: repo=%s reason=no unembedded chunks", repository)
            return {"total": 0, "indexed": 0, "skipped": 0, "errors": 0}

        logger.info("chunk_index_start: repo=%s total=%d", repository, total)

        emb_gen = EmbeddingGenerator.shared(config=self._embedding_config)
        indexed = 0
        skipped = 0
        errors = 0

        while True:
            # Always offset=0: successfully embedded chunks drop out of the
            # `WHERE c.embedding IS NULL` filter, so the next batch is
            # automatically the "next page".  Only skip-only batches (all
            # empty text) need a safety valve to avoid infinite loops.
            batch_result = await self._wiki_store.batch_get_chunks_for_embedding(
                repository, self._batch_size, 0,
            )
            if not batch_result or not batch_result.result_set:
                break

            uids: list[str] = []
            docs: list[dict[str, str]] = []

            for row in batch_result.result_set:
                uid, text = row[0], row[1]
                if not text or not str(text).strip():
                    skipped += 1
                    continue
                uids.append(str(uid))
                text_str = str(text)
                max_len = self._chunk_embedding_max_length
                if len(text_str) > max_len * 4:
                    text_str = text_str[: max_len * 4]
                docs.append(doc_dict_for_embedding({"title": "", "content": text_str}))

            if not docs:
                break

            try:
                embeddings = await emb_gen.generate_for_docs(docs)
                for uid, embedding in zip(uids, embeddings, strict=True):
                    await self._store.set_node_embedding(uid, NodeLabel.CHUNK, embedding)
                    indexed += 1
            except Exception:
                logger.warning("chunk_index_batch_error: indexed=%d", indexed, exc_info=True)
                errors += len(docs)
                break

            if self._on_progress:
                self._on_progress(indexed + skipped + errors, total)

        logger.info(
            "chunk_index_complete: repo=%s indexed=%d skipped=%d errors=%d",
            repository, indexed, skipped, errors,
        )
        return {"total": total, "indexed": indexed, "skipped": skipped, "errors": errors}
