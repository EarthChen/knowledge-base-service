# Phase 1: Knowledge Compilation & Feedback Loop — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a compiled knowledge snapshot (Karpathy-style “index”) that agents can load in one call, enrich `AGENTS.md` without conflating it with the snapshot, expose `wiki_get_snapshot` over MCP, and close the feedback loop with threshold-based regeneration, critical-severity fast path, and a 24h per-page cooldown.

**Architecture:** `WikiCompilationSnapshot` queries the graph for all `WikiPage` rows for a repo, builds markdown (layered when page count ≥ threshold: global index + per-module sub-documents). After every full generation and after incremental ingest that touches pages, run a **full snapshot rebuild** (no diff algorithm — graph queries are cheap and correctness is simpler than merging deltas). `AgentsMdGenerator` documents **how to use tools**; the snapshot is **what knowledge exists** (titles, blurbs, tiers, wikilinks, cross-refs). `FeedbackDrivenRegeneration` runs after `POST .../feedback`, counts negative feedback, optional `severity=critical` on `down`, consults `WikiConfig.feedback_regen_cooldown_hours`, and enqueues a background wiki regen (same pattern as `wiki_task_routes` + `WikiTaskRegistry` / `asyncio.create_task`) with a token-budget multiplier wired into `WikiComposer` (or a thin wrapper) when implemented.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, FalkorDB / graph store, pytest, React (no Phase 1 UI change required beyond optional feedback field).

**Repository root (commands):** `/Users/earthchen/ai-work/agent-work/knowledge-base-service`

**Review notes baked in:**

1. **Snapshot size:** layered = global index + module sub-snapshots when `page_count >= WIKI__SNAPSHOT_LAYER_PAGE_THRESHOLD` (default `100`).
2. **Updates:** always **full rebuild** from graph (no diff).
3. **Cooldown:** `WIKI__FEEDBACK_REGEN_COOLDOWN_HOURS` default `24`.
4. **AGENTS.md vs snapshot:** AGENTS = tool usage; snapshot = knowledge map.
5. **When to run:** immediately after `WikiService` persists wiki pages to the graph (same logical “post-persist” as export would see); optionally `asyncio.gather` snapshot markdown build with `AgentsMdGenerator.generate` since both are I/O + string work (not “after filesystem export” — this codebase exports via `WikiDocsExporter` on demand, not inside `generate()`).

---

## Task Group A: Compilation Snapshot (`wiki/compilation_snapshot.py` + MCP + `WikiService` integration)

**Independent after:** graph `WikiPage` nodes exist; no dependency on Group B/C except shared `WikiConfig` fields.

### A1 — Config: snapshot flags (one step = one edit)

**Files:** `config.py` (`WikiConfig`)

**Command (verify types load):** `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -c "from config import Settings; s=Settings(); print(s.wiki.snapshot_enabled, s.wiki.snapshot_layer_page_threshold)"`

- [x] **Step A1.1 — Add fields to `WikiConfig`**

Add to the `WikiConfig` class in `config.py` (env prefix already `WIKI__` via `Settings`):

```python
# config.py (inside class WikiConfig, with other wiki flags)
snapshot_enabled: bool = True
snapshot_layer_page_threshold: int = 100
```

Full class fragment (merge into existing `WikiConfig`; do not remove neighboring fields):

```python
class WikiConfig(BaseModel):
    """Application-level wiki feature flags (separate from ``wiki.models.WikiConfig``)."""

    # ... existing fields ...

    snapshot_enabled: bool = True
    """When true, run compilation snapshot after wiki pages are persisted."""
    snapshot_layer_page_threshold: int = 100
    """At or above this many wiki pages, emit global index + per-module sub-snapshots."""
```

- [x] **Step A1.2 — Add failing test that defaults resolve**

`tests/wiki/test_compilation_snapshot_config.py`:

```python
from config import Settings


def test_wiki_config_snapshot_defaults():
    s = Settings()
    assert s.wiki.snapshot_enabled is True
    assert s.wiki.snapshot_layer_page_threshold == 100
```

Run: `pytest tests/wiki/test_compilation_snapshot_config.py -q`

---

### A2 — Core: `WikiCompilationSnapshot` (TDD)

**Files:**

- Create: `wiki/compilation_snapshot.py`
- Create: `tests/wiki/test_compilation_snapshot.py`

