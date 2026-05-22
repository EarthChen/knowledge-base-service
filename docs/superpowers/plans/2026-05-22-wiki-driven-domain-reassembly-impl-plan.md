# Wiki-Driven Domain Reassembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-Wiki-generation domain reassembly node that merges semantically similar domains and re-assigns orphan pages using domain overview embeddings + LLM review.

**Architecture:** New pipeline node `reassemble_domains` inserted between `compose_parent_pages` and `quality_gate`. Uses embedding cosine similarity to find merge candidates, LLM to approve merges, and embedding matching for orphan pages. Respects `user_modified` pinned domains.

**Tech Stack:** Python 3.12+, LangGraph, numpy, EmbeddingGenerator (bge-m3), LLMProvider, FalkorDB (WikiTreeStore)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/nodes/reassemble_domains.py` | **NEW** — Core reassembly logic: embed domain overviews, find merge candidates, LLM review, orphan matching, rebuild tree |
| `wiki/pipeline_state.py` | Add `reassembly_actions` field to state TypedDict |
| `wiki/pipeline_graph.py` | Insert reassemble_domains node, add edge compose_parent_pages → reassemble_domains → quality_gate |
| `wiki/pipeline_nodes.py` | Export reassemble_domains_node |
| `core/config.py` | Add 5 reassembly config fields to AppWikiFlags |
| `wiki/tree_linker.py` | Simplify `_adopt_orphan_domain_pages` (reassembly handles orphans) |
| `tests/wiki/test_reassemble_domains.py` | **NEW** — Unit tests: merge, orphan, pinned, degradation |
| `tests/wiki/test_reassemble_integration.py` | **NEW** — Integration tests: pipeline flow |

---

### Task 1: Add config fields to `AppWikiFlags`

**Files:**
- Modify: `core/config.py:187-236` (AppWikiFlags class)
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_reassemble_domains.py
"""Tests for wiki-driven domain reassembly."""
from __future__ import annotations

import pytest


class TestReassemblyConfig:
    def test_default_config_values(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.domain_reassembly_enabled is True
        assert flags.reassembly_merge_threshold == 0.85
        assert flags.reassembly_orphan_threshold == 0.60
        assert flags.reassembly_max_moves_pct == 0.30
        assert flags.reassembly_respect_user_modified is True

    def test_config_override(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags(
            domain_reassembly_enabled=False,
            reassembly_merge_threshold=0.9,
        )
        assert flags.domain_reassembly_enabled is False
        assert flags.reassembly_merge_threshold == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestReassemblyConfig -v`
