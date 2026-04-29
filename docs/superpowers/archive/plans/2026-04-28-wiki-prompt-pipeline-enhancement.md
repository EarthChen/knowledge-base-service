# Wiki Prompt Pipeline Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize wiki page quality by enriching LLM prompts with all available graph properties, code comments, structured output templates, and progressive persistence for crash resilience.

**Architecture:** Three progressive modules — Module 1 (Prompt Pipeline + Resilience: fix mode, enhance digest, inject context, structured output, progressive persist), Module 2 (Comment Extraction: parser enhancements, filter pipeline, graph integration), Module 3 (Architecture Overview: LLM repo overview, nav cleanup). Each module is independently deliverable.

**Tech Stack:** Python 3.11+, FastAPI, tree-sitter, FalkorDB, React 19 (dashboard), TypeScript

**Spec:** `docs/superpowers/specs/2026-04-28-wiki-prompt-pipeline-enhancement-design.md`

---

## File Map

### Module 1: Prompt Pipeline + Resilience
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `dashboard/src/hooks/useWikiRegenerate.ts` | Fix mode default |
| Modify | `dashboard/src/api/client.ts` | Fix default mode parameter |
| Modify | `wiki/composer.py` | Enhance `_entity_digest`, add structured output template |
| Modify | `wiki/service.py` | Incremental context fix, progressive persist, resume |
| Modify | `config.py` | Add progressive persist config flags |

### Module 2: Comment Extraction
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `indexer/tree_sitter_parser.py` | Module docstring, file header comment, Javadoc backward traversal |
| Create | `indexer/comment_filter.py` | License/trivial/commented-code filtering |
| Modify | `indexer/code_graph_builder.py` | Store Module docstring in graph |
| Modify | `wiki/composer.py` | Inject Module docstring into digest |
| Create | `tests/test_comment_filter.py` | Filter unit tests |

### Module 3: Architecture Overview
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `wiki/composer.py` | LLM-driven overview page, remove nav from content |
| Modify | `wiki/context.py` | Accept module summaries in `build_repository_context` |

---

## Module 1: Prompt Pipeline + Resilience

### Task 1: Fix mode Default Value

**Files:**
- Modify: `dashboard/src/hooks/useWikiRegenerate.ts:155`
- Modify: `dashboard/src/api/client.ts:128`

- [ ] **Step 1: Fix `useWikiRegenerate.ts` mode assignment**

In `dashboard/src/hooks/useWikiRegenerate.ts`, line 155, change:

```typescript
// Before
const mode = incremental ? "structure" : "full";
// After
const mode = "full";
```

- [ ] **Step 2: Fix `client.ts` default mode parameter**

In `dashboard/src/api/client.ts`, line 128, change the default for `wikiGenerate`:

```typescript
// Before
export async function wikiGenerate(
  repository: string,
  scope: string,
  mode = "structure",
  language = "en",
): Promise<TaskInfo> {
// After
export async function wikiGenerate(
  repository: string,
  scope: string,
  mode = "full",
  language = "en",
): Promise<TaskInfo> {
```

And line 145, change the default for `businessWikiGenerate`:

```typescript
// Before
  mode: "structure" | "full" = "structure",
// After
  mode: "structure" | "full" = "full",
```

- [ ] **Step 3: Verify frontend builds**

Run:
```bash
cd dashboard && pnpm tsc --noEmit
```
Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/hooks/useWikiRegenerate.ts dashboard/src/api/client.ts
git commit -m "fix(wiki): default mode to 'full' instead of 'structure' for LLM generation"
```

---

### Task 2: Enhance `_entity_digest` with Graph Properties

**Files:**
- Modify: `wiki/composer.py:572-650` (`_entity_digest` method)

- [ ] **Step 1: Add class-level property injection**

In `wiki/composer.py`, method `_entity_digest`, after the `business_summary` block (line 594-595), add:

```python
        for prop_name, label in [
            ("annotations", "Annotations"),
            ("semantic_roles", "Semantic roles"),
            ("base_classes", "Base classes"),
            ("interfaces", "Implements"),
        ]:
            val = n.properties.get(prop_name)
            if val:
                display = ", ".join(val) if isinstance(val, list) else str(val)
                lines.append(f"- {label}: {display}")
```

- [ ] **Step 2: Add method-level parameters and return_type**

In `wiki/composer.py`, inside the method loop (after line 624 `detail += f" | doc: ..."`), add:

```python
                m_params = m.properties.get("parameters", "")
                m_ret = m.properties.get("return_type", "")
                if m_params:
                    detail += f" | params: {str(m_params)[:100]}"
                if m_ret:
                    detail += f" | returns: {str(m_ret)[:60]}"