**Command:** `pytest tests/wiki/test_compilation_snapshot.py -q`

- [x] **Step A2.1 — Test: small repo produces single markdown, includes title line**

`tests/wiki/test_compilation_snapshot.py` (complete):

```python
from __future__ import annotations

import pytest

from config import Settings
from wiki.compilation_snapshot import WikiCompilationSnapshot


class _Result:
    def __init__(self, data: list[dict] | list) -> None:
        self.data = data


class _FakeGraph:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.queries: list[tuple[str, dict]] = []

    async def execute_query(self, cypher: str, params: dict | None = None):
        self.queries.append((cypher, params or {}))
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_generate_single_file_below_threshold():
    rows = [
        {
            "path": "modules/auth.md",
            "title": "Auth",
            "summary": "OAuth2 and JWT " + ("x" * 300),
            "page_type": "module_overview",
            "importance_tier": "core",
            "confidence": 0.85,
            "wikilinks": ["user-model"],
        }
    ]
    g = _FakeGraph(rows)
    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=g, wiki_config=cfg)
    out = await snap.generate("acme", "my-repo")
    assert "# Knowledge Base Snapshot" in out
    assert "my-repo" in out
    assert "[[modules-auth]]" in out or "Auth" in out
    assert "0.85" in out


@pytest.mark.asyncio
async def test_layered_output_over_threshold():
    many = [
        {
            "path": f"modules/p{i}.md",
            "title": f"Page{i}",
            "summary": "S",
            "page_type": "module_overview",
            "importance_tier": "standard",
            "confidence": 0.5,
            "wikilinks": [],
        }
        for i in range(101)
    ]
    g = _FakeGraph(many)
    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=g, wiki_config=cfg)
    layered = await snap.generate_layered("acme", "my-repo")
    assert "index" in layered
    assert "modules" in layered
    assert len(layered["modules"]) >= 1
```

- [x] **Step A2.2 — Implement `wiki/compilation_snapshot.py` (complete)**

