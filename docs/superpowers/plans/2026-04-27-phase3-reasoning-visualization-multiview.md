# Phase 3 — Reasoning Visualization, Multi-View Wiki, Offline Data Package (Implementation Plan)

> **Spec**: [`docs/superpowers/specs/2026-04-27-phase3-reasoning-visualization-multiview-design.md`](../specs/2026-04-27-phase3-reasoning-visualization-multiview-design.md)  
> **Date**: 2026-04-27  
> **Tooling**: Python via **`uv`** (never `pip`); dashboard via **`pnpm`** (never `npm`).  
> **Repo root**: `knowledge-base-service/` (all paths below are relative to this directory).

---

## 0. Review amendments (must follow)

These override or narrow the draft spec where they conflict:

1. **Reasoning path semantics**: A **reasoning path** is an ordered **sequence of retrieval stages and the entity / page hits at each stage**, *not* a graph-topology walk. The UI explains *which retrieval method surfaced which entities* and *which entities appear in the final answer* (via text match), not A→B graph edges as the primary metaphor.
2. **Answer entity linkage**: Do **not** require the LLM to emit explicit entity IDs. **Post-process** the final answer by matching substrings against a **known candidate name set** (from search hits + graph context + source list).
3. **Offline scope (Phase 3c)**: Implement **offline data package download** only. **Service Worker caching** is explicitly **deferred** (document as future optimization; no `sw.js` in this phase).
4. **Search vs. tree “view”**: **Wiki search** (POST `/wiki/search`, POST `/wiki/search/global`) returns **all importance tiers** regardless of the user’s tier mode. **Tree navigation**, **landing page**, and **page browse** respect the selected **importance tier mode**. The existing URL param **`view`** stays reserved for **`business_domain` | `code_structure`**; add a **separate** query param for tier (see §B).
5. **ReasoningPathPanel UX**: If the rendered path has **more than 10 steps**, show the first 10 and a **“Show more”** control to expand (see step A18).

---

## 1. Header

### Goal

Deliver three **independently shippable** slices:

- **Phase 3a — Task Group A**: Expose a structured **reasoning path** from Wiki Q&A (and optionally Dashboard deep search), with a **ReasoningPathPanel** in the Dashboard.
- **Phase 3b — Task Group B**: **Importance-tier “wiki view mode”** (comprehensive / standard / essential) affecting **tree + landing** only; **search unchanged** for tier filtering.
- **Phase 3c — Task Group C**: **GET** endpoint that builds a single **offline JSON package** (pages + tree + metadata + optional snapshot pointer) and a **Download** affordance in the UI.

### Architecture (target)

| Area | Target |
|------|--------|
| **Reasoning model** | `wiki/reasoning_path.py` — dataclasses + pure functions: stage lists, provenance merge, **answer text → entity match** against known names. |
| **Wiki search** | `wiki/search.py` — extend fusion so each result row knows **which retrievers** (graph / vector / FTS) contributed, before trimming to `limit`. |
| **Wiki Q&A** | `wiki/ask.py` — `GraphEnhancedContextCollector` returns **structured stage records**; `WikiAskService` merges with search provenance + **matched answer entities**; SSE adds `wiki-reasoning-path` (or embed in `wiki-answer-complete`). |
| **Deep search** | `query/deep_search.py` — build `reasoning_path` from **plan → per sub-query execution → synthesis iterations**; attach **entity names** extracted from hybrid/graph result rows; merge **answer entity match** on final `analysis`. |
| **Tier mode** | Query param `wiki_tier` = `comprehensive` \| `standard` \| `essential` (default `comprehensive`). Backend **`GET /wiki/tree`** gains `wiki_tier`; server **filters `WikiPage` nodes** by `importance_tier` and prunes empty branches. |
| **Offline pack** | New **`GET /wiki/offline-pack`** (or under `/export/offline-pack`) returning `application/json` document: tree, pages, `generated_at`, optional `wiki_snapshot` text if available. |

### Conventions for this plan

