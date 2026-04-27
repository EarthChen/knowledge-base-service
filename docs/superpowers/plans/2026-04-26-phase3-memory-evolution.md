# Phase 3: Memory Evolution System — Implementation Plan

> **For agentic workers:** Implement task-by-task. Each task follows **TDD:** failing test → implement → `uv run pytest` passes → `git commit` (one logical commit per task or per task-step as noted).

**Goal:** Add memory consolidation tiers (0–3), Ebbinghaus-style forgetting, and a YAML schema validation layer; integrate both into the memory loop, graph persistence, wiki lint, and the dashboard, behind feature flags in `WikiConfig`.

**Architecture:** Extend existing `:WikiQA` nodes in FalkorDB with tiered memory fields (same label preserves `db.idx.vector` on `WikiQA.embedding`). Introduce `MemoryTierManager` for promotion/expiration during lint and on access. `MemoryLoop` becomes tier- and retention-aware when `memory_tiers_enabled` is true. Forgetting is pure calculation + status flags (`faded` / `archived`), never destructive deletes. Schema validation is an optional lint pass using `wiki/schema.yaml` (default) or `WikiConfig.schema_path`.

**Tech Stack:** Python 3.12+ (`uv`, matches root `pyproject.toml`), FalkorDB/Cypher, Pydantic (`config.py`), pytest; frontend React + Vitest + `pnpm`.

**Spec source of truth (promotion, forgetting, flags):** `docs/superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md` §4 (Phase 3) and §8 (feature flags). Promotion thresholds must match the design **exactly** (see “Authoritative rules” below).

### Authoritative promotion rules (from spec)

| Transition | When | Action |
|------------|------|--------|
| Tier 0 → 1 or expire | `tier == 0` and **age &gt; 24h** | If `access_count >= 2` → `promote(tier=1)`; **else** → `expire()` |
| Tier 1 → 2 or expire | `tier == 1` and **age &gt; 7d** | If `confirmation_count >= 3` → `promote(tier=2)`; **else** → `expire()` |
| Tier 2 → 3 | `tier == 2` | If `access_count >= 10` **and** `confidence >= 0.8` → `promote(tier=3)` |

**Ages** are measured from `created_at` (or `promoted_at` when redefining “episode” — **decision: use `created_at` for tier-0/1 window checks**; document in `memory_tiers.py` docstring). If product wants “age since promotion”, switch consistently in one place.

**Forgetting (from spec):** `retention(t) = e^(-t / S)`; initial `S = 7.0` (`WikiConfig.forgetting_initial_stability`); on each access/confirmation `S = S * 1.5`. Retention &lt; 0.3 → deprioritize (“faded”); &lt; 0.1 → “archived”.

---

## 2. File structure mapping

| Area | New / changed paths |
|------|---------------------|
| Domain & tiers | `knowledge-base-service/wiki/memory_tiers.py` (new) |
| Forgetting | `knowledge-base-service/wiki/forgetting.py` (new) |
| Schema | `knowledge-base-service/wiki/schema.yaml` (new), `knowledge-base-service/wiki/schema_validator.py` (new) |
| Memory loop | `knowledge-base-service/wiki/memory_loop.py` (modify) |
| Graph / QA store | `knowledge-base-service/store/wiki_qa_store.py` (modify), `knowledge-base-service/store/schema.py` (update comment / `NodeLabel` if second label) |
| Lint | `knowledge-base-service/wiki/lint.py` (modify) |
| Config | `knowledge-base-service/config.py` — `WikiConfig` (modify) |
| API wiring | `knowledge-base-service/main.py` (pass settings into `MemoryLoop` / lint if needed) |
| Tests | `knowledge-base-service/tests/wiki/test_memory_tiers.py`, `test_forgetting.py`, `test_schema_validator.py` (new); extend `test_memory_loop.py` |
| Frontend | `knowledge-base-service/dashboard/src/components/wiki/MemoryTierIndicator.tsx` (new), `__tests__/MemoryTierIndicator.test.tsx` (new) |
| i18n (optional) | `knowledge-base-service/dashboard/src/i18n/...` if labels are user-visible |