```

- [ ] **Step 3: Add child-level annotations for MODULE_OVERVIEW**

In the `if page_type == PageType.MODULE_OVERVIEW:` block (line 599-610), extend child detail:

```python
                ch_annotations = ch.properties.get("annotations", "")
                if ch_annotations:
                    ann_str = ", ".join(ch_annotations) if isinstance(ch_annotations, list) else str(ch_annotations)
                    detail += f" | annotations: {ann_str[:80]}"
```

- [ ] **Step 4: Verify no import errors**

Run:
```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -c "from wiki.composer import WikiComposer; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add wiki/composer.py
git commit -m "feat(wiki): inject annotations/semantic_roles/base_classes/interfaces/params into entity digest"
```

---

### Task 3: Add Structured Output Template to Tier-2 Prompt

**Files:**
- Modify: `wiki/composer.py:551-564` (`_tier2_llm` prompt construction)

- [ ] **Step 1: Define section templates as module constants**

In `wiki/composer.py`, after the `_PARENT_SYSTEM_PROMPT` constant (line 40), add:

```python
_STRUCTURED_SECTIONS_MODULE = (
    "\n\nStructure your documentation with these sections (adapt as appropriate):\n"
    "1. **Purpose & Responsibility** — What this module does and why it exists\n"
    "2. **Key Components** — Main classes/functions and their roles\n"
    "3. **Integration Points** — How this connects to other parts of the system\n"
    "4. **Data Flow** — Input/output, transformations, side effects\n"
    "5. **Design Decisions** — Notable trade-offs, patterns, constraints\n"
)

_STRUCTURED_SECTIONS_CLASS = (
    "\n\nStructure your documentation with these sections (adapt as appropriate):\n"
    "1. **Purpose & Responsibility** — What this class does and why it exists\n"
    "2. **Methods & Properties** — Key methods, their parameters, and behavior\n"
    "3. **Integration Points** — How this connects to other classes/modules\n"
    "4. **Data Flow** — Input/output, state management, side effects\n"
    "5. **Design Decisions** — Notable trade-offs, patterns, constraints\n"
)

_STRUCTURED_SECTIONS_FUNCTION = (
    "\n\nStructure your documentation with these sections (adapt as appropriate):\n"
    "1. **Purpose** — What this function does\n"
    "2. **Parameters & Return** — Input parameters and return value semantics\n"
    "3. **Usage Context** — Where and how this function is called\n"
    "4. **Design Notes** — Edge cases, constraints, performance considerations\n"
)
```

- [ ] **Step 2: Inject section template into `_tier2_llm` prompt**

In `wiki/composer.py`, method `_tier2_llm`, replace the prompt construction block (lines 551-564):

```python
        section_template = ""
        if page_type == PageType.MODULE_OVERVIEW:
            section_template = _STRUCTURED_SECTIONS_MODULE
        elif page_type == PageType.CLASS_DETAIL:
            section_template = _STRUCTURED_SECTIONS_CLASS
        else:
            section_template = _STRUCTURED_SECTIONS_FUNCTION

        prompt = (
            f"{ctx_block}\n\n"
            "## Task\n"
            f"{lang_directive}\n\n"
            f"Write a detailed documentation page for this {page_type.value.replace('_', ' ')}.\n"
            f"{section_template}\n"
            f"{entity}\n"
            f"{doc_section}"
            f"{memory_section}"
        )
```

- [ ] **Step 3: Verify import works**

Run:
```bash
python -c "from wiki.composer import WikiComposer; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add wiki/composer.py
git commit -m "feat(wiki): add structured output section templates to tier-2 LLM prompt"
```

---

### Task 4: Incremental Path — Inject glossary + parent_context

**Files:**
- Modify: `wiki/service.py:572-656` (`generate_incremental` method)

- [ ] **Step 1: Add glossary build and parent context lookup**

In `wiki/service.py`, method `generate_incremental`, before the main UID loop, add glossary build. Then inside the loop, add parent context lookup.

Before the `for uid in all_affected_uids:` loop, add:

```python
        glossary: dict[str, str] = {}
        if composer._wiki_store is not None:
            try:
                glossary = await self._ctx.build_glossary(
                    repository,
                    [n.properties.get("name", "") for n in graph_nodes_cache.values()],
                )
            except Exception:
                log.warning("incremental_glossary_build_failed", repository=repository, exc_info=True)
```

Inside the loop, before `compose_page`, add:

```python
                parent_context = ""
                parent_edges = [
                    e for e in page_data.edges
                    if e.edge_type == EdgeType.CONTAINS and e.target_uid == uid
                ]
                if parent_edges and self._wiki_store is not None:
                    try:
                        parent_uid = parent_edges[0].source_uid
                        parent_page = await self._wiki_store.get_page_by_entity_uid(
                            repository, parent_uid,
                        )
                        if parent_page and hasattr(parent_page, "content"):
                            parent_context = str(parent_page.content)[:1200]
                    except Exception:
                        log.debug("incremental_parent_context_miss", uid=uid)