- Each **step** is **one action** (≈2–5 minutes): one test file, one module, one route change, or one React file.
- **TDD** wherever code is testable without a browser: **write failing test → `uv run pytest …` (red) → implement → green →** optional commit.
- **Complete code** in the step means: the **full contents** of the *new* file, or the **full replacement** of an existing file if the change is localized; for *large* existing files, steps show **full new symbols** plus **minimal edit instructions** (“insert after line …”) so the step remains one action.
- **Commands** are run from `knowledge-base-service/`.

---

## 2. File index (new / touched)

| Path | Group | Role |
|------|-------|------|
| `wiki/reasoning_path.py` | A | Dataclasses `ReasoningStage`, `ReasoningPath`; `extract_entities_in_answer()`; `merge_reasoning_path()`. |
| `wiki/search.py` | A | Per-hit `retriever_hits` / `match_sources`; extend `SearchResult` / `SearchResponse`. |
| `wiki/ask.py` | A | Collector returns stages; `AskResponse` + SSE events include `reasoning_path`. |
| `api/models/wiki_models.py` | A | Optional Pydantic models if non-stream clients are added later; SSE remains primary. |
| `tests/wiki/test_reasoning_path.py` | A | Pure function tests. |
| `tests/wiki/test_wiki_search_provenance.py` | A | Mocked fusion / metadata tests. |
| `tests/api/test_wiki_ask_reasoning_sse.py` | A | SSE event includes reasoning (TestClient stream). |
| `query/deep_search.py` | A | `reasoning_path` in return + stream conclusion. |
| `api/routes/search_routes.py` | A | Deep search JSON includes `reasoning_path`. |
| `dashboard/src/hooks/wikiTypes.ts` | A | Types for reasoning steps. |
| `dashboard/src/hooks/useWikiAsk.ts` | A | Parse new SSE event; state for path. |
| `dashboard/src/components/wiki/ReasoningPathPanel.tsx` | A | Collapsible panel; **>10 steps** truncated with expander. |
| `dashboard/src/components/wiki/__tests__/ReasoningPathPanel.test.tsx` | A | Vitest + Testing Library. |
| `store/wiki_tree_store.py` | B | `get_wiki_tree(..., wiki_tier=...)` or filter in route. |
| `api/routes/wiki_page_routes.py` | B | `wiki_get_tree` query param `wiki_tier`. |
| `tests/api/test_wiki_tree_routes.py` | B | Tier filtering behavior (may need graph fixture or mock store). |
| `dashboard/src/components/wiki/wikiRouteHelpers.ts` | B | Parse `wiki_tier` from URL. |
| `dashboard/src/hooks/useWikiTree.ts` | B | Pass `wiki_tier` to API. |
| `dashboard/src/components/wiki/WikiViewModeSelector.tsx` | B | New selector (tier, not structure view). |
| `dashboard/src/components/wiki/WikiShell.tsx` | B | Wire selector + URL. |
| `dashboard/src/components/wiki/WikiTreeNav.tsx` | B | Receive `wikiTier` / linkParams. |
| `dashboard/src/components/wiki/WikiLandingPage.tsx` | B | Same tree query with tier. |
| `api/routes/wiki_page_routes.py` (or `wiki_feedback_routes.py`) | C | `GET` offline pack. |
| `wiki/offline_pack.py` (optional) | C | Build JSON from `WikiStore`. |
| `tests/api/test_wiki_offline_pack.py` | C | JSON shape + auth. |
| `dashboard/.../WikiExportPanel.tsx` or `WikiToolPanel` area | C | Download button. |

---

# Task Group A — Phase 3a: Reasoning Path Visualization

## A1 — Failing tests for pure extraction (TDD: red)

**Action**: Add `tests/wiki/test_reasoning_path.py` with full content below.  
**Command**:

```bash
uv run pytest tests/wiki/test_reasoning_path.py -q
```

Expect **ImportError** or failures until A2.