**Graph convention:** Keep node label `WikiQA` for vector index compatibility; **optionally** add `MemoryNode` as a second label (`:WikiQA:MemoryNode`) only if queries benefit — otherwise a single label with all properties is enough. This plan standardizes on **extended `WikiQA` properties** matching the spec’s `MemoryNode` field set.

---

## 3. SP6 — Memory Consolidation Tiers

### Task 1: MemoryNode data model (tier 0–3)

**Files:**
- New: `wiki/memory_tiers.py` (dataclasses, enums, parsing)
- New: `tests/wiki/test_memory_tiers.py`
- Modify: `store/wiki_qa_store.py` — extend `CREATE` and `search` / `list` `RETURN` clauses when properties exist (see Task 3–4; minimal stub here is acceptable if tests mock store)

- [ ] **Failing test — MemoryNode + tier enum**

```python
# tests/wiki/test_memory_tiers.py
from __future__ import annotations

from wiki.memory_tiers import MemoryNode, MemoryTier


def test_memory_tier_value_range():
    assert MemoryTier.WORKING.value == 0
    assert MemoryTier.EPISODIC.value == 1
    assert MemoryTier.SEMANTIC.value == 2
    assert MemoryTier.PROCEDURAL.value == 3


def test_memory_node_defaults():
    n = MemoryNode(
        uid="WikiQA:default:x",
        tier=MemoryTier.WORKING,
        content="Q\nA",
        entity_name="",
        repository="r1",
    )
    assert n.access_count == 0
    assert n.confirmation_count == 0
    assert n.stability_factor == 7.0  # align with Phase 3 forgetting default until Task SP7-1
```

- [ ] **Run (expect fail):** `cd knowledge-base-service && uv run pytest tests/wiki/test_memory_tiers.py -v`

- [ ] **Implement**

```python
# wiki/memory_tiers.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class MemoryTier(IntEnum):
    WORKING = 0
    EPISODIC = 1
    SEMANTIC = 2
    PROCEDURAL = 3


@dataclass
class MemoryNode:
    """In-graph memory (persisted as :WikiQA with these fields; see spec MemoryNode)."""

    uid: str
    tier: MemoryTier
    content: str
    entity_name: str
    repository: str
    access_count: int = 0
    confirmation_count: int = 0
    last_accessed: str | None = None
    created_at: str = ""
    promoted_at: str | None = None
    stability_factor: float = 7.0
    confidence: float = 0.0
    # Phase 2 integration: use WikiPage.confidence when linking; 0.0 = unknown
    status: str = "active"  # active | expired | archived | faded — wire in SP6/7

    @staticmethod
    def from_wiki_qa_row(row: dict[str, Any]) -> "MemoryNode":
        raise NotImplementedError  # implement in same commit after tests require behavior
```

- [ ] **Run (expect pass):** `uv run pytest tests/wiki/test_memory_tiers.py -v`
- [ ] **Commit:** `git add wiki/memory_tiers.py tests/wiki/test_memory_tiers.py && git commit -m "feat(wiki): add MemoryNode and MemoryTier data model"`

- [ ] **Follow-up test + impl — from_wiki_qa_row**

Add test for `from_wiki_qa_row` mapping `question`+`answer` → `content`, int tier default 1 for migrations. Implement `from_wiki_qa_row`. Commit.

---

### Task 2: MemoryTierManager promotion logic

**Files:**
- `wiki/memory_tiers.py` — add `MemoryTierManager` class
- `tests/wiki/test_memory_tiers.py` — table-driven tests for exact spec rules

- [ ] **Failing tests — promotion and expire**