Expected: FAIL with `ValidationError` or `AttributeError` (fields don't exist yet)

- [ ] **Step 3: Write minimal implementation**

Add fields to `AppWikiFlags` in `core/config.py`, after the existing `domain_classification_cache_enabled` field:

```python
    # Domain reassembly (post-wiki-generation domain structure correction)
    domain_reassembly_enabled: bool = True
    reassembly_merge_threshold: float = Field(default=0.85, ge=0.5, le=1.0)
    reassembly_orphan_threshold: float = Field(default=0.60, ge=0.3, le=1.0)
    reassembly_max_moves_pct: float = Field(default=0.30, ge=0.0, le=1.0)
    reassembly_respect_user_modified: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestReassemblyConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/wiki/test_reassemble_domains.py
git commit -m "feat(wiki): add domain reassembly config fields"
```

---

### Task 2: Add `reassembly_actions` to pipeline state

**Files:**
- Modify: `wiki/pipeline_state.py:97-105`
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/wiki/test_reassemble_domains.py

class TestPipelineState:
    def test_state_has_reassembly_actions_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "reassembly_actions" in annotations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestPipelineState -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Write minimal implementation**

Add to `wiki/pipeline_state.py` after the existing `domain_cache` field (around line 100):

```python
    # --- Domain reassembly (post-wiki-generation correction) ---
    reassembly_actions: NotRequired[list[dict[str, Any]]]
    domain_display_names: NotRequired[dict[str, str]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestPipelineState -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_state.py tests/wiki/test_reassemble_domains.py
git commit -m "feat(wiki): add reassembly_actions field to pipeline state"
```

---

### Task 3: Implement core reassembly logic — embedding + merge candidates

**Files:**
- Create: `wiki/nodes/reassemble_domains.py`
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write the failing test for domain embedding extraction**

```python
# Append to tests/wiki/test_reassemble_domains.py
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch


class TestDomainEmbedding:
    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_from_pages(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        pages = [
            {"path": "auth-domain/_overview", "content": "This domain handles authentication and authorization."},
            {"path": "payment-domain/_overview", "content": "This domain handles payment processing."},
            {"path": "auth-domain/login-module", "content": "Login module details."},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.1] * 1024,
            [0.9] * 1024,
        ])

        result = await _extract_domain_embeddings(pages, mock_generator)

        assert "auth-domain" in result
        assert "payment-domain" in result
        assert "auth-domain/login-module" not in result
        assert result["auth-domain"].shape == (1024,)
        mock_generator.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_empty_pages(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        mock_generator = AsyncMock()
        result = await _extract_domain_embeddings([], mock_generator)
        assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestDomainEmbedding -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/nodes/reassemble_domains.py
"""Wiki-driven domain reassembly node for the wiki pipeline."""
from __future__ import annotations

import itertools
from typing import Any

import numpy as np

from core.log import get_logger

log = get_logger(__name__)

_CONTENT_TRUNCATE_LEN = 2000


def _extract_domain_slug(path: str) -> str | None:
    """Extract domain slug from a page path ending with /_overview."""
    if not path.endswith("/_overview"):
        return None
    parts = path.rsplit("/", 1)
    return parts[0] if parts else None


async def _extract_domain_embeddings(
    pages: list[dict[str, Any]],
    embedding_generator: Any,
) -> dict[str, np.ndarray]:
    """Embed each domain's overview page content."""
    overview_pages: list[tuple[str, str]] = []
    for page in pages:
        path = str(page.get("path") or "")
        slug = _extract_domain_slug(path)
        if slug is None:
            continue
        content = str(page.get("content") or "")[:_CONTENT_TRUNCATE_LEN]
        if content.strip():
            overview_pages.append((slug, content))

    if not overview_pages:
        return {}

    texts = [content for _, content in overview_pages]
    embeddings_list = await embedding_generator.generate(texts)

    result: dict[str, np.ndarray] = {}
    for (slug, _), emb in zip(overview_pages, embeddings_list):
        result[slug] = np.array(emb, dtype=np.float32)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestDomainEmbedding -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/reassemble_domains.py tests/wiki/test_reassemble_domains.py
git commit -m "feat(wiki): domain embedding extraction for reassembly"
```

---

### Task 4: Implement merge candidate detection

**Files:**
- Modify: `wiki/nodes/reassemble_domains.py`
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/wiki/test_reassemble_domains.py

class TestMergeCandidates:
    def test_find_merge_candidates_above_threshold(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        # Two very similar domains (cosine sim ~1.0)
        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.99, 0.1, 0.0], dtype=np.float32),
            "domain-c": np.array([0.0, 0.0, 1.0], dtype=np.float32),
        }

        candidates = _find_merge_candidates(embeddings, threshold=0.85, pinned_domains=set())
        assert len(candidates) == 1
        assert candidates[0]["source"] in ("domain-a", "domain-b")
        assert candidates[0]["target"] in ("domain-a", "domain-b")
        assert candidates[0]["similarity"] > 0.85

    def test_find_merge_candidates_none_above_threshold(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        candidates = _find_merge_candidates(embeddings, threshold=0.85, pinned_domains=set())
        assert candidates == []

    def test_find_merge_candidates_skips_pinned(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.99, 0.1, 0.0], dtype=np.float32),
        }
        candidates = _find_merge_candidates(
            embeddings, threshold=0.85, pinned_domains={"domain-a"}
        )
        assert candidates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestMergeCandidates -v`
Expected: FAIL with `ImportError` (function not defined)

- [ ] **Step 3: Write minimal implementation**

Append to `wiki/nodes/reassemble_domains.py`:

```python
def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _find_merge_candidates(
    embeddings: dict[str, np.ndarray],
    threshold: float,
    pinned_domains: set[str],
) -> list[dict[str, Any]]:
    """Find domain pairs with cosine similarity above threshold."""
    candidates: list[dict[str, Any]] = []
    for (d1, e1), (d2, e2) in itertools.combinations(embeddings.items(), 2):
        if d1 in pinned_domains or d2 in pinned_domains:
            continue
        sim = _cosine_similarity(e1, e2)
        if sim > threshold:
            candidates.append({"source": d1, "target": d2, "similarity": sim})

    candidates.sort(key=lambda x: -x["similarity"])
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestMergeCandidates -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/reassemble_domains.py tests/wiki/test_reassemble_domains.py
git commit -m "feat(wiki): merge candidate detection for reassembly"
```

---

### Task 5: Implement orphan page matching

**Files:**
- Modify: `wiki/nodes/reassemble_domains.py`
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/wiki/test_reassemble_domains.py

class TestOrphanMatching:
    @pytest.mark.asyncio
    async def test_match_orphan_to_best_domain(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "auth-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "payment-domain": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "orphan-auth/_overview", "content": "Handles user sessions"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.95, 0.1, 0.0],  # Very similar to auth-domain
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains=set(),
        )
        assert len(assignments) == 1
        assert assignments[0]["orphan_path"] == "orphan-auth/_overview"
        assert assignments[0]["assigned_domain"] == "auth-domain"

    @pytest.mark.asyncio
    async def test_orphan_below_threshold_not_assigned(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "auth-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "unrelated/_overview", "content": "Completely different topic"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.0, 0.0, 1.0],  # Orthogonal to auth-domain
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains=set(),
        )
        assert assignments == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestOrphanMatching -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Append to `wiki/nodes/reassemble_domains.py`:

```python
async def _match_orphan_pages(
    orphan_pages: list[dict[str, Any]],
    domain_embeddings: dict[str, np.ndarray],
    embedding_generator: Any,
    threshold: float,
    pinned_domains: set[str],
) -> list[dict[str, Any]]:
    """Match orphan pages to the closest domain by embedding similarity."""
    if not orphan_pages or not domain_embeddings:
        return []

    texts = [str(p.get("content") or "")[:_CONTENT_TRUNCATE_LEN] for p in orphan_pages]
    orphan_embeddings = await embedding_generator.generate(texts)

    assignments: list[dict[str, Any]] = []
    for page, emb_list in zip(orphan_pages, orphan_embeddings):
        orphan_emb = np.array(emb_list, dtype=np.float32)
        best_domain: str | None = None
        best_score = -1.0

        for slug, domain_emb in domain_embeddings.items():
            if slug in pinned_domains:
                continue
            score = _cosine_similarity(orphan_emb, domain_emb)
            if score > best_score:
                best_score = score
                best_domain = slug

        if best_domain and best_score >= threshold:
            assignments.append({
                "orphan_path": page.get("path", ""),
                "assigned_domain": best_domain,
                "similarity": best_score,
            })

    return assignments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestOrphanMatching -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/reassemble_domains.py tests/wiki/test_reassemble_domains.py