```python
# tests/wiki/test_reasoning_path.py
from wiki.reasoning_path import (
    ReasoningPath,
    ReasoningStep,
    build_candidate_entity_names,
    extract_entities_in_answer,
    merge_stage_lists,
)

def test_extract_entities_prefers_longest_match():
    names = build_candidate_entity_names(
        ["Bar", "BarBaz", "FooService"],
    )
    found = extract_entities_in_answer(
        "Use FooService and BarBaz; ignore Bar.",
        names,
    )
    assert "FooService" in found
    assert "BarBaz" in found
    assert "Bar" not in found

def test_merge_stage_lists_order():
    a = [ReasoningStep(stage="retrieval", detail="rrf", entities=["A"])]
    b = [ReasoningStep(stage="context", detail="one_hop", entities=["B"])]
    m = merge_stage_lists(a, b, answer_entities=["C"])
    assert [x.entities for x in m[:2]] == [["A"], ["B"]]
    assert m[-1].stage == "answer_entities"

def test_reasoning_path_serialization():
    p = ReasoningPath(steps=[
        ReasoningStep(stage="retrieval", detail="graph_path", entities=["X"]),
    ])
    d = p.to_jsonable()
    assert d["steps"][0]["stage"] == "retrieval"
```

## A2 — Implement `wiki/reasoning_path.py` (TDD: green)

**Action**: Create the module with **full** implementation.

**Command**:

```bash
uv run pytest tests/wiki/test_reasoning_path.py -q
```

```python
# wiki/reasoning_path.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# Complete implementation (adjust tests in A1 if you prefer stricter bar/barbaz policy — document in docstring)
@dataclass
class ReasoningStep:
    """One row in the explanation timeline (not a Neo4j edge)."""
    stage: str  # e.g. "retrieval", "context", "graph_expand", "answer_entities"
    detail: str  # e.g. "wiki_rrf:graph+vector+fts", "section:graph_context", "one_hop"
    entities: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class ReasoningPath:
    steps: list[ReasoningStep] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "steps": [
                {
                    "stage": s.stage,
                    "detail": s.detail,
                    "entities": list(s.entities),
                    "meta": dict(s.meta),
                }
                for s in self.steps
            ]
        }

def build_candidate_entity_names(candidates: Iterable[str]) -> list[str]:
    """Deduplicate and sort by length descending for longest-first matching."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in candidates:
        s = (raw or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return sorted(out, key=len, reverse=True)

def extract_entities_in_answer(answer: str, sorted_names: Sequence[str]) -> list[str]:
    """Greedy longest-first substring match; non-overlapping spans in *answer*."""
    if not answer:
        return []
    found: list[str] = []
    used = [False] * len(answer)
    for name in sorted_names:
        if not name:
            continue
        start = 0
        while True:
            i = answer.find(name, start)
            if i < 0:
                break
            if any(used[i : i + len(name)]):
                start = i + 1
                continue
            for j in range(i, i + len(name)):
                used[j] = True
            found.append(name)
            start = i + len(name)
    return found

def merge_stage_lists(
    *parts: Sequence[ReasoningStep],
    answer_entities: list[str] | None = None,
) -> list[ReasoningStep]:
    out: list[ReasoningStep] = []
    for seq in parts:
        out.extend(seq)
    if answer_entities:
        out.append(
            ReasoningStep(
                stage="answer_entities",
                detail="text_match",
                entities=list(answer_entities),
            )
        )
    return out
```

## A3 — Wiki search: per-result retriever provenance (tests first)

**Action**: Add `tests/wiki/test_wiki_search_provenance.py` that builds small artificial `g_ranked`, `v_ranked`, `f_ranked` and asserts a helper `attach_retriever_provenance` lists correct sources. Start with a **static helper** in `wiki/search.py` (or `wiki/reasoning_path.py`) to avoid full async until A4.

**Command**:

```bash
uv run pytest tests/wiki/test_wiki_search_provenance.py -q
```

Use a minimal test file (~40 lines) that imports a function:

```python
# tests/wiki/test_wiki_search_provenance.py
from wiki.search import retriever_hits_for_page

def test_provenance_all_three():
    g = [("p1", 0.0), ("p2", 0.0)]
    v = [("p2", 0.0), ("p3", 0.0)]
    f = [("p1", 0.0)]
    m = retriever_hits_for_page("p1", g, v, f)
    assert set(m) == {"graph", "vector", "fts"}


def test_provenance_fts_only():
    g: list = []
    v: list = []
    f = [("p9", 0.0)]
    assert retriever_hits_for_page("p9", g, v, f) == ["fts"]
```