```python
# tests/wiki/test_memory_tiers.py (add)
from datetime import datetime, timedelta, timezone

import pytest
from wiki.memory_tiers import MemoryNode, MemoryTier, MemoryTierManager


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def mgr() -> MemoryTierManager:
    return MemoryTierManager()


def test_tier0_after_24h_access2_promotes_to_t1(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(hours=25)
    n = MemoryNode(
        uid="u1", tier=MemoryTier.WORKING, content="c", entity_name="e", repository="r",
        access_count=2, created_at=_iso(created), confidence=0.0,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.tier == MemoryTier.EPISODIC


def test_tier0_after_24h_low_access_expires(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(hours=30)
    n = MemoryNode(
        uid="u1", tier=MemoryTier.WORKING, content="c", entity_name="e", repository="r",
        access_count=1, created_at=_iso(created), confidence=0.0,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.status == "expired"


def test_tier1_after_7d_confirm3_promotes_to_t2(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=8)
    n = MemoryNode(
        uid="u1", tier=MemoryTier.EPISODIC, content="c", entity_name="e", repository="r",
        confirmation_count=3, access_count=1, created_at=_iso(created), confidence=0.5,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.tier == MemoryTier.SEMANTIC


def test_tier1_after_7d_low_confirm_expires(mgr: MemoryTierManager) -> None:
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    n = MemoryNode(
        uid="u1", tier=MemoryTier.EPISODIC, content="c", entity_name="e", repository="r",
        confirmation_count=2, access_count=5, created_at=_iso(created), confidence=0.9,
    )
    out = mgr.apply_promotion_rules(n, now=now)
    assert out.status == "expired"


def test_tier2_to_t3_requires_access_10_and_conf_08(mgr: MemoryTierManager) -> None:
    n = MemoryNode(
        uid="u1", tier=MemoryTier.SEMANTIC, content="c", entity_name="e", repository="r",
        access_count=10, confirmation_count=3, created_at="2020-01-01T00:00:00Z", confidence=0.8,
    )
    out = mgr.apply_promotion_rules(n, now=datetime.now(timezone.utc))
    assert out.tier == MemoryTier.PROCEDURAL
```

- [ ] **Run (expect fail):** `uv run pytest tests/wiki/test_memory_tiers.py -v`

- [ ] **Implement (exact spec order)**

```python
# wiki/memory_tiers.py (add)
from dataclasses import replace
from datetime import datetime, timedelta, timezone


def _parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class MemoryTierManager:
    def apply_promotion_rules(self, node: MemoryNode, *, now: datetime | None = None) -> MemoryNode:
        if now is None:
            now = datetime.now(timezone.utc)
        n = node
        created = _parse_iso(n.created_at) if n.created_at else now
        age = now - created

        if n.tier == MemoryTier.WORKING:
            if age > timedelta(hours=24):
                if n.access_count >= 2:
                    return replace(n, tier=MemoryTier.EPISODIC, promoted_at=_iso_utc(now))
                return replace(n, status="expired")
        elif n.tier == MemoryTier.EPISODIC:
            if age > timedelta(days=7):
                if n.confirmation_count >= 3:
                    return replace(n, tier=MemoryTier.SEMANTIC, promoted_at=_iso_utc(now))
                return replace(n, status="expired")
        elif n.tier == MemoryTier.SEMANTIC:
            if n.access_count >= 10 and n.confidence >= 0.8:
                return replace(n, tier=MemoryTier.PROCEDURAL, promoted_at=_iso_utc(now))
        return n
```

(Cross-check `_iso_utc` output with existing graph timestamps, e.g. `memory_loop.py` uses `time.strftime` + `time.gmtime` for `created_at`.)

- [ ] **Run (expect pass):** `uv run pytest tests/wiki/test_memory_tiers.py -v`
- [ ] **Commit:** `git commit -am "feat(wiki): add MemoryTierManager with spec promotion rules"`

---

### Task 3: Tier-aware retrieval in MemoryLoop

**Files:**
- `wiki/memory_loop.py` — add `MemoryEntry` fields (`tier`, `uid`, `status`); add optional `WikiConfig` or booleans; filter/rank
- `store/wiki_qa_store.py` — return `tier`, `status`, `confidence` in `search_wiki_qa` / `list_wiki_qa`
- `config.py` — `memory_tiers_enabled: bool = False`
- `tests/wiki/test_memory_loop.py` — new tests with mocked rows

- [ ] **Failing test — deprioritize expired / faded when flag on**