```python
"""Build a compiled markdown snapshot of wiki knowledge (graph → markdown)."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


def _summary_excerpt(text: str, max_len: int = 200) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _section_key(path: str) -> str:
    p = (path or "").strip("/")
    if "/" in p:
        return p.split("/", 1)[0]
    return "root"


@dataclass
class _PageRow:
    path: str
    title: str
    summary: str
    page_type: str
    importance_tier: str
    confidence: float | None
    wikilinks: list[str]


class WikiCompilationSnapshot:
    """Full rebuild of a repo's wiki snapshot from graph queries (no diff merge)."""

    def __init__(self, graph: _GraphPort, wiki_config: Any) -> None:
        self._graph = graph
        self._cfg = wiki_config

    @staticmethod
    def _parse_rows(result: Any) -> list[dict[str, Any]]:
        rows = getattr(result, "data", None) or []
        out: list[dict[str, Any]] = []
        for r in rows:
            if isinstance(r, dict):
                out.append(r)
        return out

    async def _fetch_pages(self, repository: str) -> list[_PageRow]:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE coalesce(wp.deprecated, false) = false "
            "RETURN wp.path AS path, wp.title AS title, "
            "left(coalesce(wp.content, ''), 2000) AS content_excerpt, "
            "coalesce(wp.page_type, '') AS page_type, "
            "coalesce(wp.importance_tier, '') AS importance_tier, "
            "coalesce(wp.confidence, null) AS confidence, "
            "coalesce(wp.wikilinks, []) AS wikilinks "
            "ORDER BY wp.path"
        )
        result = await self._graph.execute_query(q, {"repo": repository})
        parsed: list[_PageRow] = []
        for d in self._parse_rows(result):
            raw_links = d.get("wikilinks") or []
            if isinstance(raw_links, str):
                wikilinks = [raw_links]
            else:
                wikilinks = [str(x) for x in raw_links]
            conf = d.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            parsed.append(
                _PageRow(
                    path=str(d.get("path") or ""),
                    title=str(d.get("title") or ""),
                    summary=_summary_excerpt(str(d.get("content_excerpt") or "")),
                    page_type=str(d.get("page_type") or ""),
                    importance_tier=str(d.get("importance_tier") or "standard"),
                    confidence=conf_f,
                    wikilinks=wikilinks,
                )
            )
        return parsed

    def _render_page_line(self, p: _PageRow) -> str:
        slug = p.path.replace(".md", "").replace("/", "-")
        conf = f"{p.confidence:.2f}" if p.confidence is not None else "n/a"
        refs = ", ".join(p.wikilinks[:8]) if p.wikilinks else "—"
        return (
            f"- [[{slug}]]: {p.summary} "
            f"({p.importance_tier or 'standard'}, confidence: {conf}) "
            f"→ references: {refs}"
        )

    def _render_cross_ref(self, pages: list[_PageRow]) -> str:
        """Simple adjacency from wikilinks for snapshot footer."""
        lines: list[str] = ["", "## Cross-Reference Map", ""]
        for p in pages:
            if not p.wikilinks:
                continue
            slug = p.path.replace(".md", "").replace("/", "-")
            targets = ", ".join(p.wikilinks)
            lines.append(f"- {slug} → {targets}")
        if len(lines) <= 3:
            lines.append("_No wikilinks recorded._")
        return "\n".join(lines)

    async def generate(self, _business_id: str, repository: str) -> str:
        """Single-file snapshot (for small KBs or forced mode)."""
        pages = await self._fetch_pages(repository)
        if not pages:
            return self._empty_doc(repository)
        return self._render_bundle(repository, pages, module_sections=None)

    async def generate_layered(self, business_id: str, repository: str) -> dict[str, str]:
        """Return multiple markdown fragments: 'index' + module key → body."""
        pages = await self._fetch_pages(repository)
        if not pages:
            return {"index": self._empty_doc(repository)}
        by_mod: dict[str, list[_PageRow]] = defaultdict(list)
        for p in pages:
            by_mod[_section_key(p.path)].append(p)
        index_body = self._render_index_only(repository, pages, by_mod)
        out: dict[str, str] = {"index": index_body}
        for mod, pgs in sorted(by_mod.items()):
            out[mod] = self._render_bundle(repository, pgs, module_sections={mod: pgs}, title_suffix=mod)
        return out

    def _empty_doc(self, repository: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        return "\n".join(
            [
                f"# Knowledge Base Snapshot — {repository}",
                f"Generated: {now} | Pages: 0",
                "",
                "_No wiki pages in graph._",
            ]
        )

    def _render_index_only(
        self,
        repository: str,
        pages: list[_PageRow],
        by_mod: dict[str, list[_PageRow]],
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lines: list[str] = [
            f"# Knowledge Base Snapshot — {repository} (index)",
            f"Generated: {now} | Pages: {len(pages)} | Modules: {len(by_mod)}",
            "",
            "## Module overview",
            "",
        ]
        for mod, pgs in sorted(by_mod.items()):
            lines.append(f"- **{mod}**: {len(pgs)} page(s) → see `wiki_snapshot__{mod}.md` (embedded in layered mode)")
        lines.append(self._render_cross_ref(pages))
        return "\n".join(lines)

    def _render_bundle(
        self,
        repository: str,
        pages: list[_PageRow],
        module_sections: dict[str, list[_PageRow]] | None,
        title_suffix: str | None = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        title = f"# Knowledge Base Snapshot — {repository}"
        if title_suffix:
            title += f" / {title_suffix}"
        lines: list[str] = [
            title,
            f"Generated: {now} | Pages: {len(pages)}",
            "",
        ]
        if module_sections is None:
            by_mod: dict[str, list[_PageRow]] = defaultdict(list)
            for p in pages:
                by_mod[_section_key(p.path)].append(p)
        else:
            by_mod = module_sections
        for mod, pgs in sorted(by_mod.items()):
            lines.append(f"## Module: {mod}")
            lines.append("")
            for p in pgs:
                lines.append(self._render_page_line(p))
            lines.append("")
        lines.append(self._render_cross_ref(pages))
        return "\n".join(lines).strip() + "\n"

    async def generate_and_persist(
        self,
        business_id: str,
        repository: str,
        persist_fn: Any | None = None,
    ) -> str:
        """Build snapshot; if persist_fn set, store slices via callback."""
        pages = await self._fetch_pages(repository)
        threshold = int(getattr(self._cfg, "snapshot_layer_page_threshold", 100))
        if len(pages) >= threshold:
            layered = await self.generate_layered(business_id, repository)
            if callable(persist_fn):
                await persist_fn(layered, repository, layered=True)
            return layered.get("index", "")
        one = await self.generate(business_id, repository)
        if callable(persist_fn):
            await persist_fn({"(single)": one}, repository, layered=False)
        return one
```