git commit -m "feat(wiki): orphan page matching for reassembly"
```

---

### Task 6: Implement the full `reassemble_domains_node` pipeline node

**Files:**
- Modify: `wiki/nodes/reassemble_domains.py`
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/wiki/test_reassemble_domains.py

class TestReassembleDomainsNode:
    @pytest.mark.asyncio
    async def test_skip_when_disabled(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [],
            "domain_mapping": {},
            "domain_tree": [],
            "config": {"reassembly_enabled": False},
        }
        result = await reassemble_domains_node(state)
        assert result.get("reassembly_actions") == []

    @pytest.mark.asyncio
    async def test_skip_when_no_overview_pages(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [{"path": "some/page", "content": "No overviews"}],
            "domain_mapping": {"domain-a": [("repo", "ModA")]},
            "domain_tree": [{"slug": "domain-a"}],
            "config": {},
        }
        with patch(
            "wiki.nodes.reassemble_domains._get_embedding_generator",
            return_value=AsyncMock(),
        ):
            result = await reassemble_domains_node(state)
        assert result.get("reassembly_actions") == []

    @pytest.mark.asyncio
    async def test_merge_two_similar_domains(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": "domain-a/_overview", "content": "Handles user login and auth tokens."},
                {"path": "domain-b/_overview", "content": "Manages authentication sessions."},
            ],
            "domain_mapping": {
                "domain-a": [("repo", "ModA")],
                "domain-b": [("repo", "ModB")],
            },
            "domain_tree": [
                {"slug": "domain-a", "children": []},
                {"slug": "domain-b", "children": []},
            ],
            "domain_display_names": {"domain-a": "Auth Domain", "domain-b": "Session Domain"},
            "config": {"reassembly_merge_threshold": 0.80},
        }

        mock_generator = AsyncMock()
        # Both domains get very similar embeddings
        mock_generator.generate = AsyncMock(return_value=[
            [0.9, 0.1, 0.0] * 341 + [0.9],  # 1024-dim
            [0.88, 0.12, 0.0] * 341 + [0.88],  # 1024-dim, similar
        ])

        mock_llm = AsyncMock()
        mock_llm.chat_complete = AsyncMock(return_value='{"approved_merges": [{"source": "domain-b", "target": "domain-a"}]}')

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains._get_llm_provider", return_value=mock_llm), \
             patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()):
            result = await reassemble_domains_node(state)

        assert "domain-b" not in result["domain_mapping"]
        assert "domain-a" in result["domain_mapping"]
        assert ("repo", "ModB") in result["domain_mapping"]["domain-a"]
        assert len(result["reassembly_actions"]) > 0

    @pytest.mark.asyncio
    async def test_rollback_when_too_many_moves(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": f"domain-{i}/_overview", "content": f"Domain {i} content that is similar."}
                for i in range(10)
            ],
            "domain_mapping": {f"domain-{i}": [("repo", f"Mod{i}")] for i in range(10)},
            "domain_tree": [{"slug": f"domain-{i}", "children": []} for i in range(10)],
            "domain_display_names": {f"domain-{i}": f"Domain {i}" for i in range(10)},
            "config": {"reassembly_max_moves_pct": 0.10},  # max 10% moves = 1 module
        }

        mock_generator = AsyncMock()
        # All embeddings identical → all would merge
        mock_generator.generate = AsyncMock(return_value=[[1.0] * 1024] * 10)

        mock_llm = AsyncMock()
        mock_llm.chat_complete = AsyncMock(return_value='{"approved_merges": [{"source": "domain-1", "target": "domain-0"}, {"source": "domain-2", "target": "domain-0"}, {"source": "domain-3", "target": "domain-0"}]}')

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains._get_llm_provider", return_value=mock_llm), \
             patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()):
            result = await reassemble_domains_node(state)

        # Should rollback: original mapping preserved
        assert len(result["domain_mapping"]) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestReassembleDomainsNode -v`
