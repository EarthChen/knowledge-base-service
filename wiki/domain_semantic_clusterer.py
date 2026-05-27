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
_MAX_CLUSTERS = 25
_SMALL_N_THRESHOLD = 3


def _shorten_path(path: str, levels: int = 4) -> str:
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
    def _compute_infra_set(
        modules: list[tuple[str, str]],
        summaries: dict[str, dict[str, Any]],
    ) -> set[str]:
        """Count dep/caller frequency across modules; return set of infra names (>= threshold)."""
        import math

        threshold = max(3, math.ceil(len(modules) * 0.1))
        dep_count: dict[str, int] = {}
        for _repo, name in modules:
            compound_key = f"{_repo}|{name}"
            summary_data = summaries.get(compound_key, summaries.get(name))
            if not isinstance(summary_data, dict):
                continue
            seen: set[str] = set()
            for field in ("dependencies", "callers"):
                items = summary_data.get(field, [])
                if isinstance(items, list):
                    for item in items:
                        key = str(item)
                        if key not in seen:
                            seen.add(key)
                            dep_count[key] = dep_count.get(key, 0) + 1
        return {name for name, count in dep_count.items() if count >= threshold}

    @staticmethod
    def build_embedding_texts(
        modules: list[tuple[str, str]],
        summaries: dict[str, dict[str, Any]],
        paths: dict[str, str],
    ) -> list[str]:
        """Build text for each module to be embedded."""
        infra = DomainSemanticClusterer._compute_infra_set(modules, summaries)
        texts: list[str] = []
        for repo, name in modules:
            compound_key = f"{repo}|{name}"
            path = _shorten_path(paths.get(compound_key, paths.get(name, "")))
            summary_data = summaries.get(compound_key, summaries.get(name))
            if isinstance(summary_data, dict):
                summary_text = str(summary_data.get("summary_text", ""))
                methods = summary_data.get("methods") or summary_data.get("key_methods") or []
                docstring = str(summary_data.get("docstring", ""))
            elif isinstance(summary_data, str):
                summary_text = summary_data
                methods = []
                docstring = ""
            else:
                summary_text = ""
                methods = []
                docstring = ""

            # Build enrichment parts
            enrichment_parts: list[str] = []
            if summary_text:
                enrichment_parts.append(summary_text)
            if docstring:
                enrichment_parts.append(docstring)
            if methods and isinstance(methods, list):
                method_str = ", ".join(str(m) for m in methods[:10])
                enrichment_parts.append(f"methods: {method_str}")
            deps = summary_data.get("dependencies", []) if isinstance(summary_data, dict) else []
            callers_list = summary_data.get("callers", []) if isinstance(summary_data, dict) else []
            if deps and isinstance(deps, list):
                filtered_deps = [d for d in deps if str(d) not in infra]
                if filtered_deps:
                    enrichment_parts.append(f"depends: {', '.join(str(d) for d in filtered_deps[:8])}")
            if callers_list and isinstance(callers_list, list):
                filtered_callers = [c for c in callers_list if str(c) not in infra]
                if filtered_callers:
                    enrichment_parts.append(f"callers: {', '.join(str(c) for c in filtered_callers[:8])}")

            # If no enrichment at all, use method names as fallback
            if not enrichment_parts and isinstance(summary_data, dict):
                fallback_methods = summary_data.get("methods") or summary_data.get("key_methods") or []
                if fallback_methods and isinstance(fallback_methods, list):
                    enrichment_parts.append(
                        "methods: " + ", ".join(str(m) for m in fallback_methods[:10])
                    )

            enrichment = " — " + " | ".join(enrichment_parts) if enrichment_parts else ""
            texts.append(f"{name} [{path}]{enrichment}" if path else f"{name}{enrichment}")
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
        max_w = max((abs(w) for _, _, w in edges), default=1)
        max_w = max(max_w, 1)
        for src, dst, w in edges:
            i = mod_idx.get(src)
            j = mod_idx.get(dst)
            if i is not None and j is not None and i != j:
                # Weight-aware: higher weight → stronger discount (smaller distance)
                ratio = min(abs(w) / max_w, 1.0)
                max_discount = 1.0 - self._discount
                discount = 1.0 - max_discount * ratio
                dist[i, j] *= discount
                dist[j, i] *= discount
        return dist

    def _find_best_k(self, dist: np.ndarray, n: int) -> int:
        k_min = max(self._min_k, n // 15)
        k_max = min(max(k_min + 1, n // 4), self._max_k)
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
