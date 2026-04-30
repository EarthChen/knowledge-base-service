# LLM Semantic Diagram Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent LLM-powered semantic diagram generation step that produces Mermaid sequence diagrams for MODULE_OVERVIEW and CLASS_DETAIL wiki pages, closing the G-D3 gap with DeepWiki.

**Architecture:** New `SemanticDiagramGenerator` class in `wiki/semantic_diagram_gen.py` receives the existing `entity_digest` string and LLM port, generates Mermaid sequence diagrams via a single LLM call, validates output, and returns `WikiDiagram` objects. Integration into `compose_page` is minimal — semantic diagrams are appended to the deterministic diagram list in the main path only (mode=full + LLM available + complexity threshold met).

**Tech Stack:** Python 3.11+, pytest, existing `LLMPort` abstraction, existing `WikiDiagram`/`DiagramType` models.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `wiki/models.py` | Modify | Add `SEQUENCE_DIAGRAM` to `DiagramType` enum |
| `wiki/semantic_diagram_gen.py` | Create | `SemanticDiagramGenerator` class — prompt building, LLM call, Mermaid validation |
| `wiki/composer.py` | Modify | Call `SemanticDiagramGenerator.generate()` in `compose_page` main path |
| `tests/wiki/test_semantic_diagram_gen.py` | Create | Unit tests for SemanticDiagramGenerator |
| `tests/wiki/test_composer_semantic_diagrams.py` | Create | Integration tests for composer + semantic diagrams |

---

### Task 1: DiagramType Model Extension

**Files:**
- Modify: `wiki/models.py:30-33`
- Test: `tests/wiki/test_phase1_models.py` (existing, verify no regression)

- [ ] **Step 1: Write the failing test**

Create `tests/wiki/test_semantic_diagram_gen.py` with a minimal test that imports the new enum value:

```python
"""Tests for LLM semantic diagram generation."""
from __future__ import annotations

from wiki.models import DiagramType


def test_sequence_diagram_type_exists():
    assert DiagramType.SEQUENCE_DIAGRAM == "sequenceDiagram"
    assert DiagramType("sequenceDiagram") == DiagramType.SEQUENCE_DIAGRAM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_semantic_diagram_gen.py::test_sequence_diagram_type_exists -v`
Expected: FAIL with `AttributeError: SEQUENCE_DIAGRAM is not a member of DiagramType`

- [ ] **Step 3: Write minimal implementation**

In `wiki/models.py`, add `SEQUENCE_DIAGRAM` to the `DiagramType` enum (after line 33):

```python
class DiagramType(StrEnum):
    CLASS_DIAGRAM = "classDiagram"
    FLOWCHART = "flowchart"
    DEPENDENCY_GRAPH = "dependencyGraph"
    SEQUENCE_DIAGRAM = "sequenceDiagram"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_semantic_diagram_gen.py::test_sequence_diagram_type_exists -v`
Expected: PASS

- [ ] **Step 5: Run existing model tests for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_phase1_models.py tests/wiki/test_phase2_models.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/models.py tests/wiki/test_semantic_diagram_gen.py
git commit -m "feat(wiki): add SEQUENCE_DIAGRAM to DiagramType enum"
```

---

### Task 2: SemanticDiagramGenerator Core Implementation

**Files:**
- Create: `wiki/semantic_diagram_gen.py`
- Create/Modify: `tests/wiki/test_semantic_diagram_gen.py`

**Context:** This is the core module. It receives `entity_digest` (a multi-line string describing a code entity), `page_type`, and `page_data`, determines whether a semantic diagram should be generated, builds a prompt, calls the LLM, validates the Mermaid output, and returns a list of `WikiDiagram`. The LLM port is the same `LLMPort` interface used in `composer.py` (`_tier2_llm`). `SemanticDiagramGenerator.__init__` takes `llm: LLMPort | None`.

**Key design decisions:**
- Only generate `sequenceDiagram` (no stateDiagram — unreliable from entity_digest alone)
- Trigger for MODULE_OVERVIEW: CALLS edges >= 3
- Trigger for CLASS_DETAIL: methods >= 5 AND CALLS edges >= 2
- Only when mode="full" and LLM available
- Returns empty list on any failure (never raises)

- [ ] **Step 1: Write failing tests for validation logic**

Add to `tests/wiki/test_semantic_diagram_gen.py`:

```python
import pytest
from wiki.semantic_diagram_gen import SemanticDiagramGenerator


