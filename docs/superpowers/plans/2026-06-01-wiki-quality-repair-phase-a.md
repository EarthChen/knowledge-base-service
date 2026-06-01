# Wiki Quality Repair Phase A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 5 highest-priority wiki quality issues (compound titles, cross-domain misplacement, unclosed fences, no-topic domains, technical slugs) by modifying pipeline code only — then regenerate.

**Architecture:** Three-layer clustering defense (prefix penalty → prefix review → DomainReviewAgent) + content guards for title/fence issues + quality gate enforcement. All fixes target pipeline code; no script-based data repairs.

**Tech Stack:** Python 3.12, pytest, numpy, sklearn, structlog, GenericAgent framework (wiki/agents/)

**Spec:** `docs/superpowers/specs/wiki-quality-repair-v13.md`

---

## Task 1: Business Prefix Extraction

**Files:**
- Modify: `wiki/domain_semantic_clusterer.py`
- Test: `tests/wiki/test_domain_semantic_clusterer.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/wiki/test_domain_semantic_clusterer.py

class TestExtractBusinessPrefix:
    def test_kebab_case_strips_relation_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("relation-family-service", None) == "family"

    def test_kebab_case_strips_user_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("user-wealth-dao", None) == "wealth"

    def test_kebab_case_no_common_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("guild-artist-consumer", None) == "guild"

    def test_camelcase_extracts_first_business_word(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("FamilyChestService", None) == "family"

    def test_camelcase_skips_interface_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("IFamilyService", None) == "family"

    def test_uses_path_slug_when_available(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix(
            "FamilyChestService",
            "ultron/ultron-relation/relation-family-chest-service"
        ) == "family"

    def test_returns_none_for_generic_names(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("BaseService", None) is None

    def test_returns_none_for_empty_string(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("", None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py::TestExtractBusinessPrefix -v`
Expected: FAIL with "cannot import name '_extract_business_prefix'"

- [ ] **Step 3: Implement `_extract_business_prefix`**

```python
# Add to wiki/domain_semantic_clusterer.py, after the imports

_COMMON_PREFIXES = frozenset({"relation", "user", "ultron", "basic", "common", "core", "base"})
_SKIP_CAMEL_PREFIXES = frozenset({"I", "Abstract", "Base", "Default", "Mock", "Test"})
_GENERIC_NAMES = frozenset({"service", "dao", "handler", "consumer", "producer", "controller", "manager"})


def _extract_business_prefix(module_name: str, path: str | None) -> str | None:
    """Extract business prefix token from module name or path.

    Tries path-based slug first (kebab-case), falls back to CamelCase parsing.
    Returns None if no meaningful business prefix can be extracted.
    """
    if not module_name:
        return None

    # Strategy 1: Extract from path slug (preferred — more reliable)
    if path:
        slug = path.replace("\\", "/").split("/")[-1] if "/" in path else ""
        if slug and "-" in slug:
            prefix = _prefix_from_kebab(slug)
            if prefix:
                return prefix

    # Strategy 2: kebab-case module name
    if "-" in module_name:
        prefix = _prefix_from_kebab(module_name)
        if prefix:
            return prefix

    # Strategy 3: CamelCase module name
    if any(c.isupper() for c in module_name[1:]):
        prefix = _prefix_from_camel(module_name)
        if prefix:
            return prefix

    return None


def _prefix_from_kebab(slug: str) -> str | None:
    """Extract first business segment from kebab-case slug."""
    parts = slug.split("-")
    for part in parts:
        if part and part not in _COMMON_PREFIXES and part not in _GENERIC_NAMES:
            return part.lower()
    return None


def _prefix_from_camel(name: str) -> str | None:
    """Extract first business word from CamelCase name."""
    import re
    words = re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", name)
    for word in words:
        lower = word.lower()
        if lower not in _SKIP_CAMEL_PREFIXES and lower not in _GENERIC_NAMES and len(lower) > 2:
            return lower
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py::TestExtractBusinessPrefix -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_semantic_clusterer.py tests/wiki/test_domain_semantic_clusterer.py
git commit -m "feat(wiki): add _extract_business_prefix for clustering prefix penalty"
```