## A4 — Implement `retriever_hits_for_page` and wire `WikiSearchService.search`

**Action**: In `wiki/search.py`:

1. Add function:

```python
def retriever_hits_for_page(
    page_path: str,
    g_ranked: list[tuple[str, float]],
    v_ranked: list[tuple[str, float]],
    f_ranked: list[tuple[str, float]],
) -> list[str]:
    out: list[str] = []
    if any(p == page_path for p, _ in g_ranked):
        out.append("graph")
    if any(p == page_path for p, _ in v_ranked):
        out.append("vector")
    if any(p == page_path for p, _ in f_ranked):
        out.append("fts")
    return out
```

2. Extend `@dataclass SearchResult` with `retriever_hits: list[str] = field(default_factory=list)`.
3. After the fusion loop that builds `results`, for each `SearchResult` set `retriever_hits=retriever_hits_for_page(page_path, g_ranked, v_ranked, f_ranked)` (use the **same** lists passed to `rrf_fusion`).

**Command**:

```bash
uv run pytest tests/wiki/test_wiki_search_provenance.py tests/wiki/ -q
```

## A5 — Failing test: reasoning steps from `GraphEnhancedContextCollector` (optional slice)

**Action**: If extracting collector logic is too large for one step, add **`tests/wiki/test_graph_enhanced_context_stages.py`** with a **stub** collector that returns fixed stages; skip integration until A6.

(Alternatively skip A5 and go straight to A6 with manual verification.)

## A6 — `GraphEnhancedContextCollector` returns `list[ReasoningStep]`

**Action**: In `wiki/ask.py`, add method `collect_with_stages(...)` returning `(str, list[ReasoningStep])` **or** change `collect` to return a small `@dataclass` `GraphContextResult`. Each subsection (wiki pages, graph section by question type, signatures, module overview) appends one `ReasoningStep` with `stage="context"`, `detail`区分 e.g. `"full_wiki_pages"`, `"graph:one_hop"`, etc., and `entities` = entity names **parsed from that section’s query rows** (seed names, relation path nodes, etc.).

**Command**:

```bash
uv run pytest tests/wiki/test_ask_context_stages.py -q
```

(Create `tests/wiki/test_ask_context_stages.py` with mocked `WikiStore` methods returning one row each.)

## A7 — `WikiAskService.ask_stream`: build `ReasoningPath` and emit SSE

**Action**: After search + sources + optional collector:

1. Build **retrieval step** from `search_resp` first results: one `ReasoningStep(stage="retrieval", detail="wiki_hybrid", entities=[...])` with per-top-hit entities from `SearchResult` + **retriever_hits** encoded in `meta["retriever_hits"]` *or* one step per result row (prefer **one step per result** for clarity, max 5, with `meta`).

2. `candidate_names = build_candidate_entity_names(
     [entity names from sources + all step entities] )`

3. After LLM returns `full_text`, `answer_entities = extract_entities_in_answer(full_text, candidate_names)`.

4. `path = ReasoningPath(steps=merge_stage_lists(retrieval_steps, context_steps, answer_entities=answer_entities))`

5. New SSE event **after** `wiki-sources`, before `wiki-answer-complete`:

   ```python
   yield {"event": "wiki-reasoning-path", "data": {"reasoning_path": path.to_jsonable()}}
   ```

6. Extend `AskResponse` with `reasoning_path: list[dict[str, Any]]` (or structured type); `ask()` collects from the new event.

**Command**:

```bash
uv run pytest tests/api/test_wiki_ask_reasoning_sse.py -q
```

Example test (full file):