class TestValidateAndClean:
    def test_valid_sequence_diagram(self):
        raw = "sequenceDiagram\n    A->>B: call\n    B-->>A: response"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None
        assert result.startswith("sequenceDiagram")

    def test_strips_markdown_fences(self):
        raw = "```mermaid\nsequenceDiagram\n    A->>B: call\n```"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None
        assert not result.startswith("```")
        assert result.startswith("sequenceDiagram")

    def test_invalid_mermaid_returns_none(self):
        raw = "This is just text, not a diagram"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is None

    def test_empty_input_returns_none(self):
        result = SemanticDiagramGenerator._validate_and_clean("")
        assert result is None

    def test_strips_triple_backtick_without_mermaid_tag(self):
        raw = "```\nsequenceDiagram\n    A->>B: call\n```"
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is not None
        assert result.startswith("sequenceDiagram")

    def test_max_lines_exceeded_returns_none(self):
        lines = ["sequenceDiagram"] + [f"    A->>B: step{i}" for i in range(200)]
        raw = "\n".join(lines)
        result = SemanticDiagramGenerator._validate_and_clean(raw)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_semantic_diagram_gen.py::TestValidateAndClean -v`
Expected: FAIL with `ImportError: cannot import name 'SemanticDiagramGenerator'`

- [ ] **Step 3: Write failing tests for trigger conditions**

Add to `tests/wiki/test_semantic_diagram_gen.py`:

```python
from unittest.mock import MagicMock
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.models import PageType, WikiConfig


def _make_node(label: NodeLabel = NodeLabel.MODULE, uid: str = "test:mod:main") -> GraphNode:
    return GraphNode(uid=uid, label=label, properties={"name": "main"})


def _make_edges(call_count: int) -> list[GraphEdge]:
    return [
        GraphEdge(
            source_uid="test:mod:main",
            target_uid=f"test:mod:dep{i}",
            edge_type=EdgeType.CALLS,
            properties={},
        )
        for i in range(call_count)
    ]


def _make_page_data(
    node: GraphNode | None = None,
    edges: list[GraphEdge] | None = None,
    methods: list | None = None,
):
    pd = MagicMock()
    pd.node = node or _make_node()
    pd.edges = edges or []
    pd.methods = methods or []
    pd.children = []
    pd.code_snippets = []
    pd.related_chunks = []
    return pd


class TestShouldGenerate:
    def test_module_with_enough_calls_triggers(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(4))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is True

    def test_module_with_few_calls_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(2))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is False

    def test_class_with_enough_methods_and_calls_triggers(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        methods = [MagicMock() for _ in range(6)]
        pd = _make_page_data(
            node=_make_node(NodeLabel.CLASS, "test:cls:MyClass"),
            edges=_make_edges(3),
            methods=methods,
        )
        assert gen._should_generate(pd, PageType.CLASS_DETAIL, "full") is True

    def test_class_with_few_methods_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        methods = [MagicMock() for _ in range(2)]
        pd = _make_page_data(
            node=_make_node(NodeLabel.CLASS, "test:cls:Small"),
            edges=_make_edges(3),
            methods=methods,
        )
        assert gen._should_generate(pd, PageType.CLASS_DETAIL, "full") is False

    def test_structure_mode_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(10))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "structure") is False

    def test_no_llm_skips(self):
        gen = SemanticDiagramGenerator(llm=None)
        pd = _make_page_data(edges=_make_edges(10))
        assert gen._should_generate(pd, PageType.MODULE_OVERVIEW, "full") is False

    def test_unsupported_page_type_skips(self):
        gen = SemanticDiagramGenerator(llm=MagicMock())
        pd = _make_page_data(edges=_make_edges(10))
        assert gen._should_generate(pd, PageType.REPO_OVERVIEW, "full") is False
```

- [ ] **Step 4: Write failing test for generate (LLM integration)**

Add to `tests/wiki/test_semantic_diagram_gen.py`:

```python
import asyncio