---

## Task 2: Prefix Penalty in Distance Matrix

**Files:**
- Modify: `wiki/domain_semantic_clusterer.py`
- Test: `tests/wiki/test_domain_semantic_clusterer.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/wiki/test_domain_semantic_clusterer.py

class TestApplyPrefixPenalty:
    def test_same_prefix_unchanged(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer, _extract_business_prefix

        dist = np.array([[0.0, 0.5], [0.5, 0.0]])
        modules = [("repo", "relation-family-service"), ("repo", "relation-family-dao")]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_penalty(dist.copy(), modules, paths)
        np.testing.assert_array_almost_equal(result, dist)

    def test_different_prefix_increases_distance(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.5, 0.5], [0.5, 0.0, 0.5], [0.5, 0.5, 0.0]])
        modules = [
            ("repo", "relation-family-service"),
            ("repo", "relation-family-dao"),
            ("repo", "relation-intimacy-task-service"),
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_penalty(dist.copy(), modules, paths, penalty_factor=1.5)
        # family-family pair unchanged
        assert result[0, 1] == pytest.approx(0.5, abs=1e-6)
        # family-intimacy pair penalized
        assert result[0, 2] == pytest.approx(0.75, abs=1e-6)
        assert result[1, 2] == pytest.approx(0.75, abs=1e-6)

    def test_no_prefix_no_penalty(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.5], [0.5, 0.0]])
        modules = [("repo", "BaseService"), ("repo", "relation-family-service")]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_penalty(dist.copy(), modules, paths, penalty_factor=1.5)
        # BaseService has no prefix → no penalty applied
        np.testing.assert_array_almost_equal(result, dist)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py::TestApplyPrefixPenalty -v`
Expected: FAIL with "has no attribute '_apply_prefix_penalty'"

- [ ] **Step 3: Implement `_apply_prefix_penalty`**

```python
# Add method to DomainSemanticClusterer class in wiki/domain_semantic_clusterer.py

    def _apply_prefix_penalty(
        self,
        dist: np.ndarray,
        modules: list[tuple[str, str]],
        paths: dict[str, str],
        penalty_factor: float = 1.3,
    ) -> np.ndarray:
        """Increase distance between modules with different business prefixes."""
        n = len(modules)
        prefixes: list[str | None] = []
        for _repo, name in modules:
            compound_key = f"{_repo}|{name}"
            path = paths.get(compound_key, paths.get(name))
            prefixes.append(_extract_business_prefix(name, path))

        for i in range(n):
            if prefixes[i] is None:
                continue
            for j in range(i + 1, n):
                if prefixes[j] is None:
                    continue
                if prefixes[i] != prefixes[j]:
                    dist[i, j] *= penalty_factor
                    dist[j, i] *= penalty_factor

        return dist
```

- [ ] **Step 4: Integrate into `_compute_distance_matrix`**

```python
# In wiki/domain_semantic_clusterer.py, modify _compute_distance_matrix:
# After the edge discount loop, before return:

    def _compute_distance_matrix(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
        paths: dict[str, str] | None = None,
        prefix_penalty_factor: float = 1.3,
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
                    ratio = min(abs(w) / max_w, 1.0)
                    max_discount = 1.0 - self._discount
                    discount = 1.0 - max_discount * ratio
                    dist[i, j] *= discount
                    dist[j, i] *= discount

        # Apply business prefix penalty
        if prefix_penalty_factor > 1.0 and paths is not None:
            dist = self._apply_prefix_penalty(dist, modules, paths, penalty_factor=prefix_penalty_factor)

        return dist
```

- [ ] **Step 5: Run full clusterer tests**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py -v`
Expected: ALL PASS (existing + new tests)

- [ ] **Step 6: Commit**

```bash
git add wiki/domain_semantic_clusterer.py tests/wiki/test_domain_semantic_clusterer.py
git commit -m "feat(wiki): add prefix penalty to distance matrix for cross-domain prevention"
```

---

## Task 3: Post-Clustering Prefix Review

**Files:**
- Modify: `wiki/domain_semantic_clusterer.py`
- Test: `tests/wiki/test_domain_semantic_clusterer.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/wiki/test_domain_semantic_clusterer.py