```python
# tests/api/test_wiki_ask_reasoning_sse.py
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch):
    from main import app
    from api.routes.wiki_shared import get_wiki_ask_dep
    from wiki.ask import WikiAskService, AskResponse, SearchResponse, SearchResult
    from wiki.search import SearchResponse as SR2

    async def fake_search(*a, **k):
        from wiki.search import SearchResponse, SearchResult
        return SearchResponse(
            results=[
                SearchResult(
                    page_path="a/b.md", title="T", score=0.5, snippet="s",
                    source_locations=[{"entity": "Foo", "name": "Foo"}],
                    context={},
                )
            ],
            query_expansion={},
            total=1,
        )

    async def fake_llm(messages, **k):
        return "Use Foo in your code."

    class DummySearch:
        async def search(self, *a, **k):
            from wiki.search import SearchResponse, SearchResult
            return SearchResponse(
                results=[SearchResult(
                    page_path="a/b.md", title="T", score=0.5, snippet="s",
                    source_locations=[{"entity": "Foo", "name": "Foo"}],
                    context={},
                )],
                query_expansion={},
                total=1,
            )

    monkeypatch.setitem(app.dependency_overrides, get_wiki_ask_dep, lambda: WikiAskService(
        search=DummySearch(), llm=type("L", (), {"complete": staticmethod(fake_llm)})(),
    ))
    return TestClient(app)
```

(Adjust imports to match actual `WikiAskService` constructor and `get_wiki_ask_dep` import path; use project’s test patterns from `tests/api/`.)

## A8 — Dashboard: types + `useWikiAsk` + `consumeWikiAskStream`

**Action**:

- `dashboard/src/hooks/wikiTypes.ts`: add `export type WikiReasoningPath = { steps: WikiReasoningStep[] };` etc.
- `useWikiAsk.ts`: handle `eventName === "wiki-reasoning-path"`, `setReasoningPath(data.reasoning_path)`.
- Export `reasoningPath` from the hook return value.

**Command**:

```bash
cd dashboard && pnpm exec vitest run src/hooks/__tests__/useWikiAsk.test.ts
```

(Add test file if missing, or manual smoke test only — prefer test.)

## A9 — `ReasoningPathPanel.tsx` (full file)

**Action**: Create `dashboard/src/components/wiki/ReasoningPathPanel.tsx` with the **full** implementation below.

- Collapsible `<details>` or headless pattern consistent with `WikiShell`.
- Map `steps` to a vertical list: **Stage · detail** and entity chips.
- If `steps.length > 10`, render **10** and a button **Show more** toggling the rest.
- **No** graph-edge arrows as primary; use labels “Retrieval”, “Context”, “Answer mentions”.

**Full component** (adjust Tailwind classes to match neighboring panels):

```tsx
// dashboard/src/components/wiki/ReasoningPathPanel.tsx
import { useId, useState } from "react";

export type JsonReasoningStep = {
  stage: string;
  detail: string;
  entities: string[];
  meta?: Record<string, unknown>;
};

type Props = {
  path: { steps: JsonReasoningStep[] } | null;
  defaultOpen?: boolean;
};

const PREVIEW = 10;

export default function ReasoningPathPanel({ path, defaultOpen = false }: Props) {
  const id = useId();
  const [showAll, setShowAll] = useState(false);
  const steps = path?.steps ?? [];
  if (!steps.length) return null;

  const hasMore = steps.length > PREVIEW;
  const visible = showAll || !hasMore ? steps : steps.slice(0, PREVIEW);

  return (
    <details
      className="rounded-lg border border-gray-200 bg-gray-50/80 dark:border-gray-600 dark:bg-gray-800/50"
      open={defaultOpen}
    >
      <summary className="cursor-pointer list-none px-3 py-2 text-sm font-medium text-gray-800 dark:text-gray-100">
        Reasoning path
      </summary>
      <ul className="space-y-2 border-t border-gray-200 px-3 py-2 dark:border-gray-600" id={id}>
        {visible.map((s, i) => (
          <li key={`${s.stage}-${s.detail}-${i}`} className="text-sm" role="listitem">
            <div className="font-medium text-gray-800 dark:text-gray-200">
              {s.stage} · {s.detail}
            </div>
            {s.entities.length > 0 ? (
              <div className="mt-0.5 flex flex-wrap gap-1">
                {s.entities.map((e) => (
                  <span
                    key={e}
                    className="rounded bg-white px-1.5 py-0.5 text-xs text-gray-700 shadow-sm dark:bg-gray-900 dark:text-gray-200"
                  >
                    {e}
                  </span>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {hasMore && !showAll ? (
        <div className="px-3 pb-2">
          <button
            type="button"
            className="text-sm font-medium text-sky-600 hover:underline dark:text-sky-400"
            onClick={() => setShowAll(true)}
          >
            Show more
          </button>
        </div>
      ) : null}
    </details>
  );
}
```

