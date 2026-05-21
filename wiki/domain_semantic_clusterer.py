"""Semantic embedding clustering for domain classification."""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score

from core.log import get_logger

log = get_logger(__name__)

_DEFAULT_CALL_GRAPH_DISCOUNT = 0.85
_MIN_CLUSTERS = 3
_MAX_CLUSTERS = 15
_SMALL_N_THRESHOLD = 10


def _shorten_path(path: str, levels: int = 2) -> str:
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return path
    dir_parts = parts[:-1]
    if len(dir_parts) <= levels:
        return "/".join(dir_parts)
    return "/".join(dir_parts[-levels:])


class DomainSemanticClusterer:
    """Cluster modules by semantic similarity of their summaries."""

    def __init__(
        self,
        call_graph_discount: float = _DEFAULT_CALL_GRAPH_DISCOUNT,
        min_clusters: int = _MIN_CLUSTERS,
        max_clusters: int = _MAX_CLUSTERS,
    ):
        self._discount = call_graph_discount
        self._min_k = min_clusters
        self._max_k = max_clusters

    @staticmethod
    def build_embedding_texts(
        modules: list[tuple[str, str]],
        summaries: dict[str, dict[str, Any]],
        paths: dict[str, str],
    ) -> list[str]:
        """Build text for each module to be embedded."""
        texts: list[str] = []
        for _repo, name in modules:
            path = _shorten_path(paths.get(name, ""))
            summary_data = summaries.get(name)
            if isinstance(summary_data, dict):
                summary_text = str(summary_data.get("summary_text", ""))
            elif isinstance(summary_data, str):
                summary_text = summary_data
            else:
                summary_text = ""
            if summary_text:
                texts.append(f"{name} [{path}] — {summary_text}")
            else:
                texts.append(f"{name} [{path}]" if path else name)
        return texts

    def _compute_cosine_distance(self, embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normalized = embeddings / norms
        similarity = normalized @ normalized.T
        np.clip(similarity, -1.0, 1.0, out=similarity)
        return 1.0 - similarity

    def _compute_distance_matrix(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    ) -> np.ndarray:
        dist = self._compute_cosine_distance(embeddings)
        if not edges:
            return dist
        mod_idx = {mod: i for i, mod in enumerate(modules)}
        for src, dst, _w in edges:
            i = mod_idx.get(src)
            j = mod_idx.get(dst)
            if i is not None and j is not None and i != j:
                dist[i, j] *= self._discount
                dist[j, i] *= self._discount
        return dist

    def _find_best_k(self, dist: np.ndarray, n: int) -> int:
        k_min = max(self._min_k, n // 20)
        k_max = min(max(k_min + 1, n // 3), self._max_k)
        if k_max <= k_min:
            return k_min
        best_k = k_min
        best_score = -1.0
        for k in range(k_min, k_max + 1):
            try:
                model = AgglomerativeClustering(
                    n_clusters=k, metric="precomputed", linkage="average"
                )
                labels = model.fit_predict(dist)
                if len(set(labels)) < 2:
                    continue
                score = silhouette_score(dist, labels, metric="precomputed")
                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                continue
        log.info("domain_clusterer_best_k", best_k=best_k, score=round(best_score, 4), n=n)
        return best_k

    def cluster(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
    ) -> list[set[tuple[str, str]]]:
        n = len(modules)
        if n < _SMALL_N_THRESHOLD:
            return [set(modules)]
        dist = self._compute_distance_matrix(embeddings, modules, edges)
        best_k = self._find_best_k(dist, n)
        model = AgglomerativeClustering(
            n_clusters=best_k, metric="precomputed", linkage="average"
        )
        labels = model.fit_predict(dist)
        clusters: dict[int, set[tuple[str, str]]] = {}
        for i, label in enumerate(labels):
            clusters.setdefault(int(label), set()).add(modules[i])
        log.info(
            "domain_semantic_cluster_done",
            n_modules=n,
            n_clusters=len(clusters),
            sizes=[len(c) for c in clusters.values()],
        )
        return list(clusters.values())

    def cluster_sub_domains(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
        max_sub: int = 5,
    ) -> list[set[tuple[str, str]]]:
        """Cluster within a domain to create sub-domains."""
        n = len(modules)
        if n <= 5:
            return [set(modules)]
        dist = self._compute_distance_matrix(embeddings, modules, edges)
        best_k = 2
        best_score = -1.0
        for k in range(2, min(max_sub + 1, n // 2 + 1)):
            try:
                model = AgglomerativeClustering(
                    n_clusters=k, metric="precomputed", linkage="average"
                )
                labels = model.fit_predict(dist)
                if len(set(labels)) < 2:
                    continue
                score = silhouette_score(dist, labels, metric="precomputed")
                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                continue
        model = AgglomerativeClustering(
            n_clusters=best_k, metric="precomputed", linkage="average"
        )
        labels = model.fit_predict(dist)
        clusters: dict[int, set[tuple[str, str]]] = {}
        for i, label in enumerate(labels):
            clusters.setdefault(int(label), set()).add(modules[i])
        return list(clusters.values())
