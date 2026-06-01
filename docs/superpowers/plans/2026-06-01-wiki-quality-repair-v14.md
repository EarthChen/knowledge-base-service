# Wiki Quality Repair V14 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 P0 wiki quality issues (compound serial titles, domain duplicates, low coverage, cross-domain misplacement, weak H2 structure) plus add 3 project-understanding enhancements (F7/F8/F9).

**Architecture:** Pipeline enrichment at domain decompose + namer stages (F7-F9), slug collision handling (F1), topic generation fix (F2-F4), post-cluster validation (F5), quality gate (F6). All fixes operate independently within the existing LangGraph pipeline; no schema changes.

**Tech Stack:** Python 3.12, FalkorDB (graph queries for module paths), Tree-sitter (already indexed), structlog, pytest + pytest-asyncio

**Spec:** [`docs/superpowers/specs/wiki-quality-repair-v14.md`](../specs/wiki-quality-repair-v14.md)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `wiki/project_doc_provider.py` | Discover & read project docs from FS | **Create** |
| `wiki/pipeline_orchestrator.py` | Inject project_docs into configurable | Modify |
| `wiki/graph_domain_namer.py` | Add file tree + topology hint + project doc context | Modify |
| `wiki/domain_semantic_clusterer.py` | Add `_post_cluster_reparent` + `_path_matches_cluster` | Modify |
| `wiki/nodes/graph_domain_decompose.py` | Fix `_dedup_parallel_naming_results` to merge | Modify |
| `wiki/domain_doc_agent.py` | Fix `final_overview` dead code + mechanical split | Modify |
| `wiki/nodes/finalize.py` | Rewrite `_disambiguation_parts` | Modify |
| `wiki/nodes/quality_gate.py` | Add H2 count check | Modify |
| `tests/wiki/test_project_doc_provider.py` | Tests for F7 | **Create** |
| `tests/wiki/test_graph_domain_namer_context.py` | Tests for F8+F9 | **Create** |
| `tests/wiki/test_post_cluster_reparent.py` | Tests for F5 | **Create** |
| `tests/wiki/nodes/test_dedup_merge.py` | Tests for F1 | **Create** |
| `tests/wiki/test_mechanical_chunk_title.py` | Tests for F2 | **Create** |
| `tests/wiki/nodes/test_finalize_disambiguation.py` | Tests for F3 | **Create** |
| `tests/wiki/nodes/test_quality_gate_h2.py` | Tests for F6 | **Create** |

---

### Task 1: F7 — Project Doc Provider