**Command**:

```bash
cd dashboard && pnpm exec vitest run src/components/wiki/__tests__/ReasoningPathPanel.test.tsx
```

**Full test file** `ReasoningPathPanel.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ReasoningPathPanel from "../ReasoningPathPanel";

const many = Array.from({ length: 12 }, (_, i) => ({
  stage: "retrieval",
  detail: `hit-${i}`,
  entities: [`E${i}`],
  meta: {},
}));

describe("ReasoningPathPanel", () => {
  it("truncates to 10 steps until expanded", () => {
    render(<ReasoningPathPanel path={{ steps: many }} defaultOpen />);
    expect(screen.getAllByRole("listitem").length).toBe(10);
    fireEvent.click(screen.getByRole("button", { name: /show more/i }));
    expect(screen.getAllByRole("listitem").length).toBe(12);
  });
});
```

(Align list markup with the component: use `<ul><li>` for steps.)

## A10 — Wire panel into Q&A tool UI

**Action**: Find the component that renders Wiki Q&A (e.g. `WikiToolPanel` child or `WikiAskPanel`). Pass `reasoningPath` from `useWikiAsk` into `ReasoningPathPanel` below sources.

**Command**:

```bash
cd dashboard && pnpm run build
```

## A11 — `DeepSearchEngine.search`: add `reasoning_path`

**Action**: In `query/deep_search.py`, after the main loop, construct `list[ReasoningStep]`:

- Step `plan` with empty entities or intent string in `meta`.
- For each executed sub-query: `ReasoningStep(stage="retrieval", detail=sq["type"], entities=extracted from matches)`.
- Final: `answer_entities` via `extract_entities_in_answer(synthesis["analysis"], candidates)`.

Return `{"reasoning_path": ReasoningPath(...).to_jsonable(), **existing}`.

**Command**:

```bash
uv run pytest tests/query/test_deep_search_reasoning_path.py -q
```

Add new test with mocked `HybridQueryService` / `GraphQueryService`.

## A12 — Expose in `api/routes/search_routes.py` deep search handler

**Action**: Ensure JSON response includes `reasoning_path` key (dashboard deep search UI may ignore until later).

**Command**:

```bash
uv run pytest tests/api/test_search_routes.py -k deep -q
```

---

# Task Group B — Phase 3b: Multi-View Wiki Mode (Importance Tier)

**Naming**: `wiki_tier` = `comprehensive` (all) | `standard` (core+standard) | `essential` (core only). Maps to Cypher: `skeleton` allowed only in `comprehensive`; `standard` in `comprehensive`+`standard`; `core` always.

## B1 — Store: `get_wiki_tree` accepts `wiki_tier`

**Action**: In `store/wiki_tree_store.py`, add optional `wiki_tier: str = "comprehensive"` to `get_wiki_tree`. Implementation options (pick one in implementation):

- **(Preferred)** Add `importance_tier` to the Cypher `RETURN` for `WikiPage` nodes; filter in Python when assembling children.
- **Or** add `WHERE` on `(node:WikiPage)` for tier subset.

**Command**:

```bash
uv run pytest tests/store/test_wiki_tree_tier.py -q
```

New test: mock `execute_query` to return pages with different tiers and assert filtered structure (if unit scope too heavy, use integration flag `pytest -m slow`).

## B2 — Route `GET /wiki/tree` — query param

**Action**: In `api/routes/wiki_page_routes.py` `wiki_get_tree`, add `wiki_tier: str = Query(default="comprehensive")` with pattern/validation `^(comprehensive|standard|essential)$` (use `Literal` or `Enum`).

**Command**:

```bash
uv run pytest tests/api/test_wiki_tree_routes.py -q
```

Extend existing test to pass `wiki_tier=essential` and assert **fewer** nodes when graph data contains mixed tiers (or mock).