**Note:** If the graph has no `wikilinks` or `confidence` property yet, add a follow-up sub-step to align Cypher with `store` persistence in `wiki/service.py` / migrations; tests use fake rows.

---

### A3 — Persist snapshot as `WikiPage` (optional but spec-aligned)

**Files:** `wiki/compilation_snapshot.py` (add `persist_wiki_snapshot_pages` helper) or `wiki/service.py` private method

- [x] **Step A3.1 — Test that persist writes MERGE for snapshot path**

Use existing `persist_wiki_pages` contract from the graph store. Implement `_persist_compilation_snapshot` in `WikiService` that maps markdown to `path` values:

- Single: `wiki_snapshot.md` with `page_type: index` (or `PageType.INDEX` from `wiki/models.py`).
- Layered: `wiki_snapshot.md` = index, `wiki_snapshot_modules/{mod}.md` = sub-snapshots.

**Command:** `pytest tests/wiki/test_compilation_snapshot_persist.py -q`

(Implement test with a mock `persist_wiki_pages` capturing dicts passed.)

- [x] **Step A3.2 — Wire `generate()` and `generate_stream_events()` after `_persist_pages_to_graph`**

In `wiki/service.py`, after successful `await self._persist_pages_to_graph(...)` (and the same for stream path after persist), if `self._wiki_cfg.snapshot_enabled` and `self._store`:

```python
# Pseudocode — exact placement in file after persist block
# asyncio.create_task(self._run_compilation_snapshot(...))  # or await if you want blocking
```

Prefer **`await self._run_compilation_snapshot(business_id, repository)`** for correctness before returning HTTP 200; for stream, run once after all pages + persist.

Full snippet for a private method:

```python
async def _run_compilation_snapshot(self, business_id: str, repository: str) -> None:
    if not getattr(self._wiki_cfg, "snapshot_enabled", True):
        return
    if self._store is None or not hasattr(self._store, "execute_query"):
        return
    from wiki.compilation_snapshot import WikiCompilationSnapshot

    snap = WikiCompilationSnapshot(self._store, self._wiki_cfg)
    # Implement persist via persist_wiki_pages with synthetic WikiPage dicts; see A3.1
```

- [x] **Step A3.3 — `generate_incremental`**

At end of `generate_incremental` in `wiki/service.py`, if `pages_regenerated > 0` and `snapshot_enabled`, call `await self._run_compilation_snapshot("default", repository)`.

**File note:** The spec also listed `wiki/incremental.py` — the HTTP ingest path uses `generate_incremental` on `WikiService`; only that needs the snapshot refresh unless a separate `WikiIncrementalUpdater` path also persists pages.

- [x] **Command:** `pytest tests/wiki/test_kb_wiki_pipeline.py -q` (extend or add integration test with mocked store)

---

### A4 — MCP: `wiki_get_snapshot`

**Files:**

- `api/mcp_wiki_server.py` — add to `TOOL_DEFINITIONS` + `_handle_wiki_get_snapshot`
- `wiki/mcp_tools.py` — add to `WIKI_MCP_TOOLS_MANIFEST` + `handle_wiki_get_snapshot` on `WikiMCPHandler`
- `api/mcp_server.py` — register handler in the wiki tool map (search for `wiki_get_domain_overview`)
- `tests/wiki/mcp/test_mcp_business_wiki.py` or new `tests/wiki/mcp/test_wiki_get_snapshot.py`

- [x] **Step A4.1 — Failing test: manifest includes tool**

```python
def test_wiki_get_snapshot_in_manifests():
    from api.mcp_wiki_server import TOOL_DEFINITIONS
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST

    t1 = {d["name"] for d in TOOL_DEFINITIONS}
    t2 = {d["name"] for d in WIKI_MCP_TOOLS_MANIFEST}
    assert "wiki_get_snapshot" in t1
    assert "wiki_get_snapshot" in t2
```

- [x] **Step A4.2 — Implement handlers**

`MCPWikiServer` must accept `CompilationSnapshot` or `WikiService` or raw graph — minimal: pass `wiki_store` and call `WikiCompilationSnapshot(wiki_store, settings.wiki).generate(...)`.

