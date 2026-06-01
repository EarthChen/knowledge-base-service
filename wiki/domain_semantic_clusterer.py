"""Semantic embedding clustering for domain classification."""
from __future__ import annotations

import re
from collections import Counter
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


_COMMON_PREFIXES = frozenset({"relation", "user", "ultron", "basic", "common", "core", "base"})
_SKIP_CAMEL_PREFIXES = frozenset({"i", "abstract", "base", "default", "mock", "test"})
_GENERIC_NAMES = frozenset({"service", "dao", "handler", "consumer", "producer", "controller", "manager"})


def _prefix_from_kebab(slug: str) -> str | None:
    """Extract first business segment from kebab-case slug."""
    parts = slug.split("-")
    for part in parts:
        if part and part not in _COMMON_PREFIXES and part not in _GENERIC_NAMES:
            return part.lower()
    return None


def _prefix_from_camel(name: str) -> str | None:
    """Extract first business word from CamelCase name."""
    words = re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", name)
    for word in words:
        lower = word.lower()
        if lower not in _SKIP_CAMEL_PREFIXES and lower not in _GENERIC_NAMES and len(lower) > 2:
            return lower
    return None


def _extract_business_prefix(module_name: str, path: str | None) -> str | None:
    """Extract business prefix token from module name or path.

    Tries path-based slug first (kebab-case), falls back to CamelCase parsing.
    Returns None if no meaningful business prefix can be extracted.
    """
    if not module_name:
        return None

    if path:
        slug = path.replace("\\", "/").split("/")[-1] if "/" in path else ""
        if slug and "-" in slug:
            prefix = _prefix_from_kebab(slug)
            if prefix:
                return prefix

    if "-" in module_name:
        prefix = _prefix_from_kebab(module_name)
        if prefix:
            return prefix

    if any(c.isupper() for c in module_name[1:]):
        prefix = _prefix_from_camel(module_name)
        if prefix:
            return prefix

    return None


def _business_dir_from_path(module_path: str) -> str:
    """Extract first non-generic directory segment from a file path."""
    if not module_path or "/" not in module_path:
        return ""
    module_dir = module_path.replace("\\", "/").rsplit("/", 1)[0]
    return _business_dir_from_dir(module_dir)