class TestGenerate:
    def test_successful_generation(self):
        mock_llm = MagicMock()
        mock_llm.generate = MagicMock(
            return_value=asyncio.coroutine(
                lambda *a, **kw: "sequenceDiagram\n    A->>B: process\n    B-->>A: result"
            )()
        )

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(5))
            entity_digest = "- Label: module\n- UID: test:mod:main\n- Calls out to:\n  -> dep0\n  -> dep1"
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, entity_digest, "full")
            assert len(diagrams) == 1
            assert diagrams[0].diagram_type.value == "sequenceDiagram"
            assert "sequenceDiagram" in diagrams[0].content

        asyncio.get_event_loop().run_until_complete(_run())

    def test_llm_failure_returns_empty(self):
        mock_llm = MagicMock()
        mock_llm.generate = MagicMock(side_effect=Exception("LLM down"))

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(5))
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, "digest", "full")
            assert diagrams == []

        asyncio.get_event_loop().run_until_complete(_run())

    def test_invalid_mermaid_filtered(self):
        mock_llm = MagicMock()
        mock_llm.generate = MagicMock(
            return_value=asyncio.coroutine(
                lambda *a, **kw: "This is not valid mermaid"
            )()
        )

        async def _run():
            gen = SemanticDiagramGenerator(llm=mock_llm)
            pd = _make_page_data(edges=_make_edges(5))
            diagrams = await gen.generate(pd, PageType.MODULE_OVERVIEW, "digest", "full")
            assert diagrams == []

        asyncio.get_event_loop().run_until_complete(_run())
```

- [ ] **Step 5: Run all tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_semantic_diagram_gen.py -v`
Expected: Multiple FAIL

- [ ] **Step 6: Implement SemanticDiagramGenerator**

Create `wiki/semantic_diagram_gen.py`:

```python
"""LLM-powered semantic diagram generation for wiki pages.

Generates Mermaid sequence diagrams by asking the LLM to analyze
entity_digest context and produce business-logic-level interaction diagrams.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from store.schema import EdgeType
from wiki.models import DiagramType, PageType, WikiDiagram

if TYPE_CHECKING:
    from wiki.composer import PageData

log = logging.getLogger(__name__)

_MAX_MERMAID_LINES = 80

VALID_MERMAID_STARTS = frozenset({
    "sequenceDiagram", "stateDiagram-v2", "stateDiagram",
    "flowchart", "graph", "classDiagram",
})

_SYSTEM_PROMPT = (
    "You are a software architecture diagramming expert. "
    "Generate valid Mermaid syntax only. "
    "No markdown fences, no explanatory text. Return ONLY the Mermaid code.\n\n"
    "Mermaid syntax rules:\n"
    "- Participant names must be simple identifiers (alphanumeric, no spaces, no special chars)\n"
    "- Use aliases for readable labels: participant SVC as ServiceLayer\n"
    "- Arrow messages can contain spaces and punctuation\n"
    "- Keep diagrams concise: 5-10 participants maximum\n"
)

_MODULE_USER_PROMPT = """\
Based on the following module analysis, generate a Mermaid sequence diagram \
showing the main calling flow between this module's key components.

Module: {name}

Key components and their relationships:
{entity_digest}

Generate a sequenceDiagram that shows:
1. The most important calling sequence (pick the primary use case)
2. Use descriptive messages on the arrows
3. Keep to 5-10 participants maximum
4. Use activate/deactivate for key participants

Example format:
sequenceDiagram
    participant C as Controller
    participant S as Service
    participant R as Repository
    C->>S: processRequest()
    activate S
    S->>R: fetchData()
    R-->>S: data
    S-->>C: result
    deactivate S

Return ONLY the Mermaid code starting with "sequenceDiagram"."""

_CLASS_USER_PROMPT = """\
Based on the following class analysis, generate a Mermaid sequence diagram \
showing the key method interaction flow within this class and its collaborators.

Class: {name}

Methods and relationships:
{entity_digest}

Generate a sequenceDiagram that shows:
1. The primary business workflow through this class's methods
2. How this class interacts with its dependencies
3. Use descriptive messages on the arrows
4. Keep to 5-8 participants maximum

Return ONLY the Mermaid code starting with "sequenceDiagram"."""

_MIN_CALLS_MODULE = 3
_MIN_CALLS_CLASS = 2
_MIN_METHODS_CLASS = 5


class SemanticDiagramGenerator:
    __slots__ = ("_llm",)

    def __init__(self, llm: "LLMPort | None") -> None:
        self._llm = llm

    def _should_generate(
        self, page_data: "PageData", page_type: PageType, mode: str,
    ) -> bool:
        if mode != "full" or self._llm is None:
            return False
        call_edges = sum(1 for e in page_data.edges if e.edge_type == EdgeType.CALLS)
        if page_type == PageType.MODULE_OVERVIEW:
            return call_edges >= _MIN_CALLS_MODULE
        if page_type == PageType.CLASS_DETAIL:
            method_count = len(getattr(page_data, "methods", []) or [])
            return method_count >= _MIN_METHODS_CLASS and call_edges >= _MIN_CALLS_CLASS
        return False

    def _build_prompt(
        self, page_data: "PageData", page_type: PageType, entity_digest: str,
    ) -> str:
        name = page_data.node.properties.get("name", page_data.node.uid)
        if page_type == PageType.MODULE_OVERVIEW:
            return _MODULE_USER_PROMPT.format(name=name, entity_digest=entity_digest)
        return _CLASS_USER_PROMPT.format(name=name, entity_digest=entity_digest)

    @staticmethod
    def _validate_and_clean(raw: str) -> str | None:
        if not raw or not raw.strip():
            return None
        text = raw.strip()
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl == -1:
                return None
            text = text[first_nl + 1:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        if not text:
            return None
        first_line = text.split("\n")[0].strip()
        if not any(first_line.startswith(p) for p in VALID_MERMAID_STARTS):
            return None
        if text.count("\n") + 1 > _MAX_MERMAID_LINES:
            return None
        return text

    @staticmethod
    def _infer_title(page_type: PageType) -> str:
        if page_type == PageType.MODULE_OVERVIEW:
            return "Module interaction flow"
        return "Class interaction flow"

    async def generate(
        self,
        page_data: "PageData",
        page_type: PageType,
        entity_digest: str,
        mode: str,
    ) -> list[WikiDiagram]:
        if not self._should_generate(page_data, page_type, mode):
            return []
        assert self._llm is not None
        try:
            prompt = self._build_prompt(page_data, page_type, entity_digest)
            raw = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)
            cleaned = self._validate_and_clean(raw)
            if cleaned is None:
                entity_name = page_data.node.properties.get("name", page_data.node.uid)
                log.info("semantic_diagram_invalid_mermaid", entity=entity_name)
                return []
            title = self._infer_title(page_type)
            return [
                WikiDiagram(
                    diagram_type=DiagramType.SEQUENCE_DIAGRAM,
                    content=cleaned,
                    title=title,
                )
            ]
        except Exception:
            log.debug("semantic_diagram_failed", exc_info=True)
            return []
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_semantic_diagram_gen.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add wiki/semantic_diagram_gen.py tests/wiki/test_semantic_diagram_gen.py
git commit -m "feat(wiki): implement SemanticDiagramGenerator with LLM sequence diagrams"
```