## B3 — `parseWikiSearchParams` + `wikiHref` preserve `wiki_tier`

**Action**: In `dashboard/src/components/wiki/wikiRouteHelpers.ts`, parse `wiki_tier` with default `comprehensive`. Add to returned object. `wikiHref` must pass through `wiki_tier` in `linkParams` when set.

**Command**:

```bash
cd dashboard && pnpm exec vitest run src/components/wiki/__tests__/wikiRouteHelpers.test.ts
```

(Add small test file with `new URLSearchParams` expectations.)

## B4 — `useWikiTree(businessId, viewType, wikiTier)`

**Action**: Change `dashboard/src/hooks/useWikiTree.ts` to add third argument; append `&wiki_tier=` to the URL. Update **query key** to include tier.

**Command**:

```bash
cd dashboard && pnpm exec vitest run src/hooks/useWikiTree.ts
```

## B5 — `WikiViewModeSelector.tsx`

**Action**: New component: three options (i18n keys under `t.wiki.*`). On change, updates URL `wiki_tier` with `setSearchParams` (same pattern as `setViewType` in `WikiShell`).

**Full component** (props match how `WikiShell` wires `viewType`; rename if you prefer a single `onWikiTierChange` callback):

```tsx
// dashboard/src/components/wiki/WikiViewModeSelector.tsx
import { useI18n } from "../../i18n/context";

export type WikiTierMode = "comprehensive" | "standard" | "essential";

type Props = {
  wikiTier: WikiTierMode;
  onWikiTierChange: (tier: WikiTierMode) => void;
  id?: string;
};

const OPTIONS: { value: WikiTierMode; labelKey: "wikiTierComprehensive" | "wikiTierStandard" | "wikiTierEssential" }[] = [
  { value: "comprehensive", labelKey: "wikiTierComprehensive" },
  { value: "standard", labelKey: "wikiTierStandard" },
  { value: "essential", labelKey: "wikiTierEssential" },
];

export default function WikiViewModeSelector({ wikiTier, onWikiTierChange, id }: Props) {
  const { t } = useI18n() as { t: { wiki: Record<string, string> } };
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-gray-200 p-0.5 dark:border-gray-600">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          id={id && o.value === wikiTier ? id : undefined}
          type="button"
          onClick={() => onWikiTierChange(o.value)}
          className={
            o.value === wikiTier
              ? "rounded-md bg-sky-100 px-2 py-1 text-xs font-medium text-sky-900 dark:bg-sky-950 dark:text-sky-100"
              : "rounded-md px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
          }
        >
          {t.wiki[o.labelKey] ?? o.value}
        </button>
      ))}
    </div>
  );
}
```

Add the three keys to the i18n `wiki` section (en + zh) in a dedicated micro-step B5b if your locale files split by feature.

**Command**:

```bash
cd dashboard && pnpm exec vitest run src/components/wiki/__tests__/WikiViewModeSelector.test.tsx
```

## B6 — `WikiShell.tsx` integration

**Action**:

- Read `wikiTier` from `parseWikiSearchParams`.
- Add `setWikiTier` similar to `setViewType`, writing `wiki_tier` to query string (delete param when `comprehensive` to keep URLs short).
- Pass `wikiTier` to `WikiTreeNav`, `WikiLandingPage`, `linkParams` for `WikiSearchBar` **for navigation only** — **do not** pass `wiki_tier` into search mutation bodies.

**Command**:

```bash
cd dashboard && pnpm run build
```

## B7 — Confirm search hooks do **not** send `wiki_tier`

**Action**: Grep `useWikiSearch` / `useWikiGlobalSearch` / search components; add a comment in `useWikiSearch.ts` that tier filtering is **intentionally** excluded. Optional assertion in a trivial test on default POST body.

**Command**:

```bash
cd dashboard && pnpm exec vitest run
```

## B8 — MCP (optional, if in scope for your release)

**Action**: If `wiki_get_pages` MCP tool exists, add optional `importance_filter` as in spec; **separate** task — only if spec mandates same phase.

**Command**: `uv run pytest tests/ -k mcp --maxfail=1 -q`

---

