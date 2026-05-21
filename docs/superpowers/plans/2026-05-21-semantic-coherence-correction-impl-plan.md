# LLM 语义一致性纠正层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-based semantic correction to the wiki domain decomposition pipeline, eliminating cross-parent misplacement and reducing domain fragmentation.

**Architecture:** Insert two new LLM review steps into `graph_driven_domain_decompose_node()`: Step 5.5 (module-level semantic correction) and Step 7.5 (domain-level merge review). Create a new `GraphSemanticCorrector` class. Also improve domain naming with used-names injection, adjust sub-domain splitting parameters, and raise orphan adoption threshold.

**Tech Stack:** Python 3.12+, LLMPort interface (OpenAI-compatible), structlog, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-21-semantic-coherence-correction-design.md`

---

### Task 1: Create `GraphSemanticCorrector` — Module-Level Correction

**Files:**
- Create: `wiki/graph_semantic_corrector.py`
- Test: `tests/wiki/test_graph_semantic_corrector.py`

- [ ] **Step 1: Write the failing test for `correct_module_assignments()`**

```python
# tests/wiki/test_graph_semantic_corrector.py
"""Tests for GraphSemanticCorrector."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.graph_semantic_corrector import GraphSemanticCorrector


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def corrector(mock_llm):
    return GraphSemanticCorrector(mock_llm)


@pytest.mark.asyncio
async def test_correct_module_assignments_moves_misplaced_module(corrector, mock_llm):
    """ClosedFriendTaskHandler should be moved from family-task to intimacy-mgmt."""
    domain_mapping = {
        "family-task": [("repo1", "FamilyTaskHandler"), ("repo1", "FamilyTaskValidator"), ("repo1", "ClosedFriendTaskHandler")],
        "intimacy-mgmt": [("repo1", "IntimacyService"), ("repo1", "IntimacyGiftHandler")],
    }
    domain_display_names = {"family-task": "家族任务管理", "intimacy-mgmt": "亲密关系管理"}
    module_paths = {
        "FamilyTaskHandler": "com/example/family/task/FamilyTaskHandler.java",
        "FamilyTaskValidator": "com/example/family/task/FamilyTaskValidator.java",
        "ClosedFriendTaskHandler": "com/example/closedfriend/task/ClosedFriendTaskHandler.java",
        "IntimacyService": "com/example/intimacy/IntimacyService.java",
        "IntimacyGiftHandler": "com/example/intimacy/gift/IntimacyGiftHandler.java",
    }

    mock_llm.generate.return_value = json.dumps({
        "moves": [
            {"module": "ClosedFriendTaskHandler", "from_domain": "family-task", "to_domain": "intimacy-mgmt", "reason": "ClosedFriend belongs to intimacy"}
        ]
    })

    result = await corrector.correct_module_assignments(
        domain_mapping, domain_display_names, module_paths, {}
    )

    assert ("repo1", "ClosedFriendTaskHandler") not in result["family-task"]
    assert ("repo1", "ClosedFriendTaskHandler") in result["intimacy-mgmt"]
    assert len(result["family-task"]) == 2
    assert len(result["intimacy-mgmt"]) == 3


@pytest.mark.asyncio
async def test_correct_no_moves_needed(corrector, mock_llm):
    """When LLM finds no misplacements, domain_mapping is unchanged."""
    domain_mapping = {
        "family": [("repo1", "FamilyService")],
    }
    mock_llm.generate.return_value = json.dumps({"moves": []})

    result = await corrector.correct_module_assignments(
        domain_mapping, {"family": "家族"}, {}, {}
    )

    assert result == domain_mapping


@pytest.mark.asyncio
async def test_correct_llm_failure_returns_original(corrector, mock_llm):
    """When LLM fails, return original domain_mapping unchanged."""
    domain_mapping = {
        "family": [("repo1", "FamilyService")],
    }
    mock_llm.generate.side_effect = Exception("LLM down")

    result = await corrector.correct_module_assignments(
        domain_mapping, {"family": "家族"}, {}, {}
    )

    assert result == domain_mapping


@pytest.mark.asyncio
async def test_correct_invalid_target_domain_skipped(corrector, mock_llm):
    """Moves targeting non-existent domains are skipped."""
    domain_mapping = {
        "family": [("repo1", "FamilyService"), ("repo1", "SomeModule")],
    }
    mock_llm.generate.return_value = json.dumps({
        "moves": [
            {"module": "SomeModule", "from_domain": "family", "to_domain": "nonexistent", "reason": "test"}
        ]
    })

    result = await corrector.correct_module_assignments(
        domain_mapping, {"family": "家族"}, {}, {}
    )

    assert ("repo1", "SomeModule") in result["family"]


@pytest.mark.asyncio
async def test_correct_move_cap_30_percent(corrector, mock_llm):
    """At most 30% of total modules can be moved in one correction."""
    modules = [(f"repo1", f"Module{i}") for i in range(10)]
    domain_mapping = {"domain-a": modules}
    moves = [{"module": f"Module{i}", "from_domain": "domain-a", "to_domain": "domain-b", "reason": "test"} for i in range(10)]
    mock_llm.generate.return_value = json.dumps({"moves": moves})

    result = await corrector.correct_module_assignments(
        {**domain_mapping, "domain-b": []},
        {"domain-a": "A", "domain-b": "B"},
        {},
        {},
    )

    moved = len([m for m in modules if m not in result.get("domain-a", [])])
    assert moved <= 3  # 30% of 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_graph_semantic_corrector.py -v`
Expected: FAIL with ImportError (module not found)

- [ ] **Step 3: Write minimal implementation**

```python
# wiki/graph_semantic_corrector.py
"""LLM-based semantic coherence correction for domain assignments."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

