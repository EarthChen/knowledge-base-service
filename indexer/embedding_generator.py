"""Embedding generator for code snippets and documents.

Uses sentence-transformers to generate dense vector embeddings
for semantic search over code and documentation.
Default model: nomic-ai/CodeRankEmbed (code retrieval SOTA, 137M params, 8192 context).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from config import EmbeddingConfig
from log import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = get_logger(__name__)


def _format_code_text(name: str, signature: str, docstring: str, code_snippet: str) -> str:
    """Build a concise textual representation for embedding."""
    parts = []
    if name:
        parts.append(f"Name: {name}")
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring:
        parts.append(f"Description: {docstring[:500]}")
    if code_snippet:
        parts.append(f"Code: {code_snippet[:1000]}")
    return "\n".join(parts)


class EmbeddingGenerator:
    """Generates embeddings using a sentence-transformers model.

    Supports query_prefix for models that require task-specific instruction
    prefixes (e.g. CodeRankEmbed requires "Represent this query for searching
    relevant code: " for query texts, while document/code texts are encoded
    without prefix).
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            device = self._config.resolve_device()
            log.info("loading_embedding_model", model=self._config.model_name, device=device)
            self._model = SentenceTransformer(
                self._config.model_name,
                device=device,
                trust_remote_code=self._config.trust_remote_code,
            )
            log.info("embedding_model_loaded", dimension=self._config.dimension, device=device)
        return self._model

    async def generate(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: Texts to embed.
            is_query: If True, prepend query_prefix to each text
                      (required by models like CodeRankEmbed).
        """
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._encode_batch, texts, is_query)

    def _encode_batch(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        model = self._load_model()
        if is_query and self._config.query_prefix:
            texts = [f"{self._config.query_prefix}{t}" for t in texts]
        embeddings = model.encode(
            texts,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [emb.tolist() for emb in embeddings]

    async def generate_for_query(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for search queries (with instruction prefix)."""
        return await self.generate(texts, is_query=True)

    async def generate_for_code(
        self,
        items: list[dict[str, str]],
    ) -> list[list[float]]:
        """Generate embeddings for code items (functions/classes).

        Each item should have keys: name, signature, docstring, code_snippet.
        Documents/code are encoded without query prefix.
        """
        texts = [
            _format_code_text(
                item.get("name", ""),
                item.get("signature", ""),
                item.get("docstring", ""),
                item.get("code_snippet", ""),
            )
            for item in items
        ]
        return await self.generate(texts, is_query=False)

    @property
    def dimension(self) -> int:
        return self._config.dimension