# Task Group C — Phase 3c: Offline Data Package (No Service Worker)

## C1 — Builder module `wiki/offline_pack.py`

**Action**: Implement `async def build_offline_pack(wiki_store: WikiStore, business_id: str, view_type: str) -> dict[str, Any]`:

- `pages`: list of `{ "path", "title", "content", "importance_tier", "content_hash" }` from `get_wiki_pages_for_business(business_id, min_tier="skeleton")` (full content).
- `tree`: call same logic as `GET /wiki/tree` with `wiki_tier=comprehensive` (full tree for offline) **or** document that pack always includes all tiers (recommended for true offline read-only mirror).
- `meta`: `{ "business_id", "view_type", "generated_at" (ISO) }`
- `wiki_snapshot.md`: **if** available from your Phase 1 snapshot store, embed or omit `null` with `snapshot_missing: true` (use actual project API for snapshot lookup).

**Command**:

```bash
uv run pytest tests/wiki/test_offline_pack.py -q
```

## C2 — `GET /api/v1/wiki/offline-pack`

**Action**: In `api/routes/wiki_page_routes.py` (or dedicated router included under `wiki`):

```text
GET /wiki/offline-pack?business_id=...&view=business_domain
```

- **Auth/role**: match other read endpoints (e.g. `VIEWER+`).
- Response: `JSONResponse` with `Content-Disposition: attachment; filename="wiki-offline-pack.json"`.

**Skeleton implementation** (imports must match the project: `get_route_settings`, `require_role`, etc.):

```python
# In api/routes/wiki_page_routes.py (or wiki_offline_routes.py + include_router)

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse

from auth import require_role, Role
from store.wiki_store import WikiStore
from wiki.offline_pack import build_offline_pack  # C1

@router.get("/offline-pack", dependencies=[Depends(require_role(Role.VIEWER))])  # adjust to project auth
async def wiki_offline_pack(
    request: Request,
    business_id: str = Query(...),
    view: str = Query(default="business_domain"),
) -> JSONResponse:
    raw = getattr(request.app.state, "wiki_store", None)
    if raw is None:
        return JSONResponse(
            content={"error": "wiki_unavailable", "message": "Graph store not configured"},
            status_code=503,
        )
    store = WikiStore(raw)
    payload = await build_offline_pack(store, business_id, view)
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="wiki-offline-pack.json"'},
    )
```

**Command**:

```bash
uv run pytest tests/api/test_wiki_offline_pack.py -q
```

## C3 — Dashboard download button

**Action**: In Export tool tab (or a small “Offline” subsection), add “Download offline package” that `fetch`es the GET URL with `credentials`, then triggers a Blob download. Show error toast on !ok.

**Command**:

```bash
cd dashboard && pnpm run build
```

## C4 — Manual verification script

**Action**:

```bash
uv run uvicorn main:app --port 8000
curl -sS -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/wiki/offline-pack?business_id=default&view=business_domain" -o /tmp/pack.json
python -c "import json;d=json.load(open('/tmp/pack.json'));print(d.keys())"
```

---

## 3. Cross-cutting verification (after A + B + C)

```bash
uv run ruff check .
uv run pytest -q
cd dashboard && pnpm run lint && pnpm run test && pnpm run build
```

---

## 4. Out of scope (explicit)

- **Service Worker** / PWA / `dashboard/public/sw.js` — **future**; list in `docs/IMPLEMENTATION-STATUS.md` or spec follow-up.
- **React Flow** graph pop-up — not part of 3a (spec A2 was optional).
- **MCP** changes — only if you completed B8.

---

## 5. Suggested commit boundaries

| Commit | Contents |
|--------|----------|
| `feat(wiki): reasoning path core + search provenance` | A1–A4 |
| `feat(wiki): ask SSE reasoning path` | A6–A7, tests |
| `feat(dashboard): ReasoningPathPanel` | A8–A10 |
| `feat(search): deep search reasoning path` | A11–A12 |
| `feat(wiki): tree wiki_tier` | B1–B4 |
| `feat(dashboard): tier selector + URL` | B5–B7 |
| `feat(wiki): offline pack API + download` | C1–C3 |

---

*End of plan.*