```

Then pass these to `compose_page`:

```python
                    page = await composer.compose_page(
                        page_data,
                        page_type,
                        effective_config,
                        importance_tier=tier,
                        skeleton_strategy=skeleton_strat,
                        skeleton_light_model=skeleton_light_model,
                        parent_context=parent_context,
                        glossary=glossary,
                    )
```

- [ ] **Step 2: Verify `compose_page` accepts these params and EdgeType is imported**

Run:
```bash
python -c "
import inspect
from wiki.composer import WikiComposer
sig = inspect.signature(WikiComposer.compose_page)
print('parent_context' in sig.parameters, 'glossary' in sig.parameters)
"
```
Expected: Both should be `True`. If `EdgeType` is not imported in `wiki/service.py`, add `from store.schema import EdgeType`.

- [ ] **Step 3: Commit**

```bash
git add wiki/service.py
git commit -m "feat(wiki): inject glossary and parent_context into incremental generation path"
```

---

### Task 5: Progressive Page Persistence

**Files:**
- Modify: `config.py:173+` (add config flags)
- Modify: `wiki/service.py:1493-1650` (`_compose_all_pages`)

- [ ] **Step 1: Add config flags**

In `config.py`, class `WikiConfig`, add after `chunk_embedding_max_length` (around line 231):

```python
    progressive_persist_enabled: bool = True
    progressive_persist_batch_size: int = 20
    resume_from_saved: bool = False
```

- [ ] **Step 2: Modify `_compose_all_pages` for batched leaf composition**

In `wiki/service.py`, method `_compose_all_pages`, replace the leaf phase (lines 1633-1642):

```python
        # Before: single gather for all leaves
        # leaf_results = await asyncio.gather(*(compose_leaf(n) for n in leaves))

        # After: batched compose + progressive persist
        batch_size = int(getattr(self._wiki_cfg, "progressive_persist_batch_size", 20))
        progressive = getattr(self._wiki_cfg, "progressive_persist_enabled", True)
        skip_claim = config.mode == "structure"

        for batch_start in range(0, len(leaves), batch_size):
            batch = leaves[batch_start : batch_start + batch_size]
            leaf_results = await asyncio.gather(*(compose_leaf(n) for n in batch))

            batch_pages: list[WikiPage] = []
            for page in leaf_results:
                if page is not None:
                    pages.append(page)
                    batch_pages.append(page)
                    uid = getattr(page, "_source_entity_uid", "")
                    struct_path = getattr(page, "_structure_path", page.path)
                    _sum = _extract_summary(page, entity_uid=uid)
                    summary_index[struct_path] = _sum
                    if page.path != struct_path:
                        summary_index[page.path] = _sum

            if progressive and batch_pages and self._store is not None:
                try:
                    await self._persist_pages_to_graph(
                        repository, batch_pages,
                        language=language, skip_claim_tracking=skip_claim,
                    )
                    log.info(
                        "progressive_persist_leaf_batch",
                        repository=repository,
                        batch_start=batch_start,
                        batch_saved=len(batch_pages),
                    )
                except Exception:
                    log.warning(
                        "progressive_persist_leaf_failed",
                        repository=repository,
                        batch_start=batch_start,
                        exc_info=True,
                    )
```

- [ ] **Step 3: Progressive persist for parent depth levels**

After each parent depth level compose, persist immediately. Modify the parent loop section to persist after each depth level:

```python
        for depth_level, parent_nodes in parents_by_depth:
            parent_results = await asyncio.gather(*(compose_parent(n) for n in parent_nodes))
            depth_pages: list[WikiPage] = []
            for page in parent_results:
                if page is not None:
                    pages.append(page)
                    depth_pages.append(page)
                    # ... existing summary_index update ...

            if progressive and depth_pages and self._store is not None:
                try:
                    await self._persist_pages_to_graph(
                        repository, depth_pages,
                        language=language, skip_claim_tracking=skip_claim,
                    )
                    log.info(
                        "progressive_persist_parent_batch",
                        repository=repository,
                        depth=depth_level,
                        saved=len(depth_pages),
                    )
                except Exception:
                    log.warning(
                        "progressive_persist_parent_failed",
                        repository=repository,
                        depth=depth_level,
                        exc_info=True,
                    )