```python
# tests/wiki/test_memory_loop.py (add)
@pytest.mark.asyncio
async def test_get_relevant_memories_skips_expired_when_tiers_enabled() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(return_value=MagicMock(data=[
        {
            "question": "Q1", "answer": "A1", "source_pages": "[]",
            "quality_score": 0.9, "created_at": "2026-01-01T00:00:00Z",
            "memory_status": "expired", "tier": 1,
        },
        {
            "question": "Q2", "answer": "A2", "source_pages": "[]",
            "quality_score": 0.5, "created_at": "2026-01-02T00:00:00Z",
            "memory_status": "active", "tier": 2,
        },
    ]))

    async def embed(_: str) -> list[float]:
        return [1.0]

    ml = MemoryLoop(WikiStore(base), embed, memory_tiers_enabled=True)
    out = await ml.get_relevant_memories("t", limit=5)
    assert len(out) == 1
    assert out[0].question == "Q2"
```

- [ ] **Implement** — extend `search_wiki_qa` Cypher to `RETURN` optional `q.memory_status AS memory_status, q.tier AS tier, ...` (default `active` and tier `1` in application layer when missing). `MemoryLoop.get_relevant_memories` filters `expired` and optionally down-ranks `faded` to the end.
- [ ] **Run:** `uv run pytest tests/wiki/test_memory_loop.py -v`
- [ ] **Commit**

---

### Task 4: Memory migration (flat → tiered)

**Files:**
- `store/wiki_qa_store.py` — Cypher: `SET q.tier = 1, q.access_count = coalesce(q.access_count, 1), q.memory_status = 'active'` for nodes missing `tier`
- `wiki/migrate_memory_tiers.py` (optional one-shot module) *or* migration inside `MemoryTierManager.run_backfill` called from lint once
- `tests/wiki/test_memory_migration.py` (new) — Cypher string assertions or mock execute_query

- [ ] **Failing test**

```python
# tests/wiki/test_memory_migration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from store.wiki_store import WikiStore


@pytest.mark.asyncio
async def test_migrate_flat_wiki_qa_sets_tier1_and_access1() -> None:
    from wiki.migrate_memory_tiers import migrate_flat_wiki_qa_to_tiered  # to be created

    base = MagicMock()
    base.execute_query = AsyncMock(return_value=MagicMock(data=[{"updated": 3}]))
    n = await migrate_flat_wiki_qa_to_tiered(WikiStore(base), business_id="biz")
    assert n == 3
    cypher = base.execute_query.call_args[0][0].lower()
    assert "wikiqa" in cypher
    assert "tier" in cypher
    assert "access_count" in cypher
```

- [ ] **Implement** migration per spec §6: *Existing flat MemoryLoop entries → Tier 1 (Episodic), `access_count=1`.*

```python
# wiki/migrate_memory_tiers.py
from __future__ import annotations
from store.wiki_store import WikiStore


async def migrate_flat_wiki_qa_to_tiered(store: WikiStore, *, business_id: str | None = None) -> int:
    """One-shot: nodes without tier get tier=1 and access_count=1."""
    q = """
    MATCH (q:WikiQA)
    WHERE $business_id IS NULL OR q.business_id = $business_id
    AND q.tier IS NULL
    SET q.tier = 1, q.access_count = coalesce(q.access_count, 1), q.memory_status = coalesce(q.memory_status, 'active')
    RETURN count(q) AS updated
    """
    r = await store.execute_query(q, {"business_id": business_id})
    row = (r.data or [{}])[0]
    return int(row.get("updated", 0) or 0)
```

- [ ] **Run + commit**

---

### Task 5: MemoryTierIndicator frontend component

**Files:**
- `dashboard/src/components/wiki/MemoryTierIndicator.tsx`
- `dashboard/src/components/wiki/__tests__/MemoryTierIndicator.test.tsx`

- [ ] **Failing test (Vitest)**

```tsx
// dashboard/src/components/wiki/__tests__/MemoryTierIndicator.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import MemoryTierIndicator from "../MemoryTierIndicator";

describe("MemoryTierIndicator", () => {
  it("renders working tier label", () => {
    render(<MemoryTierIndicator tier={0} />);
    expect(screen.getByText(/working/i)).toBeInTheDocument();
  });
});
```

- [ ] **Implement** — small badge: tier 0–3 colors (e.g. slate / blue / amber / green), `aria-label` with tier name; no network calls.