Expected: FAIL with `ImportError` or `AttributeError`

- [ ] **Step 3: Write the full node implementation**

Append to `wiki/nodes/reassemble_domains.py`:

```python
from langchain_core.runnables import RunnableConfig

from core.config import get_settings
from indexer.embedding_generator import EmbeddingGenerator


def _get_embedding_generator() -> Any:
    """Get shared embedding generator instance."""
    config = get_settings().embedding
    return EmbeddingGenerator.shared(config)


def _get_llm_provider(config: RunnableConfig | None = None) -> Any:
    """Get LLM provider from config or fallback."""
    configurable = (config or {}).get("configurable", {}) or {}
    return configurable.get("llm")


async def _get_pinned_domains(config: RunnableConfig | None = None) -> set[str]:
    """Query wiki tree store for user_modified sections."""
    configurable = (config or {}).get("configurable", {}) or {}
    wiki_tree_store = configurable.get("wiki_tree_store")
    if not wiki_tree_store:
        return set()
    try:
        business_id = configurable.get("business_id", "")
        sections = await wiki_tree_store.get_all_sections(business_id)
        return {s["slug"] for s in sections if s.get("user_modified")}
    except Exception:
        log.warning("reassembly_pinned_domains_query_failed", exc_info=True)
        return set()


def _execute_merges(
    domain_mapping: dict[str, list[Any]],
    domain_display_names: dict[str, str],
    domain_tree: list[dict[str, Any]],
    approved_merges: list[dict[str, str]],
) -> tuple[dict[str, list[Any]], dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute approved merges and return updated structures + action log."""
    actions: list[dict[str, Any]] = []
    merged_away: set[str] = set()

    for merge in approved_merges:
        source = merge["source"]
        target = merge["target"]
        if source in merged_away or target in merged_away:
            continue
        if source not in domain_mapping or target not in domain_mapping:
            continue

        domain_mapping.setdefault(target, []).extend(domain_mapping.pop(source, []))
        domain_display_names.pop(source, None)
        merged_away.add(source)
        actions.append({"type": "merge", "source": source, "target": target})

    new_tree = [node for node in domain_tree if node.get("slug") not in merged_away]
    return domain_mapping, domain_display_names, new_tree, actions


async def reassemble_domains_node(
    state: dict[str, Any], config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Post-wiki domain reassembly: merge similar domains + match orphans."""
    pipeline_config = state.get("config") or {}

    if pipeline_config.get("reassembly_enabled") is False:
        log.info("reassembly_skipped", reason="disabled")
        return {"reassembly_actions": []}

    settings = get_settings().wiki
    merge_threshold = pipeline_config.get(
        "reassembly_merge_threshold", settings.reassembly_merge_threshold
    )
    orphan_threshold = pipeline_config.get(
        "reassembly_orphan_threshold", settings.reassembly_orphan_threshold
    )
    max_moves_pct = pipeline_config.get(
        "reassembly_max_moves_pct", settings.reassembly_max_moves_pct
    )
    respect_pinned = pipeline_config.get(
        "reassembly_respect_user_modified",
        settings.reassembly_respect_user_modified,
    )

    pages = state.get("pages") or []
    domain_mapping = dict(state.get("domain_mapping") or {})
    domain_tree = list(state.get("domain_tree") or [])
    domain_display_names = dict(state.get("domain_display_names") or {})
    original_module_count = sum(len(v) for v in domain_mapping.values())

    # --- Step 1: Embed domain overviews ---
    try:
        generator = _get_embedding_generator()
        domain_embeddings = await _extract_domain_embeddings(pages, generator)
    except Exception:
        log.warning("reassembly_embedding_failed", exc_info=True)
        return {"reassembly_actions": []}

    if len(domain_embeddings) < 2:
        log.info("reassembly_skipped", reason="insufficient_domains", count=len(domain_embeddings))
        return {"reassembly_actions": []}

    # --- Step 2: Find pinned domains ---
    pinned_domains: set[str] = set()
    if respect_pinned:
        pinned_domains = await _get_pinned_domains(config)

    # --- Step 3: Find merge candidates ---
    merge_candidates = _find_merge_candidates(domain_embeddings, merge_threshold, pinned_domains)

    # --- Step 4: LLM review (only if candidates exist) ---
    approved_merges: list[dict[str, str]] = []
    if merge_candidates:
        llm = _get_llm_provider(config)
        if llm:
            try:
                approved_merges = await _llm_review_merges(merge_candidates, pages, llm)
            except Exception:
                log.warning("reassembly_llm_review_failed", exc_info=True)

    # --- Step 5: Execute merges ---
    actions: list[dict[str, Any]] = []
    if approved_merges:
        domain_mapping, domain_display_names, domain_tree, merge_actions = _execute_merges(
            domain_mapping, domain_display_names, domain_tree, approved_merges,
        )
        actions.extend(merge_actions)

    # --- Step 6: Orphan matching ---
    # (Find domain overview pages not in current domain_mapping)
    known_slugs = set(domain_mapping.keys())
    orphan_pages = [
        p for p in pages
        if _extract_domain_slug(str(p.get("path") or "")) is not None
        and _extract_domain_slug(str(p.get("path") or "")) not in known_slugs
    ]
    if orphan_pages:
        try:
            orphan_assignments = await _match_orphan_pages(
                orphan_pages, domain_embeddings, generator, orphan_threshold, pinned_domains,
            )
            for assignment in orphan_assignments:
                actions.append({"type": "orphan_match", **assignment})
        except Exception:
            log.warning("reassembly_orphan_matching_failed", exc_info=True)

    # --- Step 7: Rollback check ---
    moved_count = len(actions)
    if original_module_count > 0 and moved_count / max(original_module_count, 1) > max_moves_pct:
        log.warning(
            "reassembly_rollback",
            moved=moved_count,
            total=original_module_count,
            max_pct=max_moves_pct,
        )
        return {"reassembly_actions": [{"type": "rollback", "reason": "too_many_moves"}]}

    log.info("reassembly_complete", actions_count=len(actions))
    return {
        "domain_mapping": domain_mapping,
        "domain_tree": domain_tree,
        "domain_display_names": domain_display_names,
        "reassembly_actions": actions,
    }


async def _llm_review_merges(
    candidates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    llm: Any,
) -> list[dict[str, str]]:
    """Call LLM to approve/reject merge candidates."""
    page_by_slug: dict[str, str] = {}
    for p in pages:
        slug = _extract_domain_slug(str(p.get("path") or ""))
        if slug:
            page_by_slug[slug] = str(p.get("content") or "")[:500]

    candidate_desc = []
    for c in candidates[:5]:  # Limit to top 5 candidates
        s_content = page_by_slug.get(c["source"], "")[:200]
        t_content = page_by_slug.get(c["target"], "")[:200]
        candidate_desc.append(
            f"- {c['source']} (similarity={c['similarity']:.3f}):\n"
            f"  Source: {s_content}\n"
            f"  Target: {t_content}"
        )

    prompt = (
        "Review the following domain merge candidates. Each pair has high semantic similarity.\n"
        "Approve merges ONLY if the domains genuinely describe the same business functionality.\n"
        "Respond in JSON: {\"approved_merges\": [{\"source\": \"...\", \"target\": \"...\"}]}\n\n"
        + "\n".join(candidate_desc)
    )

    from wiki.json_robust import parse_json_robust_sync

    response = await llm.chat_complete(prompt)
    parsed = parse_json_robust_sync(response)
    if isinstance(parsed, dict):
        return parsed.get("approved_merges", [])
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestReassembleDomainsNode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/reassemble_domains.py tests/wiki/test_reassemble_domains.py
git commit -m "feat(wiki): implement reassemble_domains_node with merge + orphan + rollback"
```