`api/mcp_wiki_server.py` extensions (complete handler sketch):

```python
async def _handle_wiki_get_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
    repo = str(args.get("repository", "")).strip()
    if not repo:
        return {"error": "repository required"}
    if self._wiki_store is None:
        return {"error": "Wiki store not configured"}
    from config import get_settings
    from wiki.compilation_snapshot import WikiCompilationSnapshot

    settings = get_settings()
    snap = WikiCompilationSnapshot(self._wiki_store, settings.wiki)
    try:
        md = await snap.generate("default", repo)
    except Exception as exc:
        return {"error": str(exc)}
    return {"repository": repo, "format": "markdown", "content": md}
```

Constructor of `MCPWikiServer` may need `settings: Settings` injected in `wiki/bootstrap.py`.

- [x] **Step A4.3 — Wire bootstrap**

`wiki/bootstrap.py`: when constructing `MCPWikiServer(...)`, pass `settings` (or a snapshot-only wrapper).

**Command:** `pytest tests/wiki/mcp/ -q`

---

## Task Group B: AGENTS.md Enhancement

**Positioning (document in file header and PR):**

- **AGENTS.md** — how to use MCP/HTTP tools (`wiki_search`, `wiki_qa`, …) and where to look next.
- **Compilation snapshot** — authoritative map of *what* is in the KB (read via `wiki_get_snapshot` or `wiki_snapshot.md` in the graph).

### B1 — Extend `AgentsMdGenerator`

**Files:** `wiki/agents_md_generator.py`, `tests/wiki/test_agents_md_generator.py` (create if missing)

- [x] **Step B1.1 — Test: section "Knowledge at a glance" with counts**

```python
import pytest
from wiki.agents_md_generator import AgentsMdGenerator


class _R:
    def __init__(self, data):
        self.data = data


class _G:
    def __init__(self, page_rows, stats_rows):
        self._page_rows = page_rows
        self._stats = stats_rows
        self.queries: list = []

    async def execute_query(self, cypher, params=None):
        self.queries.append((cypher, params or {}))
        if "count(wp)" in cypher or "avg(" in cypher:
            return _R(self._stats)
        return _R(self._page_rows)


@pytest.mark.asyncio
async def test_agents_includes_knowledge_map_pointer():
    pages = [
        {"title": "A", "page_path": "m/x.md", "type": "module_overview", "avg_conf": 0.8},
    ]
    stats = [{"n": 1, "avg_conf": 0.8, "stale": 0}]
    g = _G(pages, stats)
    gen = AgentsMdGenerator(g)
    md = await gen.generate("r1", "default")
    assert "Knowledge at a glance" in md
    assert "wiki_get_snapshot" in md
    assert "How to use tools" in md or "How to Use" in md
```

- [x] **Step B1.2 — Complete implementation**

`wiki/agents_md_generator.py` — keep existing list of pages, add a query for aggregates (COUNT, AVG confidence, optional stale if property exists), add sections:

1. `## Knowledge at a glance` — page count, mean confidence, pointer: “For a full map of pages and cross-refs, call MCP tool `wiki_get_snapshot` with this repository (or read `wiki_snapshot.md` in exports).”
2. `## How to use tools` (rename from "How to Use" for clarity) — unchanged text + one line separating from snapshot.
3. Do **not** inline the full snapshot body (avoids token blowup and duplicating Group A).

```python
# Fragment — full merged file in implementation
# ... after existing pages_q, add optional stats query matching your graph schema ...
```

- [x] **Command:** `pytest tests/wiki/test_agents_md_generator.py -q`

### B2 — Call site (if any) for `AgentsMdGenerator`

Search for `AgentsMdGenerator` in repo; update git export or admin route to regenerate after snapshot if there is a single writer.

**Grep command:** `rg "AgentsMdGenerator" /Users/earthchen/ai-work/agent-work/knowledge-base-service`

### B3 — (Optional) React: tooltip copy in feedback UI

Only if a component references AGENTS: align strings — **skip** if no user-facing string.

**Command (frontend):** `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm test --run` (when applicable)

---

## Task Group C: Feedback-Driven Regeneration (`wiki/feedback_loop.py` + API + config)

### C1 — Config (feedback regen + cooldown)

**Files:** `config.py` (`WikiConfig`), `tests/wiki/test_compilation_snapshot_config.py` (rename to `test_wiki_phase1_config.py` or add asserts)