```tsx
// dashboard/src/components/wiki/MemoryTierIndicator.tsx
const TIER_LABELS = ["Working", "Episodic", "Semantic", "Procedural"] as const;

export type Props = { tier: 0 | 1 | 2 | 3; className?: string };

export default function MemoryTierIndicator({ tier, className }: Props) {
  const label = TIER_LABELS[tier] ?? "Unknown";
  return (
    <span
      role="img"
      aria-label={`Memory tier: ${label}`}
      className={className}
      data-tier={tier}
    >
      {label}
    </span>
  );
}
```

- [ ] **Run:** `cd knowledge-base-service/dashboard && pnpm exec vitest run src/components/wiki/__tests__/MemoryTierIndicator.test.tsx`
- [ ] **Commit**

---

### Task 6: Feature flag (SP6)

**Files:**
- `config.py` — under `WikiConfig`:

```python
# Phase 3 (LLM Wiki v2 — Memory Evolution)
memory_tiers_enabled: bool = False
```

- Wire: `main.py` / `MemoryLoop` constructor reads `get_settings().wiki.memory_tiers_enabled` (pass explicit arg to `MemoryLoop(..., memory_tiers_enabled=...)`).
- **Test:** `tests/wiki/test_memory_loop.py` or `tests/test_config_wiki.py` assert default `False`.

- [ ] **Run:** `uv run pytest tests/wiki/test_memory_loop.py tests/ -k memory_tiers -q` (or targeted config test)
- [ ] **Commit**

---

## 4. SP7 — Forgetting Mechanism + Schema Layer

### Task 1: Forgetting calculator (Ebbinghaus formula, `initial_stability=7.0`)

**Files:**
- `wiki/forgetting.py` (new)
- `config.py` — `forgetting_initial_stability: float = 7.0`
- `tests/wiki/test_forgetting.py` (new)

- [ ] **Failing test**

```python
# tests/wiki/test_forgetting.py
from math import exp
import pytest
from wiki.forgetting import compute_retention, bump_stability


def test_retention_at_t_equals_zero_is_one() -> None:
    assert abs(compute_retention(t_days=0.0, stability=7.0) - 1.0) < 1e-9


def test_retention_matches_formula() -> None:
    t, S = 7.0, 7.0
    expected = exp(-t / S)
    assert abs(compute_retention(t, S) - expected) < 1e-12


def test_bump_stability_multiplies_by_1_5() -> None:
    assert bump_stability(4.0) == 6.0
```

- [ ] **Implement**

```python
# wiki/forgetting.py
from __future__ import annotations
from math import exp


def compute_retention(*, t_days: float, stability: float) -> float:
    """retention(t) = e^(-t / S) per design spec."""
    if stability <= 0:
        return 0.0
    return float(exp(-t_days / stability))


def bump_stability(s: float, factor: float = 1.5) -> float:
    return s * factor
```

- [ ] **Add tests for thresholds:** retention &lt; 0.3 → `"faded"`; &lt; 0.1 → `"archived"` helper `classify_retention(r: float) -> str`.
- [ ] **Run:** `uv run pytest tests/wiki/test_forgetting.py -v`
- [ ] **Commit**

---

### Task 2: Wire forgetting into lint

**Files:**
- `wiki/lint.py` — when `forgetting_enabled`, run batch query for `WikiQA` / memory nodes, compute retention from `last_accessed` and `stability_factor`, emit `LintIssue` category e.g. `memory_retention` severity `info` for faded, `warning` for archived; or **only** `SET` `memory_status` on graph + optional info issues (choose one and document; prefer: update graph in `WikiLintService` + light info lint).

- [ ] **Failing test** — `tests/wiki/test_lint_forgetting.py` with mocked store returning one stale node; expect issue or status update.

```python
# tests/wiki/test_lint_forgetting.py
@pytest.mark.asyncio
async def test_lint_marks_faded_retention() -> None:
    # construct WikiLintService with mock wiki_store returning WikiQA rows
    # call lint(...); assert issue category or execute_query was called with SET memory_status
    ...
```

- [ ] **Implement** + **Run:** `uv run pytest tests/wiki/test_lint_forgetting.py -v`
- [ ] **Commit**

---

### Task 3: Schema YAML definition (`wiki/schema.yaml`)

**Files:**
- `wiki/schema.yaml` (new) — default conventions for wiki pages (e.g. required front-matter keys, `page_type` enum, path patterns as regex strings).