```

- [ ] **Step 4: Keep final persist as idempotent safety net**

In `wiki/service.py`, method `generate()` (line 457-469), the final `_persist_pages_to_graph` call should **always run** regardless of progressive mode. FalkorDB uses MERGE (upsert), so double-persisting already-saved pages is a no-op. This ensures no pages are missed if a progressive batch failed silently.

No code change needed here — keep the existing final persist logic as-is. Progressive persist is an **additive** safety net, not a replacement.

> **Note**: `resume_from_saved` is deferred to a follow-up task. The progressive persist alone already solves the core crash-resilience problem: if the process crashes at page 500/1000, ~480 pages are already saved. The next run will re-generate all pages but won't lose prior work. If incremental mode is used next, only changed entities regenerate.

- [ ] **Step 5: Verify imports and syntax**

Run:
```bash
python -c "from wiki.service import WikiService; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add config.py wiki/service.py
git commit -m "feat(wiki): progressive page persistence during composition for crash resilience"
```

---

### Task 6: TD-1 WikiConfig Naming Cleanup

**Files:**
- Modify: `config.py:173` (rename class)
- Modify: all files importing `config.WikiConfig`

- [ ] **Step 1: Find all references to `config.WikiConfig`**

Run:
```bash
rg "config\.WikiConfig|from config import.*WikiConfig" --type py -l
```

- [ ] **Step 2: Rename `WikiConfig` in `config.py` to `AppWikiFlags`**

In `config.py`, line 173:

```python
# Before
class WikiConfig(BaseModel):
    """Application-level wiki feature flags (separate from ``wiki.models.WikiConfig``)."""
# After
class AppWikiFlags(BaseModel):
    """Application-level wiki feature flags (NOT ``wiki.models.WikiConfig`` which is per-run config)."""
```

- [ ] **Step 3: Update all imports**

For each file found in Step 1, update the import and type references.

- [ ] **Step 4: Verify no import errors**

Run:
```bash
python -c "from config import AppWikiFlags; print('OK')"
python -c "from wiki.service import WikiService; print('OK')"
```
Expected: Both `OK`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename config.WikiConfig to AppWikiFlags to resolve naming conflict with wiki.models.WikiConfig"
```

---

### Task 6.5: Module 1 Unit Tests

**Files:**
- Create: `tests/test_entity_digest_enhancement.py`

- [ ] **Step 1: Write tests for enhanced `_entity_digest`**

Create `tests/test_entity_digest_enhancement.py`:

```python
"""Tests for _entity_digest enhancements (annotations, structured output, etc.)."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from store.schema import GraphNode, GraphEdge, NodeLabel, EdgeType
from wiki.composer import WikiComposer, _STRUCTURED_SECTIONS_MODULE, _STRUCTURED_SECTIONS_CLASS
from wiki.models import PageType, PageData


def _make_class_node(**overrides):
    props = {
        "name": "AuthService",
        "path": "src/auth.py",
        "fqn": "src.auth.AuthService",
        "signature": "class AuthService",
        "docstring": "Handles authentication",
        "annotations": ["@Service", "@Transactional"],
        "semantic_roles": ["service", "authentication"],
        "base_classes": ["BaseService"],
        "interfaces": ["Authenticator"],
    }
    props.update(overrides)
    return GraphNode(uid="Class:src/auth.py:AuthService:1", label=NodeLabel.CLASS, properties=props)


def test_entity_digest_includes_annotations():
    composer = WikiComposer.__new__(WikiComposer)
    node = _make_class_node()
    page_data = PageData(node=node, edges=[], children=[], methods=[])
    digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
    assert "Annotations: @Service, @Transactional" in digest


def test_entity_digest_includes_semantic_roles():
    composer = WikiComposer.__new__(WikiComposer)
    node = _make_class_node()
    page_data = PageData(node=node, edges=[], children=[], methods=[])
    digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
    assert "Semantic roles:" in digest


def test_entity_digest_includes_base_classes():
    composer = WikiComposer.__new__(WikiComposer)
    node = _make_class_node()
    page_data = PageData(node=node, edges=[], children=[], methods=[])
    digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
    assert "Base classes: BaseService" in digest


def test_structured_sections_constants_exist():
    assert "Purpose & Responsibility" in _STRUCTURED_SECTIONS_MODULE
    assert "Methods & Properties" in _STRUCTURED_SECTIONS_CLASS
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_entity_digest_enhancement.py -v
```
Expected: All PASS (after Tasks 2-3 are complete)

- [ ] **Step 3: Commit**

```bash
git add tests/test_entity_digest_enhancement.py
git commit -m "test(wiki): add unit tests for _entity_digest enhancements and structured output templates"
```

---

## Module 2: Comment Extraction Enhancement

### Task 7: Extract Module Docstring (Python)

**Files:**
- Modify: `indexer/tree_sitter_parser.py`
- Create: `tests/test_module_docstring.py`

- [ ] **Step 1: Write test for Python module docstring extraction**