- [x] **Step C1.1 — Add fields**

```python
feedback_regen_enabled: bool = True
feedback_regen_threshold: int = 3
feedback_regen_critical_immediate: bool = True
feedback_regen_token_multiplier: float = 1.5
feedback_regen_batch_token_multiplier: float = 1.2
feedback_regen_cooldown_hours: int = 24
```

Env: `WIKI__FEEDBACK_REGEN_COOLDOWN_HOURS` (default 24) per review. All of the above use the existing `WIKI__` nested env prefix from `Settings`.

- [x] **Step C1.2 — Test defaults**

```python
def test_feedback_regen_cooldown_default():
    from config import Settings
    s = Settings()
    assert s.wiki.feedback_regen_cooldown_hours == 24
```

**Command:** `pytest tests/wiki/test_wiki_phase1_config.py -q`

---

### C2 — API: optional severity + persist

**Files:** `api/models/wiki_models.py`, `api/routes/wiki_feedback_routes.py`, `store/wiki_feedback_store.py` (add optional property on `WikiFeedback` if needed)

- [x] **Step C2.1 — Extend `WikiPageFeedbackBody`**

```python
from typing import Literal
from typing_extensions import NotRequired  # or Python 3.10+ with typed dict — prefer Literal field

# In WikiPageFeedbackBody
severity: Literal["normal", "critical"] = "normal"
```

- [x] **Step C2.2 — Pass severity into Cypher** (optional `severity` on node)

`WikiFeedbackStore.persist_feedback` add `severity: str = "normal"`.

- [x] **Step C2.3 — Test route**

`tests/api/test_wiki_feedback_regen.py`:

```python
def test_post_feedback_accepts_severity(client):
    # use TestClient, POST /api/v1/wiki/pages/.../feedback with body {"rating": "down", "severity": "critical"}
    ...
```

**Command:** `pytest tests/api/test_wiki_feedback_regen.py -q`

---

### C3 — `wiki/feedback_loop.py`

- [x] **Step C3.1 — Unit test: threshold and cooldown**

`tests/wiki/test_feedback_loop.py`:

```python
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.feedback_loop import FeedbackDrivenRegeneration

@pytest.mark.asyncio
async def test_queues_when_down_count_reaches_threshold():
    store = MagicMock()
    store.execute_query = AsyncMock(side_effect=[
        # last regen
        _FakeResult([{"ts": 0.0}]),
        # down count
        _FakeResult([{"c": 3}]),
    ])
    # ... build FeedbackDrivenRegeneration, call on_feedback, assert _queue_regeneration called
```

(Provide `_FakeResult` matching your graph return shape.)

- [x] **Step C3.2 — Complete implementation** `wiki/feedback_loop.py`