from core.log import get_logger
from wiki.json_robust import parse_json_robust_sync
from wiki.prompts import SYSTEM_JSON_ONLY

log = get_logger(__name__)

_MODULE_CORRECTION_PROMPT = (
    "You are reviewing business domain assignments for code modules.\n"
    "Below are the detected domains with module details:\n\n"
    "{domain_listing}\n\n"
    "Identify modules that clearly DO NOT belong to their assigned domain.\n"
    "Focus on modules whose NAME and PATH indicate a DIFFERENT business domain "
    "from the majority in that domain.\n\n"
    "Rules:\n"
    "- Only flag OBVIOUS misplacements (module name/path clearly indicates different domain)\n"
    "- Infrastructure modules (TaskExecutor, BaseService, CommonUtils, etc.) should stay\n"
    "- If unsure, do NOT flag\n\n"
    'Return ONLY valid JSON:\n'
    '{{"moves": [{{"module": "...", "from_domain": "...", "to_domain": "...", "reason": "..."}}]}}\n'
    'If no moves needed: {{"moves": []}}'
)

_MAX_MOVE_RATIO = 0.3


def _shorten_path(path: str, levels: int = 3) -> str:
    """Keep the last N directory levels of a module path."""
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-levels:]) if len(parts) > levels else path


def _build_domain_listing(
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
    module_paths: dict[str, str],
    module_summaries: dict[str, str],
) -> str:
    lines: list[str] = []
    for slug, pairs in sorted(domain_mapping.items()):
        display = domain_display_names.get(slug, slug)
        lines.append(f"Domain: {slug} ({display})")
        for _repo, mod_name in sorted(pairs, key=lambda p: p[1]):
            path = module_paths.get(mod_name, "")
            summary = module_summaries.get(mod_name, "")
            path_part = f"  [path: {_shorten_path(path)}]" if path else ""
            summary_part = f"  -- {summary}" if summary else ""
            lines.append(f"  - {mod_name}{path_part}{summary_part}")
        lines.append("")
    return "\n".join(lines)


