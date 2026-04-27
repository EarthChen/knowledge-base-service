# SP6: Knowledge Compilation + Deep Research — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable cross-entity concept consolidation, inline wikilinks in generated content, multi-turn deep research mode, and business flow visualization.

**Architecture:** ConceptMerger detects cross-repo similar entities via embedding similarity and generates consolidated ConceptPages. WikiComposer injects entity index into LLM prompt for [[wikilink]] generation. DeepResearchService orchestrates multi-turn Q&A with sub-question decomposition. BusinessFlowGraph renders existing BusinessFlow nodes using xyflow.

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB, React 19, @xyflow/react, pytest, Vitest

---

### Task 1: Cross-Entity Concept Merger

**Files:**
- Create: `wiki/concept_merger.py`
- Test: `tests/wiki/test_concept_merger.py`

- [ ] **Step 1: Write failing test for concept detection**

```python
# tests/wiki/test_concept_merger.py
import pytest
from wiki.concept_merger import ConceptMerger


@pytest.mark.asyncio
async def test_finds_similar_entities_across_repos():
    """Entities with embedding similarity > threshold should be detected."""
    # Setup mock with two WikiPages from different repos, similar embeddings
    # Assert ConceptMerger returns them as a merge candidate
    pass
```

- [ ] **Step 2: Implement ConceptMerger**

```python
# wiki/concept_merger.py
"""Detect and merge similar concepts across repositories."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from log import get_logger

log = get_logger(__name__)


@dataclass
class MergeCandidate:
    page_uid_a: str
    page_uid_b: str
    similarity: float
    title_a: str
    title_b: str


class ConceptMerger:
    def __init__(self, wiki_store: Any, similarity_threshold: float = 0.9) -> None:
        self._store = wiki_store
        self._threshold = similarity_threshold

    async def find_candidates(self, business_id: str) -> list[MergeCandidate]:
        """Find cross-repo WikiPage pairs with embedding similarity above threshold."""
        ...

    async def generate_concept_page(self, candidate: MergeCandidate, llm: Any) -> dict[str, Any]:
        """Generate a consolidated ConceptPage from two similar entity pages."""
        ...
```

- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

---

### Task 2: Inline Wikilinks

**Files:**
- Modify: `wiki/composer.py` (add entity index to LLM prompt)
- Create: `wiki/wikilink_resolver.py` (post-process [[links]])
- Test: `tests/wiki/test_wikilink_resolver.py`

- [ ] **Step 1: Write test for wikilink resolution**

```python
# tests/wiki/test_wikilink_resolver.py
from wiki.wikilink_resolver import resolve_wikilinks

def test_resolves_known_entity():
    entity_index = {"AuthService": "/wiki/auth/AuthService"}
    content = "This module depends on [[AuthService]] for token validation."
    result = resolve_wikilinks(content, entity_index)
    assert "[AuthService](/wiki/auth/AuthService)" in result
    assert "[[AuthService]]" not in result

def test_preserves_unknown_entity():
    content = "Uses [[UnknownThing]] for something."
    result = resolve_wikilinks(content, {})
    assert "UnknownThing" in result
```

- [ ] **Step 2: Implement wikilink_resolver.py**
- [ ] **Step 3: Add entity index injection to WikiComposer prompt**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 3: Deep Research Mode — Backend

**Files:**
- Create: `wiki/deep_research.py`
- Modify: `api/routes/wiki_routes.py` (add deep research endpoint)
- Test: `tests/wiki/test_deep_research.py`

- [ ] **Step 1: Write failing test for research decomposition**
- [ ] **Step 2: Implement DeepResearchService with sub-question generation**
- [ ] **Step 3: Add SSE streaming endpoint for research results**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 4: Deep Research Mode — Frontend

**Files:**
- Create: `dashboard/src/components/wiki/DeepResearchPanel.tsx`
- Modify: `dashboard/src/components/wiki/AskPanel.tsx` (add research toggle)
- Test: `dashboard/src/components/wiki/__tests__/DeepResearchPanel.test.tsx`

- [ ] **Step 1: Write failing test**
- [ ] **Step 2: Implement DeepResearchPanel with multi-turn display**
- [ ] **Step 3: Add research mode toggle to AskPanel**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 5: Business Flow Visualization

**Files:**
- Create: `dashboard/src/components/wiki/WikiBusinessFlowGraph.tsx`
- Create: `dashboard/src/hooks/useBusinessFlows.ts`
- Modify: `dashboard/src/components/wiki/WikiShell.tsx` (add flow tab)
- Test: `dashboard/src/components/wiki/__tests__/WikiBusinessFlowGraph.test.tsx`

- [ ] **Step 1: Write failing test**
- [ ] **Step 2: Implement useBusinessFlows hook (fetch BusinessFlow nodes)**
- [ ] **Step 3: Implement WikiBusinessFlowGraph using @xyflow/react**
- [ ] **Step 4: Add "Flows" tab to WikiShell (lazy-loaded)**
- [ ] **Step 5: Run tests**
- [ ] **Step 6: Commit**

---

### Task 6: Feature Flags

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add deep_research_enabled, concept_merging_enabled, concept_merge_similarity_threshold to WikiConfig**
- [ ] **Step 2: Guard all new features behind flags**
- [ ] **Step 3: Commit**
