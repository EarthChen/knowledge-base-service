# Semantic Embedding Domain Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Louvain topology-based domain grouping with semantic embedding clustering on module summaries, improving domain classification accuracy.

**Architecture:** Module summaries (from `compose_leaf_modules`) are embedded via `EmbeddingGenerator`, clustered using HAC with call-graph distance adjustment, then named and refined by LLM. The pipeline is reordered so `classify_domains` runs after `compose_leaf_modules`.

**Tech Stack:** Python 3.12+, scikit-learn (HAC + silhouette), existing EmbeddingGenerator (bge-m3/HTTP), LangGraph pipeline

**Spec:** `docs/superpowers/specs/2026-05-21-semantic-embedding-domain-classification-design.md`

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|---------------|
| `wiki/domain_semantic_clusterer.py` | **Create** | Embedding → distance matrix → HAC clustering core |
| `wiki/graph_domain_namer.py` | **Modify** | Accept `module_infos` (name+path+summary) instead of `module_names` |
| `wiki/graph_semantic_corrector.py` | **Modify** | Add `review_global_consistency()`, remove old methods from node usage |
| `wiki/nodes/graph_domain_decompose.py` | **Modify** | Replace Louvain with embedding clustering flow |
| `wiki/pipeline_graph.py` | **Modify** | Reorder nodes: `compose_leaf_modules` before `classify_domains` |
| `pyproject.toml` | **Modify** | Add `scikit-learn>=1.4` dependency |
| `tests/wiki/test_domain_semantic_clusterer.py` | **Create** | Unit tests for clustering |
| `tests/wiki/test_graph_domain_namer.py` | **Modify** | Tests for enhanced namer interface |
| `tests/wiki/test_graph_semantic_corrector.py` | **Modify** | Tests for `review_global_consistency()` |
| `tests/wiki/test_pipeline_domain_integration.py` | **Modify** | Integration test with new flow |

---

### Task 1: Add scikit-learn dependency

**Files:**
- Modify: `pyproject.toml:33`

- [ ] **Step 1: Add scikit-learn to dependencies**

In `pyproject.toml`, add `scikit-learn>=1.4` to the `dependencies` list:

```toml
    "networkx>=3.2",
    "scikit-learn>=1.4",
]
```

- [ ] **Step 2: Install and verify**

Run: `uv sync`
Expected: Successful install with scikit-learn added

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "from sklearn.cluster import AgglomerativeClustering; from sklearn.metrics import silhouette_score; print('OK')"`
Expected: `OK`

---

### Task 2: Create DomainSemanticClusterer — Tests

**Files:**
- Create: `tests/wiki/test_domain_semantic_clusterer.py`

- [ ] **Step 1: Write unit tests for DomainSemanticClusterer**

```python
"""Tests for DomainSemanticClusterer."""

import pytest
import numpy as np

from wiki.domain_semantic_clusterer import DomainSemanticClusterer


class TestDistanceMatrix:
    def test_cosine_distance_identical_vectors(self):
        embeddings = np.array([[1.0, 0.0], [1.0, 0.0]])
        clusterer = DomainSemanticClusterer()
        dist = clusterer._compute_cosine_distance(embeddings)
        assert dist[0, 1] == pytest.approx(0.0, abs=1e-6)

    def test_cosine_distance_orthogonal_vectors(self):
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        clusterer = DomainSemanticClusterer()
        dist = clusterer._compute_cosine_distance(embeddings)
        assert dist[0, 1] == pytest.approx(1.0, abs=1e-6)

    def test_call_graph_discount(self):
        embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        modules = [("repo", "A"), ("repo", "B"), ("repo", "C")]
        edges = [(("repo", "A"), ("repo", "B"), 1)]
        clusterer = DomainSemanticClusterer(call_graph_discount=0.85)
        dist = clusterer._compute_distance_matrix(embeddings, modules, edges)
        # A-B should have discounted distance
        assert dist[0, 1] < dist[0, 2]
        assert dist[0, 1] == pytest.approx(dist[0, 2] * 0.85, abs=0.01)
        # Discount is symmetric
        assert dist[0, 1] == pytest.approx(dist[1, 0], abs=1e-6)