class GraphSemanticCorrector:
    """LLM-based semantic coherence correction for domain assignments."""

    def __init__(self, llm: LLMPort | None):
        self._llm = llm

    async def correct_module_assignments(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_paths: dict[str, str],
        module_summaries: dict[str, str],
    ) -> dict[str, list[tuple[str, str]]]:
        if self._llm is None or not domain_mapping:
            return domain_mapping

        total_modules = sum(len(v) for v in domain_mapping.values())
        if total_modules <= 3:
            return domain_mapping

        listing = _build_domain_listing(
            domain_mapping, domain_display_names, module_paths, module_summaries,
        )
        prompt = _MODULE_CORRECTION_PROMPT.format(domain_listing=listing)

        try:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
        except Exception:
            log.warning("semantic_correction_llm_failed", exc_info=True)
            return domain_mapping

        if not isinstance(parsed, dict):
            return domain_mapping

        moves = parsed.get("moves")
        if not isinstance(moves, list) or not moves:
            return domain_mapping

        max_moves = max(int(total_modules * _MAX_MOVE_RATIO), 1)

        module_to_repo: dict[str, str] = {}
        for slug, pairs in domain_mapping.items():
            for repo, mod_name in pairs:
                module_to_repo[mod_name] = repo

        new_mapping = {slug: list(pairs) for slug, pairs in domain_mapping.items()}
        applied = 0

        for move in moves:
            if applied >= max_moves:
                break
            mod_name = move.get("module", "")
            from_domain = move.get("from_domain", "")
            to_domain = move.get("to_domain", "")

            if not mod_name or not from_domain or not to_domain:
                continue
            if from_domain not in new_mapping or to_domain not in new_mapping:
                continue

            repo = module_to_repo.get(mod_name)
            if repo is None:
                continue

            pair = (repo, mod_name)
            if pair not in new_mapping[from_domain]:
                continue

            new_mapping[from_domain].remove(pair)
            new_mapping[to_domain].append(pair)
            applied += 1
            log.info(
                "semantic_correction_move",
                module=mod_name,
                from_domain=from_domain,
                to_domain=to_domain,
                reason=move.get("reason", ""),
            )

        new_mapping = {k: v for k, v in new_mapping.items() if v}

        if applied:
            log.info("semantic_correction_applied", total_moves=applied, max_allowed=max_moves)

        return new_mapping
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_graph_semantic_corrector.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add wiki/graph_semantic_corrector.py tests/wiki/test_graph_semantic_corrector.py
git commit -m "feat: add GraphSemanticCorrector for module-level semantic correction"
```

---

### Task 2: Add Domain-Level Merge Review to `GraphSemanticCorrector`

**Files:**
- Modify: `wiki/graph_semantic_corrector.py`
- Modify: `tests/wiki/test_graph_semantic_corrector.py`

- [ ] **Step 1: Write the failing test for `merge_similar_domains()`**

```python
# Append to tests/wiki/test_graph_semantic_corrector.py

@pytest.mark.asyncio
async def test_merge_similar_domains(corrector, mock_llm):
    """Domains with overlapping business meaning should be merged."""
    domain_infos = [
        {"slug": "closed-friend-service", "display_name": "私密好友服务", "module_count": 5},
        {"slug": "closed-friend-market", "display_name": "私密好友市场", "module_count": 3},
        {"slug": "family-system", "display_name": "家族系统", "module_count": 10},
    ]
    mock_llm.generate.return_value = json.dumps({
        "merges": [
            {"sources": ["closed-friend-service", "closed-friend-market"], "target": "closed-friend-service", "reason": "same business"}
        ]
    })

    result = await corrector.merge_similar_domains(domain_infos)

    assert len(result) == 1
    assert result[0]["sources"] == ["closed-friend-service", "closed-friend-market"]
    assert result[0]["target"] == "closed-friend-service"


@pytest.mark.asyncio
async def test_merge_no_merges_needed(corrector, mock_llm):
    """When no merges needed, return empty list."""
    mock_llm.generate.return_value = json.dumps({"merges": []})

    result = await corrector.merge_similar_domains([
        {"slug": "family", "display_name": "家族", "module_count": 5},
    ])

    assert result == []