**Example (minimal; expand to project needs):**

```yaml
# wiki/schema.yaml
version: 1
required_root_pages:
  - index.md
page_types:
  - guide
  - reference
  - overview
path_pattern: '^[a-z0-9./_-]+\\.md$'
```

- [ ] **Commit:** (docs-only) `git add wiki/schema.yaml && git commit -m "feat(wiki): add default wiki schema.yaml"`

---

### Task 4: `SchemaValidator` class

**Files:**
- `wiki/schema_validator.py` (new)
- `tests/wiki/test_schema_validator.py` (new)

- [ ] **Failing test**

```python
# tests/wiki/test_schema_validator.py
from pathlib import Path
from wiki.schema_validator import SchemaValidator


def test_rejects_path_not_matching_pattern(tmp_path: Path) -> None:
    yml = tmp_path / "s.yaml"
    yml.write_text("version: 1\npath_pattern: '^[a-z]+\\.md$'\n", encoding="utf-8")
    v = SchemaValidator.from_yaml_path(yml)
    errors = v.validate_page(path="Bad.md", content="# x", page_type="guide")
    assert errors
```

- [ ] **Implement**

```python
# wiki/schema_validator.py
from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass
import yaml


@dataclass
class SchemaValidator:
    path_pattern: re.Pattern[str]
    page_types: frozenset[str]
    required_root_pages: frozenset[str]

    @classmethod
    def from_yaml_path(cls, p: Path) -> "SchemaValidator":
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        pat = data.get("path_pattern", ".*")
        return cls(
            path_pattern=re.compile(pat),
            page_types=frozenset(data.get("page_types") or ()),
            required_root_pages=frozenset(data.get("required_root_pages") or ()),
        )

    def validate_page(self, *, path: str, content: str, page_type: str) -> list[str]:
        err: list[str] = []
        if not self.path_pattern.match(path):
            err.append("path: does not match path_pattern")
        if self.page_types and page_type not in self.page_types:
            err.append("page_type: not in allowed set")
        return err
```

(Use `pyyaml` if not present — add to `pyproject.toml` via `uv add pyyaml`.)

- [ ] **Run + commit**

---

### Task 5: Wire schema validation into lint

**Files:**
- `wiki/lint.py` — if `schema_validation_enabled` and resolved path exists, load `SchemaValidator` and for each `WikiPage` in repo, call `validate_page`.
- `config.py` — `schema_path: str = ""` (empty → use package default `wiki/schema.yaml` next to `schema_validator`).

- [ ] **Failing test** `tests/wiki/test_lint_schema.py` — page with bad path triggers `LintIssue` category `schema`.

- [ ] **Run:** `uv run pytest tests/wiki/test_lint_schema.py -v`
- [ ] **Commit**

---

### Task 6: Feature flag (SP7)

**Files:**
- `config.py`

```python
forgetting_enabled: bool = False
schema_validation_enabled: bool = False
# forgetting_initial_stability already added in Task 1; reuse for S initial on new nodes
schema_path: str = ""
```

- [ ] **Test:** `assert Settings().wiki.schema_path == ""` and flags default false in `tests/test_config.py` (create if missing).
- [ ] **Commit**

---

## 5. Dependency & ordering

1. **SP6 Task 1–2** before **Task 3** (data model + manager before loop).
2. **Task 4** can follow **Task 2**; run once per environment or from lint.
3. **SP7 Task 1** can parallelize with SP6; **Task 2** needs **Task 1** and `WikiQa` / memory fields.
4. **Task 3–4–5 (schema)** in order.
5. **Feature flags (6+6)** can land early but wire **only after** the guarded code exists.

## 6. Verification checklist (end of phase)

- [ ] `cd knowledge-base-service && uv run pytest` — full suite green
- [ ] `cd knowledge-base-service/dashboard && pnpm exec vitest run` — front tests green
- [ ] Grep: no promotion threshold literals diverging from this doc (single source: `MemoryTierManager`)
- [ ] Optional: `uv run ruff check` / `uv run mypy` if project uses them

---

*Plan file: `knowledge-base-service/docs/superpowers/plans/2026-04-26-phase3-memory-evolution.md`*
