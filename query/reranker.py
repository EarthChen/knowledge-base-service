"""Cross-encoder reranking module for search result refinement."""

from __future__ import annotations

import logging
from typing import Any

from config import RerankConfig

logger = logging.getLogger(__name__)


class Reranker:
    """Cross-encoder reranker using a lightweight model (not LLM)."""

    def __init__(self, config: RerankConfig) -> None:
        self._config = config
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None or not self._config.enabled:
            return
        try:
            from sentence_transformers import CrossEncoder

            device = self._config.device
            if device == "auto":
                import torch

                device = (
                    "mps"
                    if torch.backends.mps.is_available()
                    else ("cuda" if torch.cuda.is_available() else "cpu")
                )
            self._model = CrossEncoder(self._config.model_name, device=device)
            logger.info("Loaded reranker model: %s on %s", self._config.model_name, device)
        except Exception:
            logger.warning("Failed to load reranker model, disabling reranking", exc_info=True)
            self._config.enabled = False

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Rerank candidates by cross-encoder score. Returns top_k results."""
        if not self._config.enabled or not candidates:
            return candidates[:top_k]

        self._ensure_model()
        if self._model is None:
            return candidates[:top_k]

        texts = [self._candidate_text(c) for c in candidates]
        scores = self._compute_scores(query, texts)

        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored[:top_k]]

    def _compute_scores(self, query: str, texts: list[str]) -> list[float]:
        pairs = [(query, t) for t in texts]
        return self._model.predict(pairs, batch_size=self._config.batch_size).tolist()

    @staticmethod
    def _candidate_text(candidate: dict[str, Any]) -> str:
        parts = []
        if candidate.get("business_summary"):
            parts.append(candidate["business_summary"])
        if candidate.get("name"):
            parts.append(candidate["name"])
        if candidate.get("signature"):
            parts.append(candidate["signature"])
        if candidate.get("docstring"):
            parts.append(candidate["docstring"][:200])
        if candidate.get("description"):
            parts.append(candidate["description"][:200])
        return " ".join(parts) if parts else candidate.get("name", "")