---

### Task 7: Wire into pipeline graph

**Files:**
- Modify: `wiki/pipeline_graph.py:340-346`
- Modify: `wiki/pipeline_nodes.py`
- Test: `tests/wiki/test_reassemble_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_reassemble_integration.py
"""Integration test: reassemble_domains is wired into the pipeline graph."""
from __future__ import annotations

import pytest


class TestReassemblyPipelineWiring:
    def test_reassemble_node_exists_in_graph(self):
        from wiki.pipeline_graph import build_wiki_pipeline

        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "reassemble_domains" in node_names

    def test_reassemble_between_parent_pages_and_quality_gate(self):
        from wiki.pipeline_graph import build_wiki_pipeline

        pipeline = build_wiki_pipeline(checkpointer=False)
        graph_data = pipeline.get_graph()
        edges = [(e.source, e.target) for e in graph_data.edges]
        assert ("compose_parent_pages", "reassemble_domains") in edges
        assert ("reassemble_domains", "quality_gate") in edges
        assert ("compose_parent_pages", "quality_gate") not in edges
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_reassemble_integration.py -v`
Expected: FAIL with `AssertionError` (node doesn't exist / edges wrong)

- [ ] **Step 3: Modify pipeline_graph.py and pipeline_nodes.py**

In `wiki/pipeline_nodes.py`, add the import:
```python
from wiki.nodes.reassemble_domains import reassemble_domains_node
```

And add `"reassemble_domains_node"` to `__all__`.

In `wiki/pipeline_graph.py`:

1. Add import at top:
```python
from wiki.pipeline_nodes import reassemble_domains_node
```

2. Add node and change edges (around line 343-346):

Replace:
```python
    graph.add_edge("compose_parent_pages", "quality_gate")
```

With:
```python
    graph.add_node(
        "reassemble_domains",
        _with_progress("reassemble_domains", reassemble_domains_node),
    )
    graph.add_edge("compose_parent_pages", "reassemble_domains")
    graph.add_edge("reassemble_domains", "quality_gate")
```

3. Add to `_NODE_PHASE_MAP`:
```python
    "reassemble_domains": ("reassemble_domains", 0.65),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_reassemble_integration.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run pytest tests/wiki/ -x --timeout=120 -q`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add wiki/pipeline_graph.py wiki/pipeline_nodes.py tests/wiki/test_reassemble_integration.py
git commit -m "feat(wiki): wire reassemble_domains into pipeline graph"
```

---

### Task 8: Degradation tests

**Files:**
- Test: `tests/wiki/test_reassemble_domains.py`

- [ ] **Step 1: Write degradation tests**

```python
# Append to tests/wiki/test_reassemble_domains.py

class TestReassemblyDegradation:
    @pytest.mark.asyncio
    async def test_embedding_failure_skips_gracefully(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": "domain-a/_overview", "content": "Auth content"},
                {"path": "domain-b/_overview", "content": "Payment content"},
            ],
            "domain_mapping": {"domain-a": [], "domain-b": []},
            "domain_tree": [],
            "config": {},
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(side_effect=RuntimeError("embedding service down"))

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator):
            result = await reassemble_domains_node(state)

        assert result["reassembly_actions"] == []

    @pytest.mark.asyncio
    async def test_pinned_domains_not_merged(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": "domain-a/_overview", "content": "Auth content matching"},
                {"path": "domain-b/_overview", "content": "Auth content matching very similar"},
            ],
            "domain_mapping": {"domain-a": [("repo", "ModA")], "domain-b": [("repo", "ModB")]},
            "domain_tree": [{"slug": "domain-a"}, {"slug": "domain-b"}],
            "domain_display_names": {"domain-a": "A", "domain-b": "B"},
            "config": {},
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[[1.0] * 1024, [1.0] * 1024])

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value={"domain-a"}):
            result = await reassemble_domains_node(state)

        # Pinned domain prevents merge candidate from being found
        assert "domain-a" in result.get("domain_mapping", state["domain_mapping"])
        assert "domain-b" in result.get("domain_mapping", state["domain_mapping"])
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/wiki/test_reassemble_domains.py::TestReassemblyDegradation -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/wiki/test_reassemble_domains.py
git commit -m "test(wiki): add reassembly degradation and pinned domain tests"
```

---

### Task 9: Simplify `_adopt_orphan_domain_pages` in tree_linker

**Files:**
- Modify: `wiki/tree_linker.py`
- Test: existing tests should still pass

- [ ] **Step 1: Check existing tree_linker tests**

Run: `uv run pytest tests/ -k "adopt_orphan" -v --co`
Expected: Lists any existing tests related to orphan adoption

- [ ] **Step 2: Modify tree_linker.py**

In `wiki/tree_linker.py`, find `_adopt_orphan_domain_pages` and add an early-exit when reassembly is enabled:

```python
async def _adopt_orphan_domain_pages(self, ...):
    """..."""
    settings = get_settings().wiki
    if settings.domain_reassembly_enabled:
        log.info("adopt_orphan_skipped", reason="reassembly_handles_orphans")
        return
    # ... existing logic unchanged ...
```

- [ ] **Step 3: Run tests to confirm no regression**

Run: `uv run pytest tests/wiki/ -x --timeout=120 -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/tree_linker.py
git commit -m "refactor(wiki): skip orphan adoption when reassembly enabled"
```

---

### Task 10: Final integration verification

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/wiki/ --timeout=120 -q`
Expected: All tests pass

- [ ] **Step 2: Run linter**

Run: `uv run ruff check wiki/nodes/reassemble_domains.py core/config.py wiki/pipeline_graph.py wiki/pipeline_nodes.py wiki/pipeline_state.py`
Expected: No errors

- [ ] **Step 3: Run type check (optional)**

Run: `uv run ruff format wiki/nodes/reassemble_domains.py`
Expected: Formatted

- [ ] **Step 4: Final commit (if any lint fixes)**

```bash
git add -A
git commit -m "chore: lint fixes for reassembly feature"
```