```python
"""Feedback-driven wiki regeneration with threshold, critical path, and cooldown."""
from __future__ import annotations

import time
from typing import Any, Callable, Awaitable, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class FeedbackDrivenRegeneration:
    def __init__(
        self,
        graph: _GraphPort,
        wiki_config: Any,
        enqueue_regenerate: Callable[[str, str, float], Awaitable[None]],
    ) -> None:
        self._graph = graph
        self._cfg = wiki_config
        self._enqueue = enqueue_regenerate

    def _cooldown_ok(self, last_ts: float | None) -> bool:
        h = int(getattr(self._cfg, "feedback_regen_cooldown_hours", 24))
        if last_ts is None:
            return True
        return (time.time() - last_ts) >= h * 3600

    async def on_feedback(
        self,
        page_uid: str,
        business_id: str,
        rating: str,
        *,
        severity: str = "normal",
    ) -> dict[str, Any]:
        if not getattr(self._cfg, "feedback_regen_enabled", True):
            return {"action": "noop", "reason": "disabled"}
        if rating != "down":
            return {"action": "recorded", "regenerate": False}

        last = await self._last_regen_ts(page_uid, business_id)
        if not self._cooldown_ok(last):
            return {"action": "skipped", "reason": "cooldown"}

        if severity == "critical" and getattr(
            self._cfg, "feedback_regen_critical_immediate", True
        ):
            mult = float(getattr(self._cfg, "feedback_regen_token_multiplier", 1.5))
            await self._enqueue(page_uid, "high", mult)
            await self._mark_regen(page_uid, business_id)
            return {"action": "queued", "priority": "high", "token_multiplier": mult}

        n_down = await self._count_negative(page_uid, business_id)
        thr = int(getattr(self._cfg, "feedback_regen_threshold", 3))
        if n_down >= thr:
            mult = float(getattr(self._cfg, "feedback_regen_batch_token_multiplier", 1.2))
            await self._enqueue(page_uid, "normal", mult)
            await self._mark_regen(page_uid, business_id)
            return {"action": "queued", "priority": "normal", "token_multiplier": mult}
        return {"action": "recorded", "regenerate": False}

    async def _count_negative(self, page_uid: str, business_id: str) -> int:
        q = (
            "MATCH (f:WikiFeedback {page_uid: $p, business_id: $b, rating: 'down'}) "
            "RETURN count(f) AS c"
        )
        r = await self._graph.execute_query(q, {"p": page_uid, "b": business_id})
        rows = getattr(r, "data", []) or []
        if rows and isinstance(rows[0], dict):
            return int(rows[0].get("c") or 0)
        return 0

    async def _last_regen_ts(self, page_uid: str, business_id: str) -> float | None:
        q = (
            "MATCH (wp:WikiPage) WHERE wp.uid = $uid "
            "RETURN coalesce(wp.last_feedback_regen_at, null) AS ts"
        )
        r = await self._graph.execute_query(q, {"uid": page_uid})
        rows = getattr(r, "data", []) or []
        if not rows or not isinstance(rows[0], dict):
            return None
        ts = rows[0].get("ts")
        return float(ts) if ts is not None else None

    async def _mark_regen(self, page_uid: str, business_id: str) -> None:
        q = (
            "MATCH (wp:WikiPage) WHERE wp.uid = $uid "
            "SET wp.last_feedback_regen_at = $ts"
        )
        await self._graph.execute_query(q, {"uid": page_uid, "ts": time.time()})
```

---

### C4 — Enqueue: connect to `WikiService.generate` / `WikiTaskRegistry`

- [x] **Step C4.1 — Implement `enqueue_regenerate` in `api/routes/wiki_shared.py` or `wiki/bootstrap`**

`enqueue_regenerate(page_uid, priority, token_mult)` should:

1. Parse `page_uid` → `repository` and scope from existing conventions (`WikiPage:repo:path`).
2. `asyncio.create_task` running `wiki_service.generate(repo, scope, "structure", "json", ...)` with semaphore from `get_wiki_generation_sem`.
3. Pass token multiplier into `WikiService` (requires a new optional parameter on `generate()` → composer).

**Files:** `wiki/service.py` (add optional `regeneration_token_multiplier: float | None = None` that scales code budgets in `_budget_for_tier` when set), `wiki/composer.py` (thread through if needed).

- [x] **Step C4.2 — `post_wiki_page_feedback` calls feedback loop**

`api/routes/wiki_feedback_routes.py`:

```python
async def post_wiki_page_feedback(..., request: Request, body: WikiPageFeedbackBody):
    uid = await fb.persist_feedback(..., severity=body.severity)
    loop: FeedbackDrivenRegeneration | None = getattr(
        request.app.state, "wiki_feedback_regen", None
    )
    if loop:
        out = await loop.on_feedback(decoded, body.business_id, body.rating, severity=body.severity)
    else:
        out = {}
    return {"uid": uid, "page_uid": decoded, "business_id": body.business_id, "regen": out}
```

- [x] **Step C4.3 — `wiki/bootstrap.py`:** `app.state.wiki_feedback_regen = FeedbackDrivenRegeneration(...)` with graph + settings + bound enqueue.

**Command:** `pytest tests/ -q --tb=short -k "feedback"`

---