---

### Task 3: Composer Integration

**Files:**
- Modify: `wiki/composer.py:1-10` (imports), `wiki/composer.py:340-387` (compose_page main path)
- Create: `tests/wiki/test_composer_semantic_diagrams.py`

**Context:** The integration point is in `compose_page` around line 347, after `_build_diagrams` returns deterministic diagrams. We instantiate `SemanticDiagramGenerator` in `WikiComposer.__init__` and call `generate()` in the main compose path. The `entity_digest` is already computed during tier-2 LLM generation (line 703 via `_entity_digest`), but for the semantic diagram path we need to ensure it's available regardless of which tier was selected. The cleanest approach: compute `entity_digest` once in the main path and reuse for both tier-2 LLM and semantic diagram generation.

**Key points:**
- `SemanticDiagramGenerator` is initialized in `WikiComposer.__init__` with the same `llm` port
- `entity_digest` is computed once in `compose_page` main path (move the call before tier selection)
- After `_build_diagrams`, call `semantic_gen.generate()` and extend the diagrams list
- Only execute in the main compose path (not SKELETON branches)

- [ ] **Step 1: Write failing integration test**

Create `tests/wiki/test_composer_semantic_diagrams.py`:

```python
"""Integration tests: composer + semantic diagram generation."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.models import DiagramType, PageType, WikiConfig


def _make_page_data(call_count: int = 5, label: NodeLabel = NodeLabel.MODULE):
    node = GraphNode(
        uid="test:mod:main",
        label=label,
        properties={"name": "main", "business_domain": "core"},
    )
    edges = [
        GraphEdge(
            source_uid="test:mod:main",
            target_uid=f"test:mod:dep{i}",
            edge_type=EdgeType.CALLS,
            properties={},
        )
        for i in range(call_count)
    ]
    pd = MagicMock()
    pd.node = node
    pd.edges = edges
    pd.children = []
    pd.methods = []
    pd.code_snippets = []
    pd.related_chunks = []
    pd.method_locations = []
    pd.source_location = MagicMock()
    return pd


class TestComposerSemanticDiagramIntegration:
    def test_semantic_diagrams_appended_in_full_mode(self):
        """When mode=full and LLM available, semantic diagrams should be appended."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value="sequenceDiagram\n    A->>B: call\n    B-->>A: result"
        )

        async def _run():
            from wiki.composer import WikiComposer

            ctx = MagicMock()
            ctx.build_style_sheet.return_value = ""
            ctx.build_page_context.return_value = ""
            ctx.find_related_docs.return_value = []

            composer = WikiComposer(
                llm=mock_llm,
                context_builder=ctx,
            )
            config = WikiConfig(repository="test/repo", mode="full", language="en")
            pd = _make_page_data(call_count=5)

            page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, config)

            assert page is not None
            seq_diagrams = [
                d for d in page.diagrams
                if d.diagram_type == DiagramType.SEQUENCE_DIAGRAM
            ]
            assert len(seq_diagrams) >= 1
            assert "sequenceDiagram" in seq_diagrams[0].content

        asyncio.get_event_loop().run_until_complete(_run())

    def test_no_semantic_diagrams_in_structure_mode(self):
        """When mode=structure, no semantic diagrams should be generated."""
        mock_llm = AsyncMock()

        async def _run():
            from wiki.composer import WikiComposer

            ctx = MagicMock()
            ctx.build_style_sheet.return_value = ""
            ctx.build_page_context.return_value = ""

            composer = WikiComposer(llm=mock_llm, context_builder=ctx)
            config = WikiConfig(repository="test/repo", mode="structure", language="en")
            pd = _make_page_data(call_count=5)

            page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, config)

            assert page is not None
            seq_diagrams = [
                d for d in page.diagrams
                if d.diagram_type == DiagramType.SEQUENCE_DIAGRAM
            ]
            assert len(seq_diagrams) == 0

        asyncio.get_event_loop().run_until_complete(_run())

    def test_no_semantic_diagrams_without_llm(self):
        """When no LLM, no semantic diagrams."""
        async def _run():
            from wiki.composer import WikiComposer

            ctx = MagicMock()
            composer = WikiComposer(llm=None, context_builder=ctx)
            config = WikiConfig(repository="test/repo", mode="full", language="en")
            pd = _make_page_data(call_count=5)

            page = await composer.compose_page(pd, PageType.MODULE_OVERVIEW, config)

            assert page is not None
            seq_diagrams = [
                d for d in page.diagrams
                if d.diagram_type == DiagramType.SEQUENCE_DIAGRAM
            ]
            assert len(seq_diagrams) == 0

        asyncio.get_event_loop().run_until_complete(_run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_composer_semantic_diagrams.py -v`