@pytest.mark.asyncio
async def test_merge_llm_failure_returns_empty(corrector, mock_llm):
    """When LLM fails, return empty list (no merges)."""
    mock_llm.generate.side_effect = Exception("LLM down")

    result = await corrector.merge_similar_domains([
        {"slug": "family", "display_name": "家族", "module_count": 5},
    ])

    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_graph_semantic_corrector.py::test_merge_similar_domains -v`
Expected: FAIL with AttributeError (method not found)

- [ ] **Step 3: Add `merge_similar_domains()` implementation**

Add to `wiki/graph_semantic_corrector.py`:

```python
_DOMAIN_MERGE_PROMPT = (
    "You are reviewing domain names for a wiki documentation tree.\n"
    "Below are all current domain names:\n\n"
    "{domain_listing}\n\n"
    "Identify domains that should be MERGED because they represent the same\n"
    "or highly overlapping business capability.\n\n"
    "Rules:\n"
    "- Only merge domains with CLEARLY overlapping business meaning\n"
    "- Keep the domain with more modules as the merge target\n"
    "- If unsure, do NOT merge\n\n"
    'Return ONLY valid JSON:\n'
    '{{"merges": [{{"sources": ["slug1", "slug2"], "target": "slug1", "reason": "..."}}]}}\n'
    'If no merges needed: {{"merges": []}}'
)
```

And add the `merge_similar_domains` method to the class:

```python
    async def merge_similar_domains(
        self,
        domain_infos: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._llm is None or len(domain_infos) <= 1:
            return []

        lines = []
        for info in domain_infos:
            lines.append(
                f"- {info['slug']} ({info['display_name']}) — {info['module_count']} modules"
            )
        listing = "\n".join(lines)
        prompt = _DOMAIN_MERGE_PROMPT.format(domain_listing=listing)

        try:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
        except Exception:
            log.warning("domain_merge_review_llm_failed", exc_info=True)
            return []

        if not isinstance(parsed, dict):
            return []

        merges = parsed.get("merges")
        if not isinstance(merges, list):
            return []

        valid_slugs = {info["slug"] for info in domain_infos}
        valid_merges = []
        for merge in merges:
            sources = merge.get("sources", [])
            target = merge.get("target", "")
            if (
                isinstance(sources, list)
                and len(sources) >= 2
                and isinstance(target, str)
                and target in valid_slugs
                and all(s in valid_slugs for s in sources)
                and target in sources
            ):
                valid_merges.append(merge)

        if valid_merges:
            log.info("domain_merge_review_found", merge_count=len(valid_merges))

        return valid_merges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_graph_semantic_corrector.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add wiki/graph_semantic_corrector.py tests/wiki/test_graph_semantic_corrector.py
git commit -m "feat: add merge_similar_domains to GraphSemanticCorrector"
```

---

### Task 3: Integrate Semantic Correction into Pipeline

**Files:**
- Modify: `wiki/nodes/graph_domain_decompose.py`
- Modify: `tests/wiki/test_graph_domain_namer.py` (if exists, or new test)

- [ ] **Step 1: Write the failing integration test**

```python
# tests/wiki/test_semantic_correction_integration.py
"""Integration test: semantic correction in graph_domain_decompose pipeline."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_semantic_correction_step_called():
    """Step 5.5 should call GraphSemanticCorrector.correct_module_assignments."""
    from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node

    mock_llm = AsyncMock()
    # LLM responses: 1) community naming, 2) semantic correction, 3) sub-domain naming, 4) domain merge
    mock_llm.generate.side_effect = [
        # Community 1 naming
        json.dumps({"slug": "family-system", "display_name": "家族系统", "description": ""}),
        # Community 2 naming
        json.dumps({"slug": "intimacy-mgmt", "display_name": "亲密关系管理", "description": ""}),
        # Semantic correction (no moves)
        json.dumps({"moves": []}),
        # Domain merge (no merges)
        json.dumps({"merges": []}),
    ]

    mock_graph_store = AsyncMock()

    state = {
        "entity_roles": {"uid1": "has_business_logic", "uid2": "has_business_logic"},
        "modules": {
            "repo1": [
                {"uid": "uid1", "label": "Module", "properties": {"name": "FamilyService", "path": "com/family/FamilyService.java"}},
                {"uid": "uid2", "label": "Module", "properties": {"name": "IntimacyService", "path": "com/intimacy/IntimacyService.java"}},
            ]
        },
        "repositories": ["repo1"],
    }
    config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}

    with patch("wiki.nodes.graph_domain_decompose.fetch_module_call_edges", return_value=[]):
        result = await graph_driven_domain_decompose_node(state, config)

    assert "domain_mapping" in result
    # Semantic correction was called (LLM generate called at least 3 times: 2 naming + 1 correction)
    assert mock_llm.generate.call_count >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_semantic_correction_integration.py -v`
Expected: FAIL (semantic correction not yet integrated)

- [ ] **Step 3: Modify `graph_domain_decompose.py` to insert Step 5.5 and Step 7.5**

In `wiki/nodes/graph_domain_decompose.py`, add the imports and insert the correction steps:

After Step 5 (post-processing), before Step 6 (stabilizer), add:

```python
    # --- Step 5.5: LLM Semantic Coherence Correction ---
    from wiki.graph_semantic_corrector import GraphSemanticCorrector

    module_paths: dict[str, str] = {}
    module_summaries: dict[str, str] = {}
    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            props = mod_dict.get("properties", {})
            name = str(props.get("name", ""))
            if name:
                module_paths[name] = str(props.get("path", "") or "")
                summary = str(props.get("business_summary", "") or props.get("docstring", "") or "")
                if summary:
                    module_summaries[name] = summary

    corrector = GraphSemanticCorrector(llm)
    domain_mapping = await corrector.correct_module_assignments(
        domain_mapping, domain_display_names, module_paths, module_summaries,
    )
```

After Step 7 (sub-domain splitting + naming), before Step 8 (build tree), add:

```python
    # --- Step 7.5: LLM Domain Merge Review ---
    all_domain_infos = []
    for c in communities_named:
        slug = c["slug"]
        subs = sub_trees.get(slug, [])
        if subs:
            for sub in subs:
                all_domain_infos.append({
                    "slug": sub["slug"],
                    "display_name": sub["display_name"],
                    "module_count": len(sub.get("modules", [])),
                })
        else:
            all_domain_infos.append({
                "slug": slug,
                "display_name": domain_display_names.get(slug, slug),
                "module_count": len(domain_mapping.get(slug, [])),
            })

    if len(all_domain_infos) > 2:
        merge_instructions = await corrector.merge_similar_domains(all_domain_infos)
        for merge in merge_instructions:
            sources = merge.get("sources", [])
            target = merge.get("target", "")
            for src_slug in sources:
                if src_slug == target or src_slug not in sub_trees:
                    continue
                # Move sub-domain modules to target
                if target in sub_trees:
                    target_subs = sub_trees[target]
                    for sub in sub_trees.get(src_slug, []):
                        target_subs.append(sub)
                    del sub_trees[src_slug]
            log.info("domain_merge_applied", sources=sources, target=target)
```

Also change Step 7 parameter:

```python
    # max_leaf_size: 8 → 15
    if len(community_nodes) > 15:
        sub_result = detector.detect_sub_communities(
            community_nodes, edges, max_depth=3, max_leaf_size=15
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_semantic_correction_integration.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests to check for regressions**

Run: `uv run pytest tests/wiki/test_graph_community_detector.py tests/wiki/test_graph_domain_namer.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/graph_domain_decompose.py tests/wiki/test_semantic_correction_integration.py
git commit -m "feat: integrate semantic correction into domain decompose pipeline"
```

---

### Task 4: Improve Domain Naming with Used-Names Injection

**Files:**
- Modify: `wiki/graph_domain_namer.py`
- Modify: `tests/wiki/test_graph_domain_namer.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/wiki/test_graph_domain_namer.py (or create if needed)

@pytest.mark.asyncio
async def test_name_community_with_used_names(mock_llm):
    """used_names should appear in the prompt to prevent duplicates."""
    from wiki.graph_domain_namer import GraphDomainNamer

    mock_llm.generate.return_value = json.dumps({
        "slug": "gift-system",
        "display_name": "送礼系统",
        "description": "gift sending",
    })
    namer = GraphDomainNamer(mock_llm)

    result = await namer.name_community(
        ["GiftHandler", "GiftService"],
        used_names=["family-system", "intimacy-mgmt"],
    )

    assert result["slug"] == "gift-system"
    prompt_text = mock_llm.generate.call_args[0][0]
    assert "family-system" in prompt_text
    assert "intimacy-mgmt" in prompt_text


@pytest.mark.asyncio
async def test_fallback_name_strips_tech_suffixes():
    """_fallback_name should strip technical suffixes before generating slug."""
    from wiki.graph_domain_namer import _fallback_name

    result = _fallback_name(["FamilyTaskHandler", "FamilyTaskValidator", "FamilyTaskExecutor"])
    assert "handler" not in result["slug"].lower()
    assert "family" in result["slug"].lower() or "familytask" in result["slug"].lower()


@pytest.mark.asyncio
async def test_name_community_retries_on_failure(mock_llm):
    """LLM failure should retry once before falling back."""
    from wiki.graph_domain_namer import GraphDomainNamer

    mock_llm.generate.side_effect = [
        Exception("timeout"),
        json.dumps({"slug": "family", "display_name": "家族", "description": ""}),
    ]
    namer = GraphDomainNamer(mock_llm)

    result = await namer.name_community(["FamilyService"])

    assert result["slug"] == "family"
    assert mock_llm.generate.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_graph_domain_namer.py -v -k "used_names or tech_suffixes or retries"`
Expected: FAIL

- [ ] **Step 3: Modify `graph_domain_namer.py`**

Changes:
1. Add `used_names` parameter to `name_community()` and inject into prompt
2. Improve `_fallback_name()` to strip tech suffixes
3. Add retry on LLM failure

```python
# Updated NAMING_PROMPT in wiki/graph_domain_namer.py
NAMING_PROMPT = (
    "You are naming a group of code modules that belong to the same business domain.\n"
    "These modules were grouped by their call-graph relationships "
    "(they call each other frequently).\n\n"
    "Rules:\n"
    "- Do NOT name based on technical suffixes (WebService, Handler, Dao, Provider)\n"
    "- Focus on the BUSINESS capability these modules provide together\n"
    "- Use concise Chinese business terminology for display_name\n"
    "- The slug should be kebab-case ASCII describing the business capability\n"
    "{used_names_block}"
    "\n"
    "Module list: {module_names}\n\n"
    'Return ONLY valid JSON: {{"slug": "...", "display_name": "...", "description": "..."}}'
)

_TECH_SUFFIXES = frozenset({
    "Handler", "Service", "Manager", "Executor", "Provider",
    "Dao", "Controller", "Impl", "WebService", "Listener",
    "Processor", "Worker", "Helper", "Adapter", "Factory",
})
```

Update `_fallback_name()`:
```python
def _fallback_name(module_names: list[str]) -> dict[str, str]:
    import re
    stripped = []
    for name in module_names:
        words = re.findall(r"[A-Z][a-z]+", name)
        while words and words[-1] in _TECH_SUFFIXES:
            words.pop()
        stripped.append("".join(words) if words else name)
    
    common = _extract_common_prefix(stripped)
    display_name = common or (stripped[0] if stripped else "unnamed")
    slug = normalize_slug(display_name)
    return {
        "slug": slug,
        "display_name": display_name,
        "description": f"Modules: {', '.join(module_names)}" if module_names else "",
    }
```

Update `name_community()` to accept `used_names` and retry:
```python
    async def name_community(
        self,
        module_names: list[str],
        *,
        used_names: list[str] | None = None,
    ) -> dict[str, str]:
        if not module_names or self._llm is None:
            return _fallback_name(module_names)

        used_block = ""
        if used_names:
            used_block = (
                "\nIMPORTANT: These names are already in use, choose a DIFFERENT name:\n"
                + ", ".join(used_names) + "\n"
            )

        prompt = NAMING_PROMPT.format(
            module_names=", ".join(module_names),
            used_names_block=used_block,
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
                    log.warning("graph_domain_namer_retry", module_count=len(module_names), exc_info=True)
                    continue
                log.warning("graph_domain_namer_llm_failed", module_count=len(module_names), exc_info=True)

        return _fallback_name(module_names)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_graph_domain_namer.py -v`
Expected: All PASS

- [ ] **Step 5: Update naming loops in `graph_domain_decompose.py` to pass `used_names`**

In Step 3 (community naming loop):
```python
    used_names: list[str] = []
    for community in communities:
        module_names = sorted([name for _, name in community])
        naming = await namer.name_community(module_names, used_names=used_names)
        used_names.append(naming["slug"])
        communities_named.append({...})
```

In Step 7 (sub-domain naming loop):
```python
    sub_used_names = list(used_names)  # inherit parent-level names
    for sub in leaf_subs:
        sub_module_names = sorted([name for _, name in sub.get("modules", [])])
        sub_naming = await namer.name_community(sub_module_names, used_names=sub_used_names)
        sub_used_names.append(sub_naming["slug"])
        named_subs.append({...})
```

- [ ] **Step 6: Run all related tests**

Run: `uv run pytest tests/wiki/test_graph_domain_namer.py tests/wiki/test_graph_semantic_corrector.py tests/wiki/test_semantic_correction_integration.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/graph_domain_namer.py wiki/nodes/graph_domain_decompose.py tests/wiki/test_graph_domain_namer.py
git commit -m "feat: inject used-names into domain naming, add retry and fallback improvements"
```

---

### Task 5: Adjust Orphan Adoption Threshold

**Files:**
- Modify: `wiki/tree_linker.py`
- Modify: `tests/wiki/test_tree_linker.py` (if test exists for threshold)

- [ ] **Step 1: Write the test**

```python
# tests/wiki/test_orphan_threshold.py
"""Test that orphan adoption threshold is 0.5."""
from wiki.tree_linker import WikiTreeLinker
import inspect


def test_orphan_threshold_is_0_5():
    """_adopt_orphan_domain_pages default threshold should be 0.5."""
    sig = inspect.signature(WikiTreeLinker._adopt_orphan_domain_pages)
    threshold_param = sig.parameters.get("threshold")
    assert threshold_param is not None
    assert threshold_param.default == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_orphan_threshold.py -v`
Expected: FAIL (current default is 0.3)

- [ ] **Step 3: Change threshold in `tree_linker.py`**

In `wiki/tree_linker.py`, change `_adopt_orphan_domain_pages` signature:

```python
    async def _adopt_orphan_domain_pages(
        self,
        business_id: str,
        domain_tree: list[DomainNode],
        domain_path_to_section_uid: dict[str, str],
        tree_builder: WikiTreeBuilder,
        threshold: float = 0.5,  # was 0.3
    ) -> None:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_orphan_threshold.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tree_linker tests**

Run: `uv run pytest tests/wiki/ -k "tree_linker or linker" -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/tree_linker.py tests/wiki/test_orphan_threshold.py
git commit -m "fix: raise orphan adoption threshold from 0.3 to 0.5"
```

---

### Task 6: End-to-End Verification on Dev

**Files:** None (deployment + manual verification)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/wiki/ -x --timeout=30`
Expected: All PASS

- [ ] **Step 2: Deploy to dev**

Run: `bash scripts/deploy-dev.sh --skip-build`

- [ ] **Step 3: Trigger wiki regeneration on dev**

```bash
ssh dev "curl -s -X POST -H 'Authorization: Bearer sk-admin-test' 'http://localhost:8100/api/v1/wiki/generate?business_id=ultron'"
```

- [ ] **Step 4: Query and verify domain structure**

```bash
ssh dev "curl -s -H 'Authorization: Bearer sk-admin-test' 'http://localhost:8100/api/v1/wiki/tree?business_id=ultron'" | python3 -c "
import json, sys
from collections import Counter
data = json.load(sys.stdin)
# Count sections, overview pages, cross-parent keyword scatter
..."
```

Expected improvements:
- Sections: 33 → ~10-15
- "挚友"跨父域: 7 → 1
- "家族"跨父域: 9 → 1-2