## Verification (full suite)

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
pytest -q
ruff check wiki api tests
mypy wiki/compilation_snapshot.py wiki/feedback_loop.py  # if mypy in CI
```

---

## Dependency graph (parallelization)

| Group | Depends on | Can start in parallel with |
|-------|------------|----------------------------|
| A | Config fields A1 | — |
| B | A2 query shapes (or stub stats in B1) | C1 (config) |
| C | C1, graph property `last_feedback_regen_at` (migration optional: first SET creates) | A after graph contract stable |

**Suggested order:** A1 → A2 → A3 → A4 → B1 → C1 → C2 → C3 → C4 → final pytest.

---

## Checklist: files touched (expected)

| File | Action |
|------|--------|
| `config.py` | Add snapshot + feedback regen + cooldown + optional batch multiplier |
| `wiki/compilation_snapshot.py` | Create |
| `wiki/agents_md_generator.py` | Enhance sections; clarify tool vs snapshot |
| `wiki/feedback_loop.py` | Create |
| `wiki/service.py` | Snapshot after persist; incremental; optional regen budget |
| `wiki/bootstrap.py` | MCP settings + `FeedbackDrivenRegeneration` |
| `api/mcp_wiki_server.py` | `wiki_get_snapshot` |
| `wiki/mcp_tools.py` | tool + handler |
| `api/mcp_server.py` | dispatch |
| `api/models/wiki_models.py` | `severity` on feedback body |
| `api/routes/wiki_feedback_routes.py` | call feedback loop |
| `store/wiki_feedback_store.py` | optional `severity` on CREATE |
| `tests/wiki/test_compilation_snapshot.py` | Create |
| `tests/wiki/test_agents_md_generator.py` | Create/extend |
| `tests/wiki/test_feedback_loop.py` | Create |
| `tests/wiki/mcp/test_wiki_get_snapshot.py` | Create |
| `tests/api/test_wiki_feedback_regen.py` | Create |

---

## Notes for implementers

1. If `confidence` or `wikilinks` are not on `WikiPage` in production schema, add properties in `persist_wiki_pages` or simplify Cypher in `WikiCompilationSnapshot._fetch_pages` to only use existing columns (tests stay on fakes).
2. **Cypher compatibility:** `coalesce(wp.wikilinks, [])` may require a default; use `apoc` only if already a dependency; else omit wikilinks and cross-ref section.
3. **Group A vs B:** Keep AGENTS.md as a **pointer** to snapshot rather than duplicating the layered markdown.
4. **Token multiplier:** Critical path uses `feedback_regen_token_multiplier` (default 1.5); threshold path uses `feedback_regen_batch_token_multiplier` (default 1.2).

---

## Supplementary: Deficiencies discovered during 2026-04-27 full audit

The following issues were identified during a comprehensive code/doc review and LLM Wiki ecosystem comparison. They should be addressed alongside or immediately after Phase 1 tasks:

### S1 — Enable `supersession_tracking_enabled` (default `True`)

LLM Wiki v2 identifies supersession as a core knowledge lifecycle feature. KBS has `supersession_tracking_enabled=False` in `WikiConfig`. Change default to `True` in `config.py` after Phase 1 compilation snapshot is working, so that superseded claims are visible in snapshot output.

- [ ] **Step S1.1** — Change `supersession_tracking_enabled` default from `False` to `True` in `WikiConfig`
- [ ] **Step S1.2** — Add test in `tests/test_wiki_config_defaults.py` verifying new default
- [ ] **Step S1.3** — Update `docs/DEPLOYMENT.md` table for `WIKI__SUPERSESSION_TRACKING_ENABLED`

### S2 — Implement real SSE event bus (replace placeholder)

`/api/v1/wiki/events` only sends keepalives. Phase 1 feedback loop needs real event push (lint results, regen progress, ingest status) to frontend.

- [ ] **Step S2.1** — Create `wiki/event_bus.py` with `WikiEventBus` (asyncio broadcast, typed events)
- [ ] **Step S2.2** — Wire `WikiEventBus` into `bootstrap_wiki` and `wiki_feedback_routes.py` SSE endpoint
- [ ] **Step S2.3** — Emit events from `run_lint`, `AutoHealer.heal`, `FeedbackDrivenRegeneration`, ingest
- [ ] **Step S2.4** — Frontend: update `useWikiEvents` to parse typed events and trigger query invalidation

### S3 — Frontend code quality fixes

- [ ] **Step S3.1** — Fix i18n hardcoded strings in `WikiPageFeedback` ("Was this helpful?", etc.)
- [ ] **Step S3.2** — Deduplicate `invalidateWikiQueriesForBusiness` (keep one in `hooks/`, remove from `WikiShell.tsx`)
- [ ] **Step S3.3** — Deduplicate `getCurrentBusiness` (single export from `BusinessContext.tsx`, update `api/client.ts`)
- [ ] **Step S3.4** — Remove legacy `useWikiPage` if `useWikiPageByPath` is the canonical hook

---

_End of plan._