**Files:**
- Create: `wiki/project_doc_provider.py`
- Test: `tests/wiki/test_project_doc_provider.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_project_doc_provider.py
from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a fake repo with AGENTS.md."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Project\n\n## Tech Stack\n\nPython, FastAPI\n\n## Modules\n\n- auth\n- user\n")
    return tmp_path


@pytest.fixture
def tmp_repo_with_links(tmp_path: Path) -> Path:
    """Create a fake repo with AGENTS.md that links to sub-docs."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Project\n\nSee [arch](docs/ARCHITECTURE.md) for details.\n"
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n\n## Layers\n\nService layer\n")
    return tmp_path


def test_discover_finds_agents_md(tmp_repo: Path):
    from wiki.project_doc_provider import discover_project_docs

    result = discover_project_docs({"test-repo": str(tmp_repo)})
    assert len(result) == 1
    assert result[0]["repo"] == "test-repo"
    assert result[0]["path"] == "AGENTS.md"
    assert "# Project" in result[0]["lines"][0]
    assert result[0]["total_lines"] >= 5


def test_discover_follows_markdown_links(tmp_repo_with_links: Path):
    from wiki.project_doc_provider import discover_project_docs

    result = discover_project_docs({"test-repo": str(tmp_repo_with_links)})
    assert len(result) == 2
    paths = [r["path"] for r in result]
    assert "AGENTS.md" in paths
    assert "docs/ARCHITECTURE.md" in paths


def test_discover_empty_repo(tmp_path: Path):
    from wiki.project_doc_provider import discover_project_docs

    result = discover_project_docs({"test-repo": str(tmp_path)})
    assert result == []


def test_discover_respects_line_limit(tmp_path: Path):
    from wiki.project_doc_provider import discover_project_docs, MAX_MAIN_DOC_LINES

    big_file = tmp_path / "AGENTS.md"
    big_file.write_text("\n".join([f"line {i}" for i in range(500)]))
    result = discover_project_docs({"test-repo": str(tmp_path)})
    assert len(result[0]["lines"]) == MAX_MAIN_DOC_LINES


def test_format_for_namer():
    from wiki.project_doc_provider import format_for_namer

    docs = [{"repo": "r", "path": "AGENTS.md", "lines": ["# Project", "", "## Modules", "- auth", "- user"], "total_lines": 5, "priority": 0}]
    result = format_for_namer(docs)
    assert "auth" in result
    assert "user" in result
    assert isinstance(result, str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_project_doc_provider.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'wiki.project_doc_provider'"

- [ ] **Step 3: Implement `wiki/project_doc_provider.py`**

```python
"""Project documentation discovery for wiki pipeline enrichment.

Reads AGENTS.md / CLAUDE.md / README.md from repository clone roots,
following Markdown links to sub-documents. Mimics the approach used by
Codex CLI, OpenCode, and Cline for project understanding.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

META_DOC_PRIORITY = ["AGENTS.md", "CLAUDE.md", "README.md", "readme.md"]
MAX_MAIN_DOC_LINES = 300
MAX_SUB_DOC_LINES = 200
MAX_LINKED_DOCS = 5
MAX_TOTAL_LINES = 1000

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")


def _safe_read_lines(path: Path, max_lines: int) -> list[str]:
    """Read file as lines, consistent with read_file tool behavior."""
    try:
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return all_lines[:max_lines]
    except (OSError, PermissionError):
        return []


def _extract_md_links(lines: list[str]) -> list[str]:
    """Extract relative .md link targets from Markdown content."""
    links: list[str] = []
    for line in lines:
        for _label, href in _MD_LINK_RE.findall(line):
            if not href.startswith("http") and not href.startswith("#"):
                links.append(href)
    return links


def discover_project_docs(repo_paths: dict[str, str]) -> list[dict[str, Any]]:
    """Discover and read project meta-documents from repository clone dirs.

    Returns list of dicts: [{repo, path, lines, total_lines, priority}]
    """
    results: list[dict[str, Any]] = []
    total_lines_read = 0

    for repo_id, root_str in repo_paths.items():
        root = Path(root_str)
        if not root.is_dir():
            continue

        main_doc: Path | None = None
        for i, name in enumerate(META_DOC_PRIORITY):
            candidate = root / name
            if candidate.is_file():
                main_doc = candidate
                priority = i
                break

        if main_doc is None:
            continue

        lines = _safe_read_lines(main_doc, MAX_MAIN_DOC_LINES)
        if not lines:
            continue

        total_lines_read += len(lines)
        results.append({
            "repo": repo_id,
            "path": main_doc.name,
            "lines": lines,
            "total_lines": len(lines),
            "priority": priority,
        })

        if total_lines_read >= MAX_TOTAL_LINES:
            break

        linked_paths = _extract_md_links(lines)
        for link_path in linked_paths[:MAX_LINKED_DOCS]:
            if total_lines_read >= MAX_TOTAL_LINES:
                break
            sub_path = root / link_path
            if not sub_path.is_file():
                continue
            sub_lines = _safe_read_lines(sub_path, MAX_SUB_DOC_LINES)
            if sub_lines:
                total_lines_read += len(sub_lines)
                results.append({
                    "repo": repo_id,
                    "path": link_path,
                    "lines": sub_lines,
                    "total_lines": len(sub_lines),
                    "priority": priority + 10,
                })

    return results


def format_for_namer(docs: list[dict[str, Any]]) -> str:
    """Format project docs as context block for domain namer prompt."""
    if not docs:
        return ""

    parts: list[str] = ["Project documentation context:"]
    for doc in docs:
        lines = doc.get("lines", [])
        if not lines:
            continue
        header = f"\n--- {doc['path']} ---"
        parts.append(header)
        parts.extend(lines[:50])
        if len(lines) > 50:
            parts.append(f"... ({len(lines) - 50} more lines)")

    return "\n".join(parts)


def format_for_page_agent(docs: list[dict[str, Any]], domain: str = "") -> str:
    """Format project docs as background context for page agent."""
    if not docs:
        return ""

    parts: list[str] = ["## Project Background"]
    for doc in docs:
        lines = doc.get("lines", [])
        if not lines:
            continue
        parts.append(f"\n### From {doc['path']}:")
        parts.extend(lines[:80])

    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_project_doc_provider.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/project_doc_provider.py tests/wiki/test_project_doc_provider.py
git commit -m "feat(wiki): add project_doc_provider for F7 project doc injection"
```

---

### Task 2: F8 — File Tree Context Injection

**Files:**
- Modify: `wiki/graph_domain_namer.py`
- Test: `tests/wiki/test_graph_domain_namer_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_graph_domain_namer_context.py
from __future__ import annotations

import pytest


def test_build_file_tree_context_basic():
    from wiki.graph_domain_namer import _build_file_tree_context

    modules = [
        {"name": "RelationRankService", "path": "src/relation/rank/RelationRankService.java"},
        {"name": "RelationRankDao", "path": "src/relation/rank/RelationRankDao.java"},
        {"name": "RelationScoreCalc", "path": "src/relation/rank/RelationScoreCalc.java"},
    ]
    result = _build_file_tree_context(modules)
    assert "src/relation/rank/" in result
    assert "RelationRankService.java" in result


def test_build_file_tree_context_empty():
    from wiki.graph_domain_namer import _build_file_tree_context

    result = _build_file_tree_context([])
    assert result == ""


def test_build_file_tree_context_no_paths():
    from wiki.graph_domain_namer import _build_file_tree_context

    modules = [{"name": "Foo", "path": ""}]
    result = _build_file_tree_context(modules)
    assert result == ""


def test_topology_label_majority():
    from wiki.graph_domain_namer import _topology_label

    modules = [
        {"name": "RelationRankService", "path": "src/relation/rank/RelationRankService.java"},
        {"name": "RelationRankDao", "path": "src/relation/rank/RelationRankDao.java"},
        {"name": "RelationScoreCalc", "path": "src/relation/score/RelationScoreCalc.java"},
        {"name": "UserProfileHelper", "path": "src/user/UserProfileHelper.java"},
    ]
    result = _topology_label(modules)
    assert result["slug_hint"] == "relation"
    assert result["confidence"] >= 0.7


def test_topology_label_no_majority():
    from wiki.graph_domain_namer import _topology_label

    modules = [
        {"name": "AlphaService", "path": "a/AlphaService.java"},
        {"name": "BetaHandler", "path": "b/BetaHandler.java"},
        {"name": "GammaDao", "path": "c/GammaDao.java"},
    ]
    result = _topology_label(modules)
    assert result["slug_hint"] == ""
    assert result["confidence"] < 0.4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_graph_domain_namer_context.py -v`
Expected: FAIL with "cannot import name '_build_file_tree_context'"

- [ ] **Step 3: Implement F8+F9 in `wiki/graph_domain_namer.py`**

Add the following functions to `wiki/graph_domain_namer.py`:

```python
def _build_file_tree_context(modules: list[dict]) -> str:
    """Build a concise directory tree from community module paths (Cline-inspired)."""
    from collections import defaultdict

    dirs: defaultdict[str, list[str]] = defaultdict(list)
    for m in modules:
        path = m.get("path") or ""
        if not path:
            continue
        parts = path.replace("\\", "/").rsplit("/", 1)
        dir_part = parts[0] if len(parts) > 1 else ""
        file_part = parts[-1]
        if dir_part:
            dirs[dir_part].append(file_part)

    if not dirs:
        return ""

    lines = ["Directory structure of this module group:"]
    for dir_path in sorted(dirs.keys()):
        files = sorted(dirs[dir_path])[:8]
        lines.append(f"  {dir_path}/")
        for f in files:
            lines.append(f"    {f}")
        if len(dirs[dir_path]) > 8:
            lines.append(f"    ... (+{len(dirs[dir_path]) - 8} more)")

    return "\n".join(lines)


def _topology_label(modules: list[dict]) -> dict[str, Any]:
    """Derive a domain label from module name topology (RepoNova-inspired).

    Uses majority-vote on business prefixes extracted from module names.
    Zero LLM tokens — pure string analysis.
    """
    from collections import Counter

    prefixes: list[str] = []
    for m in modules:
        name = m.get("name") or ""
        path = m.get("path") or ""
        prefix = _extract_business_prefix_from(name, path)
        if prefix:
            prefixes.append(prefix)

    if not prefixes:
        return {"slug_hint": "", "confidence": 0.0}

    counter = Counter(prefixes)
    total = len(prefixes)
    top_prefix, top_count = counter.most_common(1)[0]

    confidence = top_count / total
    if confidence < 0.4:
        return {"slug_hint": "", "confidence": confidence}

    return {"slug_hint": top_prefix, "confidence": confidence}


def _extract_business_prefix_from(name: str, path: str) -> str | None:
    """Extract business prefix from module name or path."""
    import re
    # Try path-based extraction first
    if path:
        segments = path.replace("\\", "/").split("/")
        for seg in segments:
            if seg and seg.lower() not in {"src", "main", "java", "com", "kotlin", "python", "lib", "internal", "pkg"}:
                clean = seg.split(".")[0].lower()
                if clean and len(clean) > 2:
                    return clean
    # Fallback to CamelCase first word
    words = re.findall(r"[A-Z][a-z]+", name)
    skip = {"Abstract", "Base", "Default", "Mock", "Test", "I"}
    for word in words:
        if word not in skip and word.lower() not in {"service", "dao", "handler", "controller", "manager", "impl"}:
            return word.lower()
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_graph_domain_namer_context.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/graph_domain_namer.py tests/wiki/test_graph_domain_namer_context.py
git commit -m "feat(wiki): add file tree context and topology labels (F8+F9)"
```

---

### Task 3: F1 — Slug Stem Merge

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py`
- Test: `tests/wiki/nodes/test_dedup_merge.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/nodes/test_dedup_merge.py
from __future__ import annotations

import pytest


def test_slug_collision_merges_instead_of_suffix():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "relation-rank", "display_name": "关系排名", "modules": ["RankService"]},
        {"slug": "relation-rank", "display_name": "关系排名服务", "modules": ["RankDao"]},
    ]
    deduped = _dedup_parallel_naming_results(results, set())
    assert len(deduped) == 1
    assert deduped[0]["slug"] == "relation-rank"
    assert "RankService" in deduped[0]["modules"]
    assert "RankDao" in deduped[0]["modules"]


def test_stem_suffix_merge():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "quick-message", "display_name": "快捷消息", "modules": ["QuickMsg"]},
        {"slug": "quick-message-service", "display_name": "快捷消息服务", "modules": ["QuickMsgSvc"]},
    ]
    deduped = _dedup_parallel_naming_results(results, set())
    assert len(deduped) == 1
    assert deduped[0]["slug"] == "quick-message"


def test_collision_with_existing_slugs_uses_numeric():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "auth", "display_name": "认证", "modules": ["AuthSvc"]},
    ]
    deduped = _dedup_parallel_naming_results(results, {"auth"})
    assert len(deduped) == 1
    assert deduped[0]["slug"] == "auth-2"


def test_no_collision_passes_through():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "user-profile", "display_name": "用户资料", "modules": ["UserProfile"]},
        {"slug": "family-system", "display_name": "家族系统", "modules": ["FamilySvc"]},
    ]
    deduped = _dedup_parallel_naming_results(results, set())
    assert len(deduped) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/nodes/test_dedup_merge.py -v`
Expected: FAIL (current implementation creates suffix instead of merging)

- [ ] **Step 3: Modify `_dedup_parallel_naming_results` in `wiki/nodes/graph_domain_decompose.py`**

Replace the current dedup logic with the merge-first approach from the spec (see V14 spec §3 F1).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/nodes/test_dedup_merge.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Run existing tests for regression**

Run: `uv run pytest tests/wiki/nodes/test_graph_domain_decompose.py -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/graph_domain_decompose.py tests/wiki/nodes/test_dedup_merge.py
git commit -m "fix(wiki): merge duplicate slugs instead of suffixing (F1)"
```

---

### Task 4: F5 — Post-Cluster Reparent

**Files:**
- Modify: `wiki/domain_semantic_clusterer.py`
- Test: `tests/wiki/test_post_cluster_reparent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_post_cluster_reparent.py
from __future__ import annotations

import pytest


def test_reparent_moves_misplaced_module():
    from wiki.domain_semantic_clusterer import DomainSemanticClusterer

    clusterer = DomainSemanticClusterer.__new__(DomainSemanticClusterer)
    clusters = [
        {("repo", "FamilyTaskService"), ("repo", "FamilyRewardService"), ("repo", "FamilyManager")},
        {("repo", "RelationRankService"), ("repo", "RelationScoreDao"), ("repo", "RelationFamilyTaskService")},
    ]
    paths = {
        "FamilyTaskService": "src/family/FamilyTaskService.java",
        "FamilyRewardService": "src/family/FamilyRewardService.java",
        "FamilyManager": "src/family/FamilyManager.java",
        "RelationRankService": "src/relation/rank/RelationRankService.java",
        "RelationScoreDao": "src/relation/rank/RelationScoreDao.java",
        "RelationFamilyTaskService": "src/family/task/RelationFamilyTaskService.java",
    }
    result = clusterer._post_cluster_reparent(clusters, [], paths)
    # RelationFamilyTaskService should move to family cluster
    family_cluster = next(c for c in result if ("repo", "FamilyTaskService") in c)
    assert ("repo", "RelationFamilyTaskService") in family_cluster


def test_reparent_no_move_when_no_clear_majority():
    from wiki.domain_semantic_clusterer import DomainSemanticClusterer

    clusterer = DomainSemanticClusterer.__new__(DomainSemanticClusterer)
    clusters = [
        {("repo", "AlphaService"), ("repo", "BetaHandler")},
        {("repo", "GammaDao"), ("repo", "DeltaManager")},
    ]
    paths = {}
    result = clusterer._post_cluster_reparent(clusters, [], paths)
    # No moves expected — no clear dominant prefix
    assert len(result[0]) == 2
    assert len(result[1]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_post_cluster_reparent.py -v`
Expected: FAIL with "has no attribute '_post_cluster_reparent'"

- [ ] **Step 3: Implement `_post_cluster_reparent` and `_path_matches_cluster`**

Add the methods from V14 spec §3 F5 to `wiki/domain_semantic_clusterer.py`.

- [ ] **Step 4: Wire into `cluster()` method**

Call `_post_cluster_reparent` at the end of the `cluster()` method before returning.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_post_cluster_reparent.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Run existing tests for regression**

Run: `uv run pytest tests/wiki/test_domain_semantic_clusterer.py -v`
Expected: All existing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/domain_semantic_clusterer.py tests/wiki/test_post_cluster_reparent.py
git commit -m "fix(wiki): add post-cluster reparent for cross-domain misplacement (F5)"
```

---

### Task 5: F4 — Coverage Fix (final_overview + min_modules)

**Files:**
- Modify: `wiki/domain_doc_agent.py`
- Modify: `core/config.py`

- [ ] **Step 1: Find and fix the dead code**

Search for `final_overview` assignment in `wiki/domain_doc_agent.py` and ensure it gets set before `plan_topics` checks it.

- [ ] **Step 2: Change `plan_topics_min_modules` from 2 to 1**

In `core/config.py`, find `plan_topics_min_modules` and change to 1.

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/wiki/ -k "domain_doc_agent or plan_topics" -v`
Expected: PASS (behavior change is intentional)

- [ ] **Step 4: Commit**

```bash
git add wiki/domain_doc_agent.py core/config.py
git commit -m "fix(wiki): fix final_overview dead code + lower min_modules to 1 (F4)"
```

---

### Task 6: F2+F3 — Chunk Title Semanticization + Disambiguation

**Files:**
- Modify: `wiki/domain_doc_agent.py`
- Modify: `wiki/nodes/finalize.py`
- Test: `tests/wiki/test_mechanical_chunk_title.py`
- Test: `tests/wiki/nodes/test_finalize_disambiguation.py`

- [ ] **Step 1: Write tests for F2 (`_common_camel_prefix`)**

```python
# tests/wiki/test_mechanical_chunk_title.py
from __future__ import annotations

import pytest


def test_common_camel_prefix_basic():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix(["RelationRankService", "RelationRankDao", "RelationRankCalc"])
    assert result == "RelationRank"


def test_common_camel_prefix_single_word():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix(["UserService", "UserDao"])
    # Only 1 common segment, need >= 2
    assert result == ""


def test_common_camel_prefix_no_common():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix(["AlphaService", "BetaHandler"])
    assert result == ""
```

- [ ] **Step 2: Write tests for F3 (`_extract_first_h2_theme`)**

```python
# tests/wiki/nodes/test_finalize_disambiguation.py
from __future__ import annotations

import pytest


def test_extract_first_h2_theme():
    from wiki.nodes.finalize import _extract_first_h2_theme

    page = {"content": "# Title\n\n## 排名计算\n\nContent here\n\n## 总结\n\nEnd"}
    result = _extract_first_h2_theme(page)
    assert result == "排名计算"


def test_extract_first_h2_theme_skips_generic():
    from wiki.nodes.finalize import _extract_first_h2_theme

    page = {"content": "# Title\n\n## 概述\n\nContent\n\n## 核心逻辑\n\nDetails"}
    result = _extract_first_h2_theme(page)
    assert result == "核心逻辑"


def test_disambiguation_no_domain_slug():
    from wiki.nodes.finalize import _disambiguation_parts

    page = {"content": "# Title\n\n## 排名计算\n\nStuff"}
    result = _disambiguation_parts(page, level=0, seq=1)
    assert "排名计算" in result
    # Should NOT contain domain slug
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_mechanical_chunk_title.py tests/wiki/nodes/test_finalize_disambiguation.py -v`
Expected: FAIL

- [ ] **Step 4: Implement F2 in `wiki/domain_doc_agent.py`**

Add `_common_camel_prefix` function and modify `_build_mechanical_topic_split`.

- [ ] **Step 5: Implement F3 in `wiki/nodes/finalize.py`**

Add `_extract_first_h2_theme` and rewrite `_disambiguation_parts`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/wiki/test_mechanical_chunk_title.py tests/wiki/nodes/test_finalize_disambiguation.py -v`
Expected: All tests PASS

- [ ] **Step 7: Run full finalize test suite for regression**

Run: `uv run pytest tests/wiki/nodes/test_finalize*.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add wiki/domain_doc_agent.py wiki/nodes/finalize.py tests/wiki/test_mechanical_chunk_title.py tests/wiki/nodes/test_finalize_disambiguation.py
git commit -m "fix(wiki): semantic chunk titles + H2-based disambiguation (F2+F3)"
```

---

### Task 7: F6 — H2 Quality Gate

**Files:**
- Modify: `wiki/nodes/quality_gate.py`
- Test: `tests/wiki/nodes/test_quality_gate_h2.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/nodes/test_quality_gate_h2.py
from __future__ import annotations

import pytest


def test_h2_check_topic_insufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\n## Only One Section\n\nContent"
    result = _check_h2_structure(content, "topic")
    assert result is not None
    assert "insufficient" in result.code


def test_h2_check_topic_sufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\n## Section 1\n\n## Section 2\n\n## Section 3\n\n"
    result = _check_h2_structure(content, "topic")
    assert result is None


def test_h2_check_overview_sufficient():
    from wiki.nodes.quality_gate import _check_h2_structure

    content = "# Title\n\n## Section 1\n\n## Section 2\n\n"
    result = _check_h2_structure(content, "overview")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate_h2.py -v`
Expected: FAIL with "cannot import name '_check_h2_structure'"

- [ ] **Step 3: Implement `_check_h2_structure`**

Add to `wiki/nodes/quality_gate.py` per V14 spec §3 F6.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate_h2.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run existing quality_gate tests**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate*.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/quality_gate.py tests/wiki/nodes/test_quality_gate_h2.py
git commit -m "feat(wiki): add H2 count quality gate (F6)"
```

---

### Task 8: Pipeline Wiring

**Files:**
- Modify: `wiki/pipeline_orchestrator.py`
- Modify: `wiki/graph_domain_namer.py` (inject context into naming call)

- [ ] **Step 1: Wire `discover_project_docs` into pipeline orchestrator**

In `wiki/pipeline_orchestrator.py`, after `_repo_paths` is resolved, add:
```python
if _repo_paths:
    from wiki.project_doc_provider import discover_project_docs
    configurable["project_docs"] = discover_project_docs(_repo_paths)
```

- [ ] **Step 2: Wire file tree + topology + project docs into `name_community`**

In `wiki/graph_domain_namer.py`, modify `name_community()` to:
1. Build `_build_file_tree_context(modules)` 
2. Compute `_topology_label(modules)`
3. Format project docs with `format_for_namer(project_docs)`
4. Combine into `business_context_block`

- [ ] **Step 3: Run full pipeline tests**

Run: `uv run pytest tests/wiki/ -x --timeout=60`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/pipeline_orchestrator.py wiki/graph_domain_namer.py
git commit -m "feat(wiki): wire F7+F8+F9 context into pipeline orchestrator"
```

---

### Task 9: Integration Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/wiki/ -n auto --timeout=120`
Expected: All pass, no regressions

- [ ] **Step 2: Run linter**

Run: `uv run ruff check wiki/ tests/wiki/`
Expected: No errors

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -A && git commit -m "chore: cleanup after V14 implementation"
```