class TestClustering:
    def test_cluster_returns_sets_of_modules(self):
        # 6 modules in 2 clear groups (similar embeddings)
        embeddings = np.array([
            [1.0, 0.0], [0.9, 0.1], [0.8, 0.2],  # Group 1
            [0.0, 1.0], [0.1, 0.9], [0.2, 0.8],  # Group 2
        ])
        modules = [("r", f"M{i}") for i in range(6)]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        assert len(clusters) >= 2
        # All modules assigned
        all_mods = set()
        for c in clusters:
            all_mods.update(c)
        assert all_mods == set(modules)

    def test_small_n_returns_single_cluster(self):
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        modules = [("r", "A"), ("r", "B")]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        # With N < min_clusters, should return single cluster
        assert len(clusters) == 1
        assert len(clusters[0]) == 2


class TestBuildEmbeddingTexts:
    def test_with_summary(self):
        modules = [("repo", "IntimacyService")]
        summaries = {"IntimacyService": {"summary_text": "亲密关系核心服务"}}
        paths = {"IntimacyService": "intimacy/service/IntimacyService.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "IntimacyService" in texts[0]
        assert "亲密关系核心服务" in texts[0]
        assert "intimacy/service" in texts[0]

    def test_without_summary_fallback(self):
        modules = [("repo", "FooHandler")]
        summaries = {}
        paths = {"FooHandler": "foo/handler/FooHandler.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "FooHandler" in texts[0]
        assert "foo/handler" in texts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.domain_semantic_clusterer'`

---

### Task 3: Create DomainSemanticClusterer — Implementation

**Files:**
- Create: `wiki/domain_semantic_clusterer.py`

- [ ] **Step 1: Implement DomainSemanticClusterer**

```python
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
    return "/".join(parts[-levels:]) if len(parts) > levels else path


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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/domain_semantic_clusterer.py tests/wiki/test_domain_semantic_clusterer.py pyproject.toml
git commit -m "feat: add DomainSemanticClusterer with HAC embedding clustering"
```

---

### Task 4: Enhance GraphDomainNamer — Tests

**Files:**
- Modify: `tests/wiki/test_graph_domain_namer.py`

- [ ] **Step 1: Add tests for module_infos interface**

Add to `tests/wiki/test_graph_domain_namer.py`:

```python
class TestNameCommunityWithInfos:
    @pytest.mark.asyncio
    async def test_name_with_module_infos(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"slug": "intimacy", "display_name": "亲密关系", "description": "desc"}')
        namer = GraphDomainNamer(llm)
        result = await namer.name_community(
            module_infos=[
                {"name": "IntimacyService", "path": "intimacy/service/", "summary": "亲密关系核心服务"},
                {"name": "ClosedFriendHandler", "path": "closedfriend/handler/", "summary": "私密好友圈管理"},
            ],
        )
        assert result["slug"] == "intimacy"
        assert result["display_name"] == "亲密关系"
        prompt_arg = llm.generate.call_args[0][0]
        assert "IntimacyService" in prompt_arg
        assert "intimacy/service/" in prompt_arg
        assert "亲密关系核心服务" in prompt_arg

    @pytest.mark.asyncio
    async def test_backward_compat_module_names(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"slug": "test", "display_name": "测试", "description": ""}')
        namer = GraphDomainNamer(llm)
        result = await namer.name_community(module_names=["FooService", "BarHandler"])
        assert result["slug"] == "test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_graph_domain_namer.py::TestNameCommunityWithInfos -v`
Expected: FAIL (new parameter not supported yet)

---

### Task 5: Enhance GraphDomainNamer — Implementation

**Files:**
- Modify: `wiki/graph_domain_namer.py`

- [ ] **Step 1: Update name_community to accept module_infos**

In `wiki/graph_domain_namer.py`, modify `GraphDomainNamer.name_community()`:

```python
    async def name_community(
        self,
        module_names: list[str] | None = None,
        *,
        module_infos: list[dict[str, str]] | None = None,
        used_names: list[str] | None = None,
        business_id: str = "",
    ) -> dict[str, str]:
        """Name a community based on module names or detailed infos.

        Args:
            module_names: Simple list of class names (legacy).
            module_infos: List of dicts with keys: name, path, summary (preferred).
            used_names: Slugs already in use to avoid duplicates.
            business_id: Business context for the prompt.
        """
        if module_infos:
            detail_lines = []
            for info in module_infos:
                name = info.get("name", "")
                path = info.get("path", "")
                summary = info.get("summary", "")
                if summary:
                    detail_lines.append(f"- {name} [{path}] — {summary}")
                elif path:
                    detail_lines.append(f"- {name} [{path}]")
                else:
                    detail_lines.append(f"- {name}")
            names_for_fallback = [info.get("name", "") for info in module_infos]
        elif module_names:
            detail_lines = [f"- {n}" for n in module_names]
            names_for_fallback = list(module_names)
        else:
            return _fallback_name([])

        if not detail_lines:
            return _fallback_name(names_for_fallback)

        if self._llm is None:
            return _fallback_name(names_for_fallback)

        used_block = ""
        if used_names:
            used_block = (
                "\nIMPORTANT: These names are already in use, choose a DIFFERENT name:\n"
                + ", ".join(used_names)
                + "\n"
            )

        biz_block = f"\nBusiness context: {business_id}\n" if business_id else ""

        prompt = _NAMING_PROMPT_V2.format(
            module_details="\n".join(detail_lines),
            used_names_block=used_block,
            business_context_block=biz_block,
        )

        for attempt in range(2):
            try:
                raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
                parsed = parse_json_robust_sync(raw)
                if isinstance(parsed, dict):
                    slug = parsed.get("slug")
                    display_name = parsed.get("display_name")
                    description = parsed.get("description")
                    if isinstance(slug, str) and slug and isinstance(display_name, str) and display_name:
                        return {
                            "slug": slug,
                            "display_name": display_name,
                            "description": str(description) if description is not None else "",
                        }
            except Exception:
                if attempt == 0:
                    log.warning("graph_domain_namer_retry", exc_info=True)
                    continue
                log.warning("graph_domain_namer_llm_failed", exc_info=True)

        return _fallback_name(names_for_fallback)
```

Also add the new prompt constant:

```python
_NAMING_PROMPT_V2 = (
    "You are naming a group of code modules for a business documentation wiki.\n"
    "These modules were grouped by their semantic similarity (business function).\n"
    "{business_context_block}\n"
    "Module details:\n"
    "{module_details}\n\n"
    "Rules:\n"
    "- Name the BUSINESS capability these modules provide, not code structure\n"
    "- Use concise Chinese business terminology (2-6 chars) for display_name\n"
    "- The slug should be kebab-case ASCII describing the business capability\n"
    "- Do NOT name based on technical patterns (Handler, Service, Dao, etc.)\n"
    "{used_names_block}\n"
    'Return ONLY valid JSON: {{"slug": "...", "display_name": "...", "description": "..."}}'
)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_graph_domain_namer.py -v`
Expected: All tests PASS (including old tests for backward compatibility)

- [ ] **Step 3: Commit**

```bash
git add wiki/graph_domain_namer.py tests/wiki/test_graph_domain_namer.py
git commit -m "feat: enhance GraphDomainNamer to accept module_infos with summaries"
```

---

### Task 6: Add review_global_consistency to GraphSemanticCorrector — Tests

**Files:**
- Modify: `tests/wiki/test_graph_semantic_corrector.py`

- [ ] **Step 1: Add tests for review_global_consistency**

Add to `tests/wiki/test_graph_semantic_corrector.py`:

```python
class TestReviewGlobalConsistency:
    @pytest.mark.asyncio
    async def test_merge_overlapping_domains(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"merges": [{"sources": ["intimacy-rel", "private-friends"], "target": "intimacy-rel", "new_display_name": "亲密关系", "reason": "same business"}], "renames": [], "moves": []}')
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "intimacy-rel": [("r", "IntimacyService"), ("r", "IntimacyTask")],
            "private-friends": [("r", "ClosedFriendHandler")],
            "family-system": [("r", "FamilyService")],
        }
        domain_display = {"intimacy-rel": "亲密关系", "private-friends": "私密好友", "family-system": "家族系统"}
        new_mapping, new_display = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )
        assert "private-friends" not in new_mapping
        assert "intimacy-rel" in new_mapping
        assert ("r", "ClosedFriendHandler") in new_mapping["intimacy-rel"]
        assert new_display.get("intimacy-rel") == "亲密关系"

    @pytest.mark.asyncio
    async def test_no_changes_needed(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"merges": [], "renames": [], "moves": []}')
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {"a": [("r", "X")], "b": [("r", "Y")]}
        domain_display = {"a": "域A", "b": "域B"}
        new_mapping, new_display = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )
        assert new_mapping == domain_mapping
        assert new_display == domain_display

    @pytest.mark.asyncio
    async def test_llm_none_returns_unchanged(self):
        corrector = GraphSemanticCorrector(None)
        domain_mapping = {"a": [("r", "X")]}
        domain_display = {"a": "域A"}
        new_mapping, new_display = await corrector.review_global_consistency(
            domain_mapping, domain_display, module_paths={}, module_summaries={},
        )
        assert new_mapping == domain_mapping
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_graph_semantic_corrector.py::TestReviewGlobalConsistency -v`
Expected: FAIL (`review_global_consistency` not defined)

---

### Task 7: Add review_global_consistency to GraphSemanticCorrector — Implementation

**Files:**
- Modify: `wiki/graph_semantic_corrector.py`

- [ ] **Step 1: Add review_global_consistency method**

Add the following method to `GraphSemanticCorrector` class and add the prompt constant:

```python
_GLOBAL_REVIEW_PROMPT = (
    "You are reviewing domain assignments for a code documentation wiki.\n"
    "Business: {business_id}\n\n"
    "All domains with their top representative modules:\n"
    "{domain_listing}\n\n"
    "Tasks:\n"
    "1. MERGE domains with overlapping business scope into one\n"
    "2. RENAME domains that use technical terms instead of business terms\n"
    "3. Flag obvious module misplacements (max 3 moves)\n\n"
    "Rules:\n"
    "- Only merge when business meaning clearly overlaps\n"
    "- Keep the domain with more modules as the merge target\n"
    "- Max 30% of modules can be moved\n\n"
    "Return ONLY valid JSON:\n"
    '{{"merges": [{{"sources": ["slug1", "slug2"], "target": "slug1",'
    ' "new_display_name": "...", "reason": "..."}}],'
    ' "renames": [{{"slug": "...", "new_display_name": "...", "reason": "..."}}],'
    ' "moves": [{{"module": "...", "from": "...", "to": "...", "reason": "..."}}]}}\n'
    'If no changes: {{"merges": [], "renames": [], "moves": []}}'
)
```

```python
    async def review_global_consistency(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_paths: dict[str, str],
        module_summaries: dict[str, str],
        *,
        business_id: str = "",
    ) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
        """One-shot global review: merge overlapping domains, rename, move modules."""
        if self._llm is None or len(domain_mapping) <= 1:
            return domain_mapping, domain_display_names

        # Build compact listing (top 5 modules per domain, no full summaries)
        lines: list[str] = []
        for slug, pairs in sorted(domain_mapping.items(), key=lambda x: -len(x[1])):
            display = domain_display_names.get(slug, slug)
            top_names = sorted([name for _, name in pairs])[:5]
            lines.append(f"- {slug} ({display}) — {len(pairs)} modules")
            lines.append(f"  {', '.join(top_names)}")
        listing = "\n".join(lines)

        prompt = _GLOBAL_REVIEW_PROMPT.format(
            business_id=business_id or "unknown",
            domain_listing=listing,
        )

        try:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
        except Exception:
            log.warning("global_review_llm_failed", exc_info=True)
            return domain_mapping, domain_display_names

        if not isinstance(parsed, dict):
            return domain_mapping, domain_display_names

        new_mapping = {slug: list(pairs) for slug, pairs in domain_mapping.items()}
        new_display = dict(domain_display_names)

        # Apply merges
        merges = parsed.get("merges", [])
        if isinstance(merges, list):
            for merge in merges:
                sources = merge.get("sources", [])
                target = merge.get("target", "")
                if not isinstance(sources, list) or target not in sources:
                    continue
                if target not in new_mapping:
                    continue
                new_name = merge.get("new_display_name")
                if isinstance(new_name, str) and new_name:
                    new_display[target] = new_name
                for src in sources:
                    if src == target or src not in new_mapping:
                        continue
                    new_mapping[target].extend(new_mapping.pop(src))
                    new_display.pop(src, None)
                    log.info("global_review_merge", source=src, target=target)

        # Apply renames
        renames = parsed.get("renames", [])
        if isinstance(renames, list):
            for rename in renames:
                slug = rename.get("slug", "")
                new_name = rename.get("new_display_name", "")
                if slug in new_display and isinstance(new_name, str) and new_name:
                    new_display[slug] = new_name
                    log.info("global_review_rename", slug=slug, new_name=new_name)

        # Apply moves (limited)
        total_modules = sum(len(v) for v in new_mapping.values())
        max_moves = max(int(total_modules * _MAX_MOVE_RATIO), 1)
        moves = parsed.get("moves", [])
        applied_moves = 0
        if isinstance(moves, list):
            module_to_repo: dict[str, str] = {}
            for pairs in new_mapping.values():
                for repo, mod_name in pairs:
                    module_to_repo[mod_name] = repo
            for move in moves:
                if applied_moves >= max_moves:
                    break
                mod_name = move.get("module", "")
                from_d = move.get("from", "")
                to_d = move.get("to", "")
                repo = module_to_repo.get(mod_name)
                if not all([mod_name, from_d, to_d, repo]):
                    continue
                if from_d not in new_mapping or to_d not in new_mapping:
                    continue
                pair = (repo, mod_name)
                if pair in new_mapping[from_d]:
                    new_mapping[from_d].remove(pair)
                    new_mapping[to_d].append(pair)
                    applied_moves += 1
                    log.info("global_review_move", module=mod_name, from_d=from_d, to_d=to_d)

        new_mapping = {k: v for k, v in new_mapping.items() if v}
        return new_mapping, new_display
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_graph_semantic_corrector.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/graph_semantic_corrector.py tests/wiki/test_graph_semantic_corrector.py
git commit -m "feat: add review_global_consistency to GraphSemanticCorrector"
```

---

### Task 8: Refactor graph_driven_domain_decompose_node

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py`

- [ ] **Step 1: Replace Louvain with embedding clustering**

Rewrite the core of `graph_driven_domain_decompose_node` to use the new components. Key changes:

1. Read `module_summaries` from state
2. Build embedding texts from summaries
3. Generate embeddings via `EmbeddingGenerator.shared()`
4. Use `DomainSemanticClusterer.cluster()` instead of `GraphCommunityDetector.detect()`
5. Pass `module_infos` to `GraphDomainNamer.name_community()` instead of `module_names`
6. Replace `correct_module_assignments()` + `merge_similar_domains()` with `review_global_consistency()`
7. Use `cluster_sub_domains()` for sub-domain splitting instead of `detect_sub_communities()`
8. Add fallback to Louvain if embedding generation fails

The full implementation replaces Steps 1-7.5 in the current code. Steps 0, 8-10 remain largely unchanged.

See spec Section 4.1 for the complete step-by-step flow.

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/wiki/test_pipeline_domain_integration.py -v`
Expected: Tests pass (may need mock updates for new embedding calls)

- [ ] **Step 3: Run all existing domain tests**

Run: `uv run pytest tests/wiki/test_graph_domain_namer.py tests/wiki/test_graph_semantic_corrector.py tests/wiki/test_domain_semantic_clusterer.py tests/wiki/test_pipeline_domain_integration.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/nodes/graph_domain_decompose.py
git commit -m "feat: replace Louvain with semantic embedding clustering in domain decomposition"
```

---

### Task 9: Adjust pipeline_graph.py node ordering

**Files:**
- Modify: `wiki/pipeline_graph.py`

- [ ] **Step 1: Reorder edges to put compose_leaf_modules before classify_domains**

In `build_wiki_pipeline()`, change the edge ordering from:

```python
graph.add_edge("assign_canonical_keys", "classify_domains")
graph.add_edge("classify_domains", "persist_classification")
graph.add_edge("persist_classification", "generate_titles")
graph.add_edge("generate_titles", "set_review_status")
graph.add_edge("set_review_status", "compose_leaf_modules")
```

To:

```python
graph.add_edge("assign_canonical_keys", "generate_titles")
graph.add_edge("generate_titles", "compose_leaf_modules")
graph.add_edge("compose_leaf_modules", "classify_domains")
graph.add_edge("classify_domains", "persist_classification")
graph.add_edge("persist_classification", "set_review_status")
```

Also remove the existing `graph.add_edge("compose_leaf_modules", "compose_domain_agents")` since it's now `set_review_status → compose_domain_agents`.

Add: `graph.add_edge("set_review_status", "compose_domain_agents")`

Update `_NODE_PHASE_MAP` progress percentages to reflect new order.

- [ ] **Step 2: Run pipeline structure tests**

Run: `uv run pytest tests/wiki/ -k "pipeline" -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/pipeline_graph.py
git commit -m "feat: reorder pipeline — compose_leaf_modules before classify_domains"
```

---

### Task 10: Full integration verification

**Files:**
- Modify: `tests/wiki/test_pipeline_domain_integration.py`

- [ ] **Step 1: Update integration tests for new pipeline order**

Ensure the integration test mocks the new flow: `compose_leaf_modules` providing `module_summaries` before `classify_domains` runs. Add mock for `EmbeddingGenerator.shared()`.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/wiki/ -v --timeout=120`
Expected: All tests PASS

- [ ] **Step 3: Run linter**

Run: `uv run ruff check wiki/ tests/wiki/`
Expected: No errors

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: update integration tests for semantic embedding domain classification"
```