Create `tests/test_module_docstring.py`:

```python
"""Tests for module-level docstring extraction."""
import pytest
from indexer.tree_sitter_parser import TreeSitterParser

PYTHON_MODULE_WITH_DOCSTRING = '''
"""This module handles user authentication and authorization."""

import os
from typing import Optional

class AuthService:
    pass
'''

PYTHON_MODULE_NO_DOCSTRING = '''
import os

class Foo:
    pass
'''


def test_python_module_docstring_extracted():
    parser = TreeSitterParser()
    result = parser.parse_file("test.py", PYTHON_MODULE_WITH_DOCSTRING.encode(), "python")
    assert result.module_docstring == "This module handles user authentication and authorization."


def test_python_module_no_docstring():
    parser = TreeSitterParser()
    result = parser.parse_file("test.py", PYTHON_MODULE_NO_DOCSTRING.encode(), "python")
    assert result.module_docstring == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_module_docstring.py -v
```
Expected: FAIL (attribute `module_docstring` not found on `ParseResult`).

- [ ] **Step 3: Add `module_docstring` to `ParseResult`**

In `indexer/tree_sitter_parser.py`, locate the `ParseResult` dataclass and add:

```python
@dataclass
class ParseResult:
    # ... existing fields ...
    module_docstring: str = ""
```

- [ ] **Step 4: Implement `_extract_module_docstring`**

In `indexer/tree_sitter_parser.py`, add as a static method of `TreeSitterParser`:

```python
    @staticmethod
    def _extract_module_docstring(root_node: "Node", language: str) -> str:
        """Extract file-level docstring from the module root."""
        if language == "python":
            for child in root_node.children:
                if child.type == "expression_statement":
                    expr = child.children[0] if child.children else None
                    if expr and expr.type in ("string", "concatenated_string"):
                        raw = expr.text.decode("utf-8") if expr.text else ""
                        return raw.strip("'\"").strip()
                    break
                if child.type not in ("comment", "import_statement", "import_from_statement"):
                    break
        return ""
```

- [ ] **Step 5: Wire into `parse_file`**

In `parse_file`, after parsing, set:

```python
        result.module_docstring = self._extract_module_docstring(tree.root_node, language)
```

- [ ] **Step 6: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_module_docstring.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add indexer/tree_sitter_parser.py tests/test_module_docstring.py
git commit -m "feat(parser): extract Python module-level docstring"
```

---

### Task 8: Extract File Header Comment (Java/JS/TS)

**Files:**
- Modify: `indexer/tree_sitter_parser.py`
- Modify: `tests/test_module_docstring.py`

- [ ] **Step 1: Write test for Java file header comment**

Append to `tests/test_module_docstring.py`:

```python
JAVA_FILE_WITH_CLASS_DOC = '''
package com.example;

import java.util.List;

/**
 * Service responsible for user authentication.
 * Handles login, logout, and session management.
 */
@Service
public class AuthService {
    // ...
}
'''

JAVA_FILE_WITH_LICENSE_ONLY = '''
/*
 * Copyright 2026 Company Inc.
 * Licensed under the Apache License, Version 2.0
 */
package com.example;

public class Foo {}
'''


def test_java_file_header_comment_above_class():
    parser = TreeSitterParser()
    result = parser.parse_file("AuthService.java", JAVA_FILE_WITH_CLASS_DOC.encode(), "java")
    assert "user authentication" in result.module_docstring.lower()


def test_java_license_header_filtered():
    parser = TreeSitterParser()
    result = parser.parse_file("Foo.java", JAVA_FILE_WITH_LICENSE_ONLY.encode(), "java")
    assert result.module_docstring == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_module_docstring.py::test_java_file_header_comment_above_class -v