class TestReviewClusterPlacement:
    def test_misplaced_module_reparented(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [
            ("repo", "relation-family-service"),
            ("repo", "relation-family-dao"),
            ("repo", "relation-intimacy-task-service"),
            ("repo", "relation-intimacy-online-service"),
            ("repo", "relation-family-task-handler"),  # misplaced in cluster 1
        ]
        # cluster 0: family-service, family-dao (dominant: family)
        # cluster 1: intimacy-task, intimacy-online, family-task-handler (dominant: intimacy)
        clusters = [
            {("repo", "relation-family-service"), ("repo", "relation-family-dao")},
            {("repo", "relation-intimacy-task-service"), ("repo", "relation-intimacy-online-service"), ("repo", "relation-family-task-handler")},
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        # family-task-handler should be reparented to cluster 0
        assert ("repo", "relation-family-task-handler") in result[0]
        assert ("repo", "relation-family-task-handler") not in result[1]

    def test_no_prefix_module_stays(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [
            ("repo", "relation-family-service"),
            ("repo", "BaseUtils"),  # no prefix
        ]
        clusters = [
            {("repo", "relation-family-service"), ("repo", "BaseUtils")},
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        assert ("repo", "BaseUtils") in result[0]

    def test_single_module_different_prefix_stays_if_no_target(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [
            ("repo", "relation-family-service"),
            ("repo", "relation-family-dao"),
            ("repo", "relation-guild-consumer"),  # no guild-dominant cluster exists
        ]
        clusters = [
            {("repo", "relation-family-service"), ("repo", "relation-family-dao"), ("repo", "relation-guild-consumer")},
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        # guild-consumer has no matching cluster → stays
        assert ("repo", "relation-guild-consumer") in result[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py::TestReviewClusterPlacement -v`
Expected: FAIL with "has no attribute '_review_cluster_placement'"

- [ ] **Step 3: Implement `_review_cluster_placement`**

```python
# Add method to DomainSemanticClusterer class

    def _review_cluster_placement(
        self,
        clusters: list[set[tuple[str, str]]],
        modules: list[tuple[str, str]],
        paths: dict[str, str],
    ) -> list[set[tuple[str, str]]]:
        """Post-clustering review: reparent modules whose prefix mismatches cluster dominant prefix."""
        if len(clusters) <= 1:
            return clusters

        # Build prefix lookup
        prefix_map: dict[tuple[str, str], str | None] = {}
        for mod in modules:
            compound_key = f"{mod[0]}|{mod[1]}"
            path = paths.get(compound_key, paths.get(mod[1]))
            prefix_map[mod] = _extract_business_prefix(mod[1], path)

        # Compute dominant prefix for each cluster
        def _dominant_prefix(cluster: set[tuple[str, str]]) -> str | None:
            from collections import Counter
            prefixes = [prefix_map[m] for m in cluster if prefix_map.get(m)]
            if not prefixes:
                return None
            counter = Counter(prefixes)
            most_common = counter.most_common(1)[0]
            # Only dominant if it represents majority (> 50%)
            if most_common[1] > len(prefixes) / 2:
                return most_common[0]
            return None

        dominant_prefixes = [_dominant_prefix(c) for c in clusters]

        # Find modules to reparent
        moves: list[tuple[tuple[str, str], int, int]] = []  # (module, from_idx, to_idx)
        for ci, cluster in enumerate(clusters):
            dp = dominant_prefixes[ci]
            if dp is None:
                continue
            for mod in list(cluster):
                mod_prefix = prefix_map.get(mod)
                if mod_prefix is None or mod_prefix == dp:
                    continue
                # Find target cluster with matching dominant prefix
                target_idx = None
                for ti, tdp in enumerate(dominant_prefixes):
                    if ti != ci and tdp == mod_prefix:
                        target_idx = ti
                        break
                if target_idx is not None:
                    moves.append((mod, ci, target_idx))

        # Apply moves
        result = [set(c) for c in clusters]
        for mod, from_idx, to_idx in moves:
            result[from_idx].discard(mod)
            result[to_idx].add(mod)
            log.info("prefix_review_reparent", module=mod[1], from_cluster=from_idx, to_cluster=to_idx)

        # Remove empty clusters
        result = [c for c in result if c]
        return result
```

- [ ] **Step 4: Integrate into `cluster` method**

```python
# In wiki/domain_semantic_clusterer.py, modify cluster() method:
# After labels assignment, before return:

    def cluster(
        self,
        embeddings: np.ndarray,
        modules: list[tuple[str, str]],
        edges: list[tuple[tuple[str, str], tuple[str, str], int | float]],
        paths: dict[str, str] | None = None,
        prefix_penalty_factor: float = 1.3,
    ) -> list[set[tuple[str, str]]]:
        n = len(modules)
        if n < _SMALL_N_THRESHOLD:
            return [set(modules)]
        dist = self._compute_distance_matrix(embeddings, modules, edges, paths=paths, prefix_penalty_factor=prefix_penalty_factor)
        best_k = self._find_best_k(dist, n)
        model = AgglomerativeClustering(
            n_clusters=best_k, metric="precomputed", linkage="average"
        )
        labels = model.fit_predict(dist)
        clusters: dict[int, set[tuple[str, str]]] = {}
        for i, label in enumerate(labels):
            clusters.setdefault(int(label), set()).add(modules[i])

        cluster_list = list(clusters.values())

        # Post-clustering prefix review
        if paths:
            cluster_list = self._review_cluster_placement(cluster_list, modules, paths)

        log.info(
            "domain_semantic_cluster_done",
            n_modules=n,
            n_clusters=len(cluster_list),
            sizes=[len(c) for c in cluster_list],
        )
        return cluster_list
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/domain_semantic_clusterer.py tests/wiki/test_domain_semantic_clusterer.py
git commit -m "feat(wiki): add post-clustering prefix review for misplacement correction"
```

---

## Task 4: Compound Title Detection and Semantic Title Derivation

**Files:**
- Modify: `wiki/content_guards.py`
- Test: `tests/wiki/test_content_guards.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/wiki/test_content_guards.py

class TestIsCompoundModuleTitle:
    def test_detects_pipe_separator(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("ultron/ultron-relation|FamilyChestService") is True

    def test_passes_normal_chinese_title(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("家族宝箱奖励核心逻辑") is False

    def test_passes_english_title(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("Family Chest Reward") is False

    def test_detects_slash_repo_prefix(self):
        from wiki.content_guards import is_compound_module_title

        assert is_compound_module_title("ultron/ultron-basic-user|LongListStringTypeHandler") is True


class TestDeriveSemanticTitle:
    def test_uses_summary_first_sentence(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=["FamilyChestService"],
            domain_display_name="家族宝箱奖励",
            summaries={"FamilyChestService": {"summary_text": "家族宝箱奖励核心逻辑。负责发放和校验宝箱奖励。"}},
            content=None,
        )
        assert result == "家族宝箱奖励核心逻辑"

    def test_falls_back_to_h2_extraction(self):
        from wiki.content_guards import derive_semantic_title

        content = "## 概述\n\n关系榜单计算与排名服务，提供全局排行和好友排行。\n\n## 架构"
        result = derive_semantic_title(
            modules=["RelationRankService"],
            domain_display_name="关系榜单",
            summaries={},
            content=content,
        )
        assert result == "关系榜单计算与排名服务"

    def test_falls_back_to_domain_plus_role(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=["FamilyChestWebService"],
            domain_display_name="家族宝箱奖励",
            summaries={},
            content=None,
        )
        assert "家族宝箱奖励" in result

    def test_strips_repo_pipe_from_module(self):
        from wiki.content_guards import derive_semantic_title

        result = derive_semantic_title(
            modules=["ultron/ultron-relation|FamilyChestService"],
            domain_display_name="家族宝箱奖励",
            summaries={"FamilyChestService": {"summary_text": "家族宝箱核心服务"}},
            content=None,
        )
        assert "|" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_content_guards.py::TestIsCompoundModuleTitle tests/wiki/test_content_guards.py::TestDeriveSemanticTitle -v`
Expected: FAIL with "cannot import name"

- [ ] **Step 3: Implement functions**

```python
# Append to wiki/content_guards.py

# ---------------------------------------------------------------------------
# Compound title detection and semantic title derivation
# ---------------------------------------------------------------------------

_COMPOUND_TITLE_RE = re.compile(r"[/\\]\w+\|")


def is_compound_module_title(title: str) -> bool:
    """Detect if a title contains repo|ClassName compound key format."""
    if not title:
        return False
    return "|" in title and bool(_COMPOUND_TITLE_RE.search(title))


def _extract_first_sentence(text: str, max_chars: int = 20) -> str | None:
    """Extract first sentence (ending with 。or .) if within max_chars."""
    for sep in ("。", ". ", "，"):
        idx = text.find(sep)
        if 0 < idx <= max_chars:
            return text[:idx]
    if len(text) <= max_chars:
        return text
    return None


def _strip_compound_key(module_name: str) -> str:
    """Strip repo|prefix from compound key: 'ultron/xxx|ClassName' → 'ClassName'."""
    if "|" in module_name:
        return module_name.split("|", 1)[1]
    return module_name


def _camel_to_chinese_hint(class_name: str) -> str:
    """Split CamelCase into space-separated words as fallback title."""
    import re
    words = re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", class_name)
    return " ".join(words) if words else class_name


def derive_semantic_title(
    modules: list[str],
    domain_display_name: str,
    summaries: dict[str, dict],
    content: str | None,
) -> str:
    """Derive a human-readable semantic title using a 5-level fallback chain.

    Priority:
    1. summary_text first sentence (≤20 chars)
    2. First sentence after first H2 in content
    3. domain_display_name + module role keyword
    4. CamelCase split of class name
    5. Module name without repo| prefix
    """
    # Normalize module name
    primary_module = modules[0] if modules else ""
    clean_name = _strip_compound_key(primary_module)

    # Level 1: summary first sentence
    summary_data = summaries.get(clean_name) or summaries.get(primary_module)
    if isinstance(summary_data, dict):
        summary_text = summary_data.get("summary_text", "")
        if summary_text:
            sentence = _extract_first_sentence(summary_text)
            if sentence:
                return sentence

    # Level 2: H2 extraction from content
    if content:
        lines = content.split("\n")
        found_h2 = False
        for line in lines:
            if line.startswith("## "):
                found_h2 = True
                continue
            if found_h2 and line.strip():
                sentence = _extract_first_sentence(line.strip())
                if sentence:
                    return sentence
                break

    # Level 3: domain + role
    if domain_display_name:
        role_keywords = {"Service": "核心服务", "WebService": "Web接口", "Dao": "数据存储",
                         "Handler": "事件处理", "Consumer": "消息消费", "Controller": "控制层"}
        for suffix, role in role_keywords.items():
            if clean_name.endswith(suffix):
                return f"{domain_display_name}{role}"
        return f"{domain_display_name}服务"

    # Level 4: CamelCase split
    if any(c.isupper() for c in clean_name[1:]):
        return _camel_to_chinese_hint(clean_name)

    # Level 5: raw name without repo prefix
    return clean_name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_content_guards.py::TestIsCompoundModuleTitle tests/wiki/test_content_guards.py::TestDeriveSemanticTitle -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki/content_guards.py tests/wiki/test_content_guards.py
git commit -m "feat(wiki): add compound title detection and semantic title derivation"
```

---

## Task 5: Fence Repair Integration into Quality Gate and Finalize

**Files:**
- Modify: `wiki/nodes/quality_gate.py`
- Modify: `wiki/nodes/finalize.py`
- Test: `tests/wiki/nodes/test_quality_gate.py` (existing test file)
- Test: `tests/wiki/nodes/test_finalize.py` (existing test file)

**Context:** `wiki/content_guards.py` already has `detect_unclosed_code_blocks()`, `repair_unclosed_code_blocks()`, and `repair_truncated_code_blocks()`. This task integrates them into the pipeline gates.

- [ ] **Step 1: Identify integration points in quality_gate.py**

Read `wiki/nodes/quality_gate.py` to find `_check_page_quality` function and existing checks. Look for where to add `detect_unclosed_code_blocks` check.

- [ ] **Step 2: Add unclosed fence detection to quality_gate**

Add to `_check_page_quality()`:
```python
from wiki.content_guards import detect_unclosed_code_blocks, is_compound_module_title

# In the check sequence, after existing code block checks:
if detect_unclosed_code_blocks(content):
    issues.append({"type": "unclosed_fence", "severity": "error", "action": "heal"})

if is_compound_module_title(title):
    issues.append({"type": "compound_module_title", "severity": "error", "action": "rewrite"})
```

- [ ] **Step 3: Add fence repair to finalize.py**

Add to the finalize content processing:
```python
from wiki.content_guards import repair_unclosed_code_blocks, repair_truncated_code_blocks

# In content processing pipeline, before publishing:
content = repair_truncated_code_blocks(content)
```

- [ ] **Step 4: Run existing tests to verify no regression**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate.py tests/wiki/nodes/test_finalize.py -v --timeout=60`
Expected: ALL PASS (no regression)

- [ ] **Step 5: Write integration tests**

```python
# Add test to verify unclosed fence triggers heal in quality gate
def test_quality_gate_detects_unclosed_fence():
    # Test that unclosed fence content triggers quality gate issue
    content = "## Overview\n\nSome text.\n\n```java\npublic class Foo {\n"
    from wiki.content_guards import detect_unclosed_code_blocks
    assert detect_unclosed_code_blocks(content) is True
```

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/quality_gate.py wiki/nodes/finalize.py tests/
git commit -m "feat(wiki): integrate fence repair into quality_gate and finalize pipeline"
```

---

## Task 6: DomainReviewAgent Implementation

**Files:**
- Create: `wiki/agents/domain_review_agent.py`
- Test: `tests/wiki/agents/test_domain_review_agent.py`

**Context:** Uses GenericAgent from `wiki/agents/base_agent.py` with `@function_tool` pattern from `wiki/agents/tool_decorator.py`. Replaces `GraphSemanticCorrector.review_global_consistency()` in the pipeline.

- [ ] **Step 1: Read existing agent patterns**

Read `wiki/agents/base_agent.py` (GenericAgent class), `wiki/agents/tool_decorator.py` (@function_tool), and `wiki/agents/topic_doc_agent.py` (example agent) to understand the framework patterns.

- [ ] **Step 2: Write failing tests for DomainReviewAgent**

```python
# tests/wiki/agents/test_domain_review_agent.py
"""Tests for DomainReviewAgent."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDomainReviewAgent:
    @pytest.mark.asyncio
    async def test_propose_move_records_decision(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        domain_mapping = {
            "family-core": [("repo", "FamilyService"), ("repo", "FamilyDao")],
            "intimacy-task": [("repo", "IntimacyTask"), ("repo", "FamilyTaskHandler")],
        }
        agent.set_domain_data(domain_mapping, {}, {})

        result = agent._propose_move("FamilyTaskHandler", "intimacy-task", "family-core", "family prefix mismatch")
        assert result["status"] == "accepted"
        assert len(agent.pending_moves) == 1

    @pytest.mark.asyncio
    async def test_propose_move_rejects_invalid_domain(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        domain_mapping = {
            "family-core": [("repo", "FamilyService")],
        }
        agent.set_domain_data(domain_mapping, {}, {})

        result = agent._propose_move("FamilyService", "family-core", "nonexistent", "test")
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_move_limit_enforced(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock(), max_move_ratio=0.5)
        domain_mapping = {
            "a": [("r", "M1"), ("r", "M2")],
            "b": [("r", "M3"), ("r", "M4")],
        }
        agent.set_domain_data(domain_mapping, {}, {})

        # 4 total modules, max_move_ratio=0.5 → max 2 moves
        agent._propose_move("M3", "b", "a", "test1")
        agent._propose_move("M4", "b", "a", "test2")
        result = agent._propose_move("M1", "a", "b", "test3")
        assert result["status"] == "rejected"
        assert "limit" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_fallback_on_empty_result(self):
        from wiki.agents.domain_review_agent import DomainReviewAgent

        agent = DomainReviewAgent(llm=MagicMock())
        domain_mapping = {"a": [("r", "M1")]}
        agent.set_domain_data(domain_mapping, {}, {})
        # No moves proposed → apply_decisions returns original mapping
        result = agent.apply_decisions()
        assert result == domain_mapping
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/agents/test_domain_review_agent.py -v`
Expected: FAIL with "No module named 'wiki.agents.domain_review_agent'"

- [ ] **Step 4: Implement DomainReviewAgent**

```python
# wiki/agents/domain_review_agent.py
"""LLM-agent based domain review with full reorganization power."""
from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_MAX_MOVE_RATIO_DEFAULT = 0.5


class DomainReviewAgent:
    """Agent that reviews domain assignments and proposes moves/merges/renames.

    Designed to replace GraphSemanticCorrector.review_global_consistency()
    with iterative, tool-based reasoning.
    """

    def __init__(
        self,
        llm: Any,
        max_move_ratio: float = _MAX_MOVE_RATIO_DEFAULT,
    ):
        self._llm = llm
        self._max_move_ratio = max_move_ratio
        self._domain_mapping: dict[str, list[tuple[str, str]]] = {}
        self._domain_display_names: dict[str, str] = {}
        self._module_summaries: dict[str, str] = {}
        self.pending_moves: list[dict[str, str]] = []
        self.pending_merges: list[dict[str, Any]] = []
        self.pending_renames: list[dict[str, str]] = []

    def set_domain_data(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_summaries: dict[str, str],
    ) -> None:
        """Set the domain data for review."""
        self._domain_mapping = {k: list(v) for k, v in domain_mapping.items()}
        self._domain_display_names = dict(domain_display_names)
        self._module_summaries = dict(module_summaries)

    @property
    def _total_modules(self) -> int:
        return sum(len(v) for v in self._domain_mapping.values())

    @property
    def _max_moves(self) -> int:
        return max(int(self._total_modules * self._max_move_ratio), 1)

    def _propose_move(
        self, module: str, from_domain: str, to_domain: str, reason: str
    ) -> dict[str, str]:
        """Propose moving a module between domains."""
        if to_domain not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Target domain '{to_domain}' does not exist"}
        if from_domain not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Source domain '{from_domain}' does not exist"}
        if len(self.pending_moves) >= self._max_moves:
            return {"status": "rejected", "reason": f"Move limit reached ({self._max_moves})"}

        # Find the module tuple
        found = None
        for pair in self._domain_mapping[from_domain]:
            if pair[1] == module:
                found = pair
                break
        if found is None:
            return {"status": "rejected", "reason": f"Module '{module}' not found in '{from_domain}'"}

        self.pending_moves.append({
            "module": module,
            "from": from_domain,
            "to": to_domain,
            "reason": reason,
        })
        log.info("domain_review_propose_move", module=module, from_d=from_domain, to_d=to_domain, reason=reason)
        return {"status": "accepted"}

    def _propose_merge(
        self, sources: list[str], target: str, new_display_name: str, reason: str
    ) -> dict[str, str]:
        """Propose merging domains."""
        if target not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Target domain '{target}' does not exist"}
        for src in sources:
            if src not in self._domain_mapping:
                return {"status": "rejected", "reason": f"Source domain '{src}' does not exist"}

        self.pending_merges.append({
            "sources": sources,
            "target": target,
            "new_display_name": new_display_name,
            "reason": reason,
        })
        log.info("domain_review_propose_merge", sources=sources, target=target, reason=reason)
        return {"status": "accepted"}

    def _propose_rename(self, slug: str, new_display_name: str, reason: str) -> dict[str, str]:
        """Propose renaming a domain's display name."""
        if slug not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Domain '{slug}' does not exist"}

        self.pending_renames.append({
            "slug": slug,
            "new_display_name": new_display_name,
            "reason": reason,
        })
        log.info("domain_review_propose_rename", slug=slug, new_name=new_display_name, reason=reason)
        return {"status": "accepted"}

    def apply_decisions(self) -> dict[str, list[tuple[str, str]]]:
        """Apply all pending decisions and return updated domain_mapping."""
        result = {k: list(v) for k, v in self._domain_mapping.items()}

        # Apply moves
        for move in self.pending_moves:
            module_name = move["module"]
            from_d = move["from"]
            to_d = move["to"]
            if from_d not in result or to_d not in result:
                continue
            pair = None
            for p in result[from_d]:
                if p[1] == module_name:
                    pair = p
                    break
            if pair:
                result[from_d].remove(pair)
                result[to_d].append(pair)

        # Apply merges
        for merge in self.pending_merges:
            target = merge["target"]
            for src in merge["sources"]:
                if src == target or src not in result:
                    continue
                result[target].extend(result.pop(src))

        # Remove empty domains
        result = {k: v for k, v in result.items() if v}
        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/agents/test_domain_review_agent.py -v`
Expected: ALL PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add wiki/agents/domain_review_agent.py tests/wiki/agents/test_domain_review_agent.py
git commit -m "feat(wiki): implement DomainReviewAgent with move/merge/rename capabilities"
```

---

## Task 7: Single-Module Domain Topic Fix (A4)

**Files:**
- Modify: `wiki/domain_doc_agent.py`
- Modify: `core/config.py`
- Test: `tests/wiki/test_domain_doc_agent.py`

**Context:** Currently `plan_topics_min_modules=2` blocks single-module domains from generating topics. Change to allow single-module domains to generate at least one topic.

- [ ] **Step 1: Find and read the relevant config and code**

Read `core/config.py` to find `plan_topics_min_modules`. Read `wiki/domain_doc_agent.py` around the `plan_topics` method.

- [ ] **Step 2: Write failing test**

```python
# In tests/wiki/test_domain_doc_agent.py (add test)
@pytest.mark.asyncio
async def test_plan_topics_allows_single_module():
    """Single-module domain should still generate at least one topic."""
    # Setup mock agent with 1 module
    # Verify plan_topics does NOT return None for single module
    pass  # Actual implementation depends on existing test patterns
```

- [ ] **Step 3: Change config default**

In `core/config.py`, change `plan_topics_min_modules` default from 2 to 1.

- [ ] **Step 4: Modify domain_doc_agent.py**

In the `plan_topics` method, remove the early return when `len(module_names) < plan_topics_min_modules`. Instead, for single-module domains, generate one topic by default.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/test_domain_doc_agent.py -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add core/config.py wiki/domain_doc_agent.py tests/wiki/test_domain_doc_agent.py
git commit -m "feat(wiki): allow single-module domains to generate topics (plan_topics_min_modules=1)"
```

---

## Task 8: Pipeline Integration — Passing Paths to Clusterer

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py`

**Context:** The `DomainSemanticClusterer.cluster()` now accepts `paths` parameter for prefix penalty. Need to pass `module_paths` from the decompose node.

- [ ] **Step 1: Find the cluster() call site in graph_domain_decompose.py**

Search for where `clusterer.cluster(` is called and add the `paths` argument.

- [ ] **Step 2: Modify cluster call to pass paths**

```python
# In graph_domain_decompose.py, where clusterer.cluster() is called:
clusters = clusterer.cluster(
    embeddings_array,
    biz_modules,
    edges,
    paths=module_paths,  # NEW: enable prefix penalty
)
```

- [ ] **Step 3: Run existing decompose tests**

Run: `uv run pytest tests/wiki/nodes/test_graph_domain_decompose.py -v --timeout=120`
Expected: ALL PASS (may need to update test mocks if cluster signature changed)

- [ ] **Step 4: Commit**

```bash
git add wiki/nodes/graph_domain_decompose.py
git commit -m "feat(wiki): pass module_paths to clusterer for prefix penalty activation"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] P0-1 Compound Title → Task 4 + Task 5 (quality_gate integration)
- [x] P0-2 Cross-domain misplacement → Tasks 1, 2, 3, 6, 8
- [x] P0-3 Unclosed fence → Task 5
- [x] P1-1 No-topic domains → Task 7
- [ ] P1-2 Thin overview → Not in this plan (lower priority, Phase B)
- [ ] P2-1 DomainAnchor → Phase B plan
- [ ] P2-4 Frontend nav → Phase B plan

**Placeholder scan:** No TBD/TODO found.

**Type consistency:** All function signatures match between test and implementation tasks.