def _business_dir_from_dir(module_dir: str) -> str:
    skip = {"src", "main", "java", "com", "kotlin", "python", "lib", "internal", "pkg"}
    for part in module_dir.replace("\\", "/").split("/"):
        if part.lower() not in skip and part:
            return part.lower()
    return ""


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

    def _apply_prefix_penalty(
        self,
        dist: np.ndarray,
        modules: list[tuple[str, str]],
        paths: dict[str, str],
        penalty_factor: float = 1.3,
    ) -> np.ndarray:
        prefixes: list[str | None] = []
        for repo, name in modules:
            compound_key = f"{repo}|{name}"
            path = paths.get(compound_key, paths.get(name))
            prefixes.append(_extract_business_prefix(name, path))

        n = len(modules)
        for i in range(n):
            pi = prefixes[i]
            if pi is None:
                continue
            for j in range(i + 1, n):
                pj = prefixes[j]
                if pj is None or pi == pj:
                    continue
                dist[i, j] *= penalty_factor
                dist[j, i] *= penalty_factor
        return dist

    def _apply_prefix_cannot_link(
        self,
        dist_matrix: np.ndarray,
        modules: list[tuple[str, str]],
        paths: dict[str, str] | None = None,
    ) -> np.ndarray:
        """Apply cannot-link constraints for modules with different business prefixes.

        This is stronger than prefix_penalty — it makes cross-prefix merging impossible
        by setting distance to 2.0 (maximum).
        """
        if not paths:
            return dist_matrix

        n = len(modules)
        prefix_map: dict[int, str | None] = {}
        for i, mod in enumerate(modules):
            compound_key = f"{mod[0]}|{mod[1]}"
            path = paths.get(compound_key, paths.get(mod[1]))
            prefix_map[i] = _extract_business_prefix(mod[1], path)

        for i in range(n):
            pi = prefix_map[i]
            if pi is None:
                continue
            for j in range(i + 1, n):
                pj = prefix_map[j]
                if pj is None:
                    continue
                if pi != pj:
                    dist_matrix[i, j] = 2.0
                    dist_matrix[j, i] = 2.0

        return dist_matrix

    def _apply_anchor_constraints(
        self,
        dist_matrix: np.ndarray,
        modules: list[tuple[str, str]],
        pinned_domains: dict[tuple[str, str], str],
    ) -> np.ndarray:
        """Apply cannot-link constraints for modules pinned to different domains.

        If module A is pinned to domain X and module B is pinned to domain Y (X≠Y),
        set dist[i,j] = dist[j,i] = 2.0 (maximum distance, cannot link).
        Same domain → no change.
        """
        if not pinned_domains:
            return dist_matrix

        n = len(modules)
        for i in range(n):
            domain_i = pinned_domains.get(modules[i])
            if domain_i is None:
                continue
            for j in range(i + 1, n):
                domain_j = pinned_domains.get(modules[j])
                if domain_j is None:
                    continue
                if domain_i != domain_j:
                    dist_matrix[i, j] = 2.0
                    dist_matrix[j, i] = 2.0

        return dist_matrix

    def _review_cluster_placement(
        self,
        clusters: list[set[tuple[str, str]]],
        modules: list[tuple[str, str]],
        paths: dict[str, str],
    ) -> list[set[tuple[str, str]]]:
        if len(clusters) <= 1:
            return clusters

        prefix_map: dict[tuple[str, str], str | None] = {}
        for repo, name in modules:
            compound_key = f"{repo}|{name}"
            path = paths.get(compound_key, paths.get(name))
            prefix_map[(repo, name)] = _extract_business_prefix(name, path)

        cluster_list = [set(c) for c in clusters]

        def dominant_prefix(cluster: set[tuple[str, str]]) -> str | None:
            prefixes = [prefix_map[m] for m in cluster if prefix_map.get(m) is not None]
            if not prefixes:
                return None
            top_prefix, count = Counter(prefixes).most_common(1)[0]
            if count / len(prefixes) > 0.5:
                return top_prefix
            return None

        dominants = [dominant_prefix(c) for c in cluster_list]
        reparents: list[tuple[tuple[str, str], int, int]] = []

        for ci, cluster in enumerate(cluster_list):
            cluster_dom = dominants[ci]
            if cluster_dom is None:
                continue
            for module in list(cluster):
                mod_prefix = prefix_map.get(module)
                if mod_prefix is None or mod_prefix == cluster_dom:
                    continue
                target_idx = next(
                    (tj for tj, target_dom in enumerate(dominants) if target_dom == mod_prefix),
                    None,
                )
                if target_idx is not None:
                    reparents.append((module, ci, target_idx))

        for module, from_idx, to_idx in reparents:
            cluster_list[from_idx].discard(module)
            cluster_list[to_idx].add(module)
            log.info(
                "prefix_review_reparent",
                module=f"{module[0]}|{module[1]}",
                from_cluster=from_idx,
                to_cluster=to_idx,
                module_prefix=prefix_map[module],
            )

        return [c for c in cluster_list if c]

    def _compute_distance_matrix(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
        paths: dict[str, str] | None = None,
        prefix_penalty_factor: float = 2.0,
    ) -> np.ndarray:
        dist = self._compute_cosine_distance(embeddings)
        if edges:
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
        if prefix_penalty_factor > 1.0 and paths is not None:
            dist = self._apply_prefix_penalty(
                dist, modules, paths, penalty_factor=prefix_penalty_factor
            )
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
        paths: dict[str, str] | None = None,
        prefix_penalty_factor: float = 2.0,
        pinned_domains: dict[tuple[str, str], str] | None = None,
        enable_prefix_cannot_link: bool = True,
    ) -> list[set[tuple[str, str]]]:
        n = len(modules)
        if n < _SMALL_N_THRESHOLD:
            return [set(modules)]
        dist = self._compute_distance_matrix(
            embeddings, modules, edges, paths=paths, prefix_penalty_factor=prefix_penalty_factor
        )
        if pinned_domains:
            dist = self._apply_anchor_constraints(dist, modules, pinned_domains)
        if enable_prefix_cannot_link and paths is not None:
            dist = self._apply_prefix_cannot_link(dist, modules, paths)
        best_k = self._find_best_k(dist, n)
        model = AgglomerativeClustering(
            n_clusters=best_k, metric="precomputed", linkage="average"
        )
        labels = model.fit_predict(dist)
        clusters: dict[int, set[tuple[str, str]]] = {}
        for i, label in enumerate(labels):
            clusters.setdefault(int(label), set()).add(modules[i])
        cluster_list = list(clusters.values())
        if paths:
            cluster_list = self._review_cluster_placement(cluster_list, modules, paths)
        cluster_list = self._post_cluster_reparent(cluster_list, edges, paths or {})
        log.info(
            "domain_semantic_cluster_done",
            n_modules=n,
            n_clusters=len(cluster_list),
            sizes=[len(c) for c in cluster_list],
        )
        return cluster_list

    def cluster_sub_domains(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
        max_sub: int = 5,
        paths: dict[str, str] | None = None,
        prefix_penalty_factor: float = 2.0,
        enable_prefix_cannot_link: bool = True,
    ) -> list[set[tuple[str, str]]]:
        """Cluster within a domain to create sub-domains."""
        n = len(modules)
        if n <= 5:
            return [set(modules)]
        dist = self._compute_distance_matrix(
            embeddings, modules, edges, paths=paths, prefix_penalty_factor=prefix_penalty_factor
        )
        if enable_prefix_cannot_link and paths:
            dist = self._apply_prefix_cannot_link(dist, modules, paths)
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
        cluster_list = list(clusters.values())
        if paths:
            cluster_list = self._review_cluster_placement(cluster_list, modules, paths)
        return cluster_list

    def _path_matches_cluster(
        self,
        module_path: str,
        cluster: set[tuple[str, str]],
        paths: dict[str, str],
    ) -> bool:
        """Check if a module's path shares directory affinity with a cluster's majority path."""
        if not module_path:
            return False

        cluster_dirs: list[str] = []
        for _repo, name in cluster:
            compound = f"{_repo}|{name}"
            p = paths.get(compound, paths.get(name, ""))
            if p and "/" in p:
                cluster_dirs.append(p.replace("\\", "/").rsplit("/", 1)[0])

        if not cluster_dirs:
            return False

        module_biz = _business_dir_from_path(module_path)
        if not module_biz:
            return False

        cluster_biz = [_business_dir_from_dir(d) for d in cluster_dirs]
        cluster_biz = [b for b in cluster_biz if b]
        if not cluster_biz:
            return False

        counter = Counter(cluster_biz)
        dominant, count = counter.most_common(1)[0]
        # Module path must match the cluster's dominant business directory
        return module_biz == dominant and count / len(cluster_biz) > 0.5

    def _post_cluster_reparent(
        self,
        clusters: list[set[tuple[str, str]]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
        paths: dict[str, str],
    ) -> list[set[tuple[str, str]]]:
        """Post-cluster validation: reparent modules with double-confirm (prefix + path).

        A module is reparented only when BOTH conditions are met:
        1. Its name prefix diverges from its current cluster's dominant prefix
        2. Its file path has affinity with a different cluster
        """
        if len(clusters) <= 1:
            return clusters

        cluster_list = [set(c) for c in clusters]

        # Compute dominant prefix per cluster
        def _dominant_prefix(cluster: set[tuple[str, str]]) -> str | None:
            prefixes: list[str] = []
            for _repo, name in cluster:
                prefix = _prefix_from_camel(name)
                if prefix:
                    prefixes.append(prefix)
            if not prefixes:
                return None
            from collections import Counter

            top, count = Counter(prefixes).most_common(1)[0]
            return top if count / len(prefixes) > 0.5 else None

        dominants = [_dominant_prefix(c) for c in cluster_list]
        reparents: list[tuple[tuple[str, str], int, int]] = []

        for ci, cluster in enumerate(cluster_list):
            cluster_dom = dominants[ci]
            if cluster_dom is None:
                continue
            for module in list(cluster):
                _repo, name = module
                mod_prefix = _prefix_from_camel(name)
                compound = f"{_repo}|{name}"
                mod_path = paths.get(compound, paths.get(name, ""))
                path_prefix = _business_dir_from_path(mod_path)
                effective_prefix = path_prefix if path_prefix and path_prefix != mod_prefix else mod_prefix
                if effective_prefix is None or effective_prefix == cluster_dom:
                    continue

                # Condition 1 met: prefix diverges
                # Now check condition 2: path affinity with another cluster
                for tj, target_cluster in enumerate(cluster_list):
                    if tj == ci:
                        continue
                    if self._path_matches_cluster(mod_path, target_cluster, paths):
                        reparents.append((module, ci, tj))
                        break

        for module, from_idx, to_idx in reparents:
            cluster_list[from_idx].discard(module)
            cluster_list[to_idx].add(module)
            log.info(
                "post_cluster_reparent",
                module=f"{module[0]}|{module[1]}",
                from_cluster=from_idx,
                to_cluster=to_idx,
            )

        return [c for c in cluster_list if c]