```
Expected: FAIL

- [ ] **Step 3: Implement `_extract_file_header_comment`**

In `indexer/tree_sitter_parser.py`:

```python
    @staticmethod
    def _extract_file_header_comment(root_node: "Node", language: str) -> str:
        """Extract documentation comment above the first class declaration (not above imports)."""
        if language not in ("java", "javascript", "typescript", "go"):
            return ""

        first_class = None
        for child in root_node.children:
            if child.type in (
                "class_declaration", "interface_declaration",
                "enum_declaration", "annotation_type_declaration",
                "class",
            ):
                first_class = child
                break
            if child.type == "export_statement":
                for sub in child.children:
                    if sub.type in ("class_declaration", "interface_declaration", "class"):
                        first_class = child
                        break
                if first_class:
                    break

        if first_class is None:
            return ""

        prev = first_class.prev_named_sibling
        while prev and prev.type in (
            "decorator", "annotation", "marker_annotation", "modifiers",
        ):
            prev = prev.prev_named_sibling

        if prev and prev.type in ("comment", "block_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            cleaned = raw.strip("/* \n\t")
            if _is_license_comment(cleaned):
                return ""
            return cleaned

        return ""
```

- [ ] **Step 4: Add `_is_license_comment` helper**

```python
_LICENSE_KEYWORDS = frozenset({
    "copyright", "licensed", "license", "apache", "mit license",
    "gpl", "bsd", "mozilla", "all rights reserved",
})

def _is_license_comment(text: str) -> bool:
    lower = text.lower()[:500]
    return sum(1 for kw in _LICENSE_KEYWORDS if kw in lower) >= 2
```

- [ ] **Step 5: Wire into `_extract_module_docstring` fallback**

Update `_extract_module_docstring` to call `_extract_file_header_comment` for non-Python:

```python
    @staticmethod
    def _extract_module_docstring(root_node: "Node", language: str) -> str:
        if language == "python":
            # ... existing Python logic ...
        else:
            return TreeSitterParser._extract_file_header_comment(root_node, language)
        return ""
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest tests/test_module_docstring.py -v
```
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add indexer/tree_sitter_parser.py tests/test_module_docstring.py
git commit -m "feat(parser): extract file header comment above class for Java/JS/TS/Go with license filtering"
```

---

### Task 9: Enhanced Javadoc Backward Traversal

**Files:**
- Modify: `indexer/tree_sitter_parser.py:376-403` (`_extract_docstring`)
- Modify: `tests/test_module_docstring.py`

- [ ] **Step 1: Write test for Javadoc past annotations**

Append to `tests/test_module_docstring.py`:

```python
JAVA_ANNOTATED_METHOD = '''
public class Foo {
    /**
     * Authenticates user with provided credentials.
     */
    @Override
    @Transactional
    public boolean authenticate(String user, String pass) {
        return true;
    }
}
'''


def test_javadoc_past_annotations():
    parser = TreeSitterParser()
    result = parser.parse_file("Foo.java", JAVA_ANNOTATED_METHOD.encode(), "java")
    methods = [f for f in result.functions if f.name == "authenticate"]
    assert len(methods) == 1
    assert "authenticates user" in methods[0].docstring.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_module_docstring.py::test_javadoc_past_annotations -v
```
Expected: FAIL (current code only checks immediate prev_named_sibling)

- [ ] **Step 3: Fix `_extract_docstring` for backward traversal**

In `indexer/tree_sitter_parser.py`, method `_extract_docstring`, replace the Java/JS/TS/Go branch (lines 397-401):

```python
        elif language in ("java", "javascript", "typescript", "go"):
            prev = node.prev_named_sibling
            while prev and prev.type in (
                "decorator", "annotation", "marker_annotation",
                "modifiers", "module_attribute",
            ):
                prev = prev.prev_named_sibling
            if prev and prev.type in ("comment", "block_comment"):
                raw = prev.text.decode("utf-8") if prev.text else ""
                return raw.strip("/* \n\t")
```

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/test_module_docstring.py::test_javadoc_past_annotations -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/tree_sitter_parser.py tests/test_module_docstring.py
git commit -m "fix(parser): walk backwards past annotations to find Javadoc comments"
```

---

### Task 10: Comment Filter Pipeline

**Files:**
- Create: `indexer/comment_filter.py`
- Create: `tests/test_comment_filter.py`

- [ ] **Step 1: Write test file**

Create `tests/test_comment_filter.py`:

```python
"""Tests for comment classification and filtering."""
import pytest
from indexer.comment_filter import CommentFilter, CommentTier


@pytest.fixture
def cf():
    return CommentFilter()


def test_license_detected(cf):
    text = "Copyright 2026 Company Inc. Licensed under the Apache License, Version 2.0"
    assert cf.classify(text) == CommentTier.NEVER


def test_trivial_comment(cf):
    assert cf.classify("increment i") == CommentTier.NEVER
    assert cf.classify("return result") == CommentTier.NEVER


def test_commented_out_code(cf):
    code = "if (user != null) { return user.getName(); }"
    assert cf.classify(code) == CommentTier.NEVER


def test_meaningful_block_comment(cf):
    text = "This service handles cross-border transaction settlement flows using the SWIFT network"
    tier = cf.classify(text)
    assert tier in (CommentTier.BLOCK_COMMENT, CommentTier.FILE_HEADER)


def test_short_comment_is_never(cf):
    assert cf.classify("ok") == CommentTier.NEVER
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_comment_filter.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `indexer/comment_filter.py`**

Create `indexer/comment_filter.py`:

```python
"""Classify and filter code comments by signal quality."""
from __future__ import annotations

import re
from enum import Enum


class CommentTier(Enum):
    STRUCTURED_DOC = 1
    FILE_HEADER = 2
    BLOCK_COMMENT = 3
    INLINE = 4
    NEVER = 99


_LICENSE_KEYWORDS = frozenset({
    "copyright", "licensed", "license", "apache", "mit license",
    "gpl", "bsd", "mozilla", "all rights reserved",
})

_CODE_KEYWORDS = frozenset({
    "if", "else", "for", "while", "return", "class", "import",
    "def", "function", "var", "let", "const", "new", "try",
    "catch", "throw", "public", "private", "static", "void",
})

_TRIVIAL_PATTERNS = re.compile(
    r"^(increment|decrement|return|set|get|init|todo|fixme|hack|xxx|note)\b",
    re.IGNORECASE,
)


class CommentFilter:
    def classify(self, text: str) -> CommentTier:
        stripped = text.strip()
        if not stripped or len(stripped) < 15:
            return CommentTier.NEVER
        if self._is_license(stripped):
            return CommentTier.NEVER
        if self._is_commented_code(stripped):
            return CommentTier.NEVER
        if self._is_trivial(stripped):
            return CommentTier.NEVER
        if len(stripped) >= 40:
            return CommentTier.BLOCK_COMMENT
        return CommentTier.INLINE

    def _is_license(self, text: str) -> bool:
        lower = text.lower()[:500]
        return sum(1 for kw in _LICENSE_KEYWORDS if kw in lower) >= 2

    def _is_commented_code(self, text: str) -> bool:
        tokens = text.split()
        if not tokens:
            return False
        code_count = sum(1 for t in tokens if t.rstrip("(;){},") in _CODE_KEYWORDS)
        ratio = code_count / len(tokens)
        has_syntax = any(c in text for c in [";", "{", "}", "=>", "->", "==", "!="])
        return ratio > 0.3 or (ratio > 0.15 and has_syntax)

    def _is_trivial(self, text: str) -> bool:
        return bool(_TRIVIAL_PATTERNS.match(text.strip()))
```

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/test_comment_filter.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/comment_filter.py tests/test_comment_filter.py
git commit -m "feat(indexer): add comment filter pipeline for license/trivial/code detection"
```

---

### Task 11: Graph Builder — Store Module Docstring

**Files:**
- Modify: `indexer/code_graph_builder.py`

- [ ] **Step 1: Add module docstring to Module node properties**

In `indexer/code_graph_builder.py`, locate the Module node construction in `_build_graph` (search for `module_props` or `NodeLabel.MODULE`).

After the existing Module properties are set, add:

```python
        module_doc = self._parser._extract_module_docstring(tree.root_node, language)
        if module_doc:
            module_props["docstring"] = module_doc[:1000]
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "from indexer.code_graph_builder import CodeGraphBuilder; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add indexer/code_graph_builder.py
git commit -m "feat(indexer): store module docstring/file header in graph Module nodes"
```

---

### Task 12: Composer — Inject Module Docstring + Config for Comment Tiers

**Files:**
- Modify: `wiki/composer.py` (`_entity_digest`)
- Modify: `wiki/models.py` (`WikiConfig`)

- [ ] **Step 1: Add comment injection config to `wiki/models.py`**

In `wiki/models.py`, class `WikiConfig` (the per-run config), add fields:

```python
@dataclass
class WikiConfig:
    repository: str
    mode: str = "structure"
    format: str = "json"
    language: str = "en"
    comment_injection_tier: int = 2   # inject all tiers from 1 through N (1=docstring, 2=+file headers, 3=+block, 4=+inline)
    comment_max_chars: int = 500      # per-entity comment character budget
```

- [ ] **Step 2: Add Module docstring injection in `_entity_digest`**

In `wiki/composer.py`, method `_entity_digest`, inside the `if page_type == PageType.MODULE_OVERVIEW:` block, before the children loop, add:

```python
            module_doc = n.properties.get("docstring")
            if isinstance(module_doc, str) and module_doc:
                lines.append(f"- Module documentation: {module_doc[:500]}")
```

- [ ] **Step 3: Verify**

```bash
python -c "from wiki.composer import WikiComposer; print('OK')"
python -c "from wiki.models import WikiConfig; c = WikiConfig('test'); print(c.comment_injection_tier)"
```
Expected: `OK` and `2`

- [ ] **Step 4: Commit**

```bash
git add wiki/composer.py wiki/models.py
git commit -m "feat(wiki): inject module docstring into entity digest + add comment tier config"
```

---

## Module 3: Architecture Overview

### Task 13: LLM-Driven Repository Overview Page

**Files:**
- Modify: `wiki/composer.py` (`compose_incremental_navigation_pages`)
- Modify: `wiki/context.py` (`build_repository_context`)

- [ ] **Step 1: Update `compose_incremental_navigation_pages` to pass real module list**

First check `wiki/context.py` `build_repository_context` signature to verify it accepts a list of strings.

In `wiki/composer.py`, method `compose_incremental_navigation_pages`, replace the `build_repository_context([])` call:

```python
        module_summaries = []
        if self._wiki_store is not None:
            try:
                top_modules = await self._wiki_store.find_top_level_modules(repository)
                for m in (top_modules or [])[:30]:
                    name = m.properties.get("name", "")
                    bs = m.properties.get("business_summary", "")
                    doc = m.properties.get("docstring", "")
                    module_summaries.append(name + (f": {bs}" if bs else f": {doc[:200]}" if doc else ""))
            except Exception:
                log.debug("overview_module_fetch_failed", repository=repository)

        repo_ctx = await self._ctx.build_repository_context(module_summaries)
```

- [ ] **Step 3: Add `_REPO_OVERVIEW_SYSTEM` prompt**

In `wiki/composer.py`, add after `_PARENT_SYSTEM_PROMPT`:

```python
_REPO_OVERVIEW_SYSTEM = (
    "You are a senior architect writing a repository overview for developer onboarding. "
    "Describe the overall architecture, key design patterns, major module responsibilities, "
    "how they collaborate, and the system's primary data flows. "
    "Include a Mermaid architecture diagram showing module relationships. "
    "Use clear section headings (##). Output Markdown."
)
```

- [ ] **Step 4: Enhance overview page with LLM when available**

If LLM is available and module summaries exist, use LLM instead of the template overview:

```python
        if self._llm and module_summaries:
            overview_prompt = (
                f"# Repository: {repository}\n\n"
                f"## Modules ({len(module_summaries)} top-level):\n"
                + "\n".join(f"- {s}" for s in module_summaries)
                + "\n\nWrite a comprehensive repository overview."
            )
            try:
                overview_text = await self._llm.generate(
                    overview_prompt, system=_REPO_OVERVIEW_SYSTEM,
                )
            except Exception:
                log.warning("llm_overview_failed", repository=repository, exc_info=True)
                overview_text = repo_ctx.strip()
        else:
            overview_text = repo_ctx.strip()
```

- [ ] **Step 5: Verify**

```bash
python -c "from wiki.composer import WikiComposer; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add wiki/composer.py wiki/context.py
git commit -m "feat(wiki): LLM-driven repository overview page with real module context"
```

---

### Task 14: TD-2 — Remove Navigation from Page Content

**Files:**
- Modify: `wiki/composer.py` (search for `render_navigation_section`)

- [ ] **Step 1: Find and remove `render_navigation_section` from page content**

Run `rg "render_navigation_section" --type py` to locate all call sites.

In `wiki/composer.py`, method `_markdown_body`, find where `render_navigation_section` output is appended to `content` (typically as a section in the body list). Remove the call and its insertion:

```python
# Find the line that looks like:
#     nav = render_navigation_section(...)
#     if nav:
#         sections.append(nav)
# Replace with nothing — navigation data stays in navigation_json only.
```

If `render_navigation_section` is used in other methods, check if those also need cleanup. The function definition itself can remain (it may be used by the frontend API).

- [ ] **Step 2: Verify frontend reads from `navigation_json`**

Run `rg "navigation_json" dashboard/src/ --type-add "tsx:*.tsx" --type tsx --type ts` to confirm the dashboard `WikiTreeNav` component reads from `navigation_json` and not from parsing `content`.

- [ ] **Step 3: Verify page content is smaller**

Run a quick integration check: generate a page and verify the content field no longer contains navigation links.

- [ ] **Step 4: Commit**

```bash
git add wiki/composer.py
git commit -m "refactor(wiki): remove navigation section from page content (TD-2), data stays in navigation_json"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: All sections (3.1-3.6, 4.1-4.4, 5.1-5.2) mapped to tasks
- [x] **No placeholders**: Every step has concrete code or commands; READ-only steps merged or removed
- [x] **Type consistency**: Method signatures and property names consistent across tasks
- [x] **TD items**: TD-1 (Task 6), TD-2 (Task 14), TD-3/TD-4 (addressed in Task 4)
- [x] **Progressive persist**: Config flags + batched compose + final persist always runs (idempotent safety net)
- [x] **Comment filtering**: License, trivial, commented-out code all handled
- [x] **File header comments**: Above class (not import), with license filtering
- [x] **Comment config**: `comment_injection_tier` and `comment_max_chars` added in Task 12
- [x] **Module 1 tests**: Task 6.5 adds unit tests for _entity_digest and structured output
- [x] **Resume deferred**: `resume_from_saved` noted as follow-up; progressive persist is the primary deliverable