Expected: FAIL (SemanticDiagramGenerator not wired into composer yet)

- [ ] **Step 3: Implement composer integration**

In `wiki/composer.py`, make these changes:

**3a. Add import** (near other wiki imports at top of file):

```python
from wiki.semantic_diagram_gen import SemanticDiagramGenerator
```

**3b. Initialize in `__init__`** (after `self._wikilink_cache = wikilink_cache`):

```python
self._semantic_gen = SemanticDiagramGenerator(llm)
```

**3c. In `compose_page` main path** (after line 347 `diagrams = self._build_diagrams(page_data, page_type)`, before building WikiPage):

```python
        # LLM semantic diagrams (mode=full only, async)
        entity_digest_str = self._entity_digest(page_data, page_type, config=config)
        semantic_diagrams = await self._semantic_gen.generate(
            page_data, page_type, entity_digest_str, config.mode,
        )
        diagrams.extend(semantic_diagrams)
```

Note: `_entity_digest` is already called in `_tier2_llm` for tier-2 generation. For the main path, if we already went through tier-2, the digest was computed there. To avoid double-computation, we compute it once in the main path. However, since `_entity_digest` is a pure function (no side effects, fast), calling it twice is acceptable and simpler than refactoring the tier-2 flow.

- [ ] **Step 4: Run integration tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_composer_semantic_diagrams.py -v`
Expected: All PASS

- [ ] **Step 5: Run full wiki test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/ -x --timeout=60 -q`
Expected: All PASS (no regression)

- [ ] **Step 6: Commit**

```bash
git add wiki/composer.py tests/wiki/test_composer_semantic_diagrams.py
git commit -m "feat(wiki): integrate SemanticDiagramGenerator into compose_page pipeline"
```
