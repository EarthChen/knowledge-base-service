# Wiki Phase 4: Quality Evaluation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-dimension quality evaluation system (Completeness / Helpfulness / Truthfulness) with structural checks, LLM-as-Judge evaluation, hierarchical score aggregation, and optional auto-heal for low-quality pages.

**Architecture:** Extend existing `quality_score` with LLM-based semantic evaluation. Judge receives wiki page + source code + graph metadata. Scores aggregate bottom-up: page → module → repo (weighted by ImportanceTier). Low-quality pages can be auto-marked for regeneration.

**Tech Stack:** Python 3.11+, LLM provider (existing), pydantic

**Spec:** [`docs/superpowers/specs/2026-04-28-wiki-hierarchical-generation-design.md`](../specs/2026-04-28-wiki-hierarchical-generation-design.md) §3.9

**Depends on:** Phase 1 completed (ImportanceTier). Phase 2 recommended (business flow pages to evaluate).

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/quality_evaluator.py` (create) | Core evaluation: structural checks + LLM judge + aggregation |
| `wiki/models.py` (modify) | Add `WikiQualityDimension`, `WikiPageQualityScore` |
| `config.py` (modify) | Add `quality_*` configuration fields |
| `api/routes/wiki_routes.py` (modify) | Add quality evaluation API endpoint |

---

### Task 1: Add quality evaluation models

**Files:**
- Modify: `wiki/models.py`
- Test: `tests/wiki/test_models.py`

- [ ] **Step 1: Write failing test**

```python
from wiki.models import WikiQualityDimension, WikiPageQualityScore


def test_quality_dimension_values():
    assert WikiQualityDimension.COMPLETENESS == "completeness"
    assert WikiQualityDimension.HELPFULNESS == "helpfulness"
    assert WikiQualityDimension.TRUTHFULNESS == "truthfulness"


def test_quality_score_overall():
    score = WikiPageQualityScore(
        page_path="classes/Foo.md",
        completeness=0.8,
        helpfulness=0.7,
        truthfulness=0.9,
        overall=0.8,
        issues=[],
    )
    assert score.overall == 0.8
    assert not score.issues
```

- [ ] **Step 2: Implement models**

```python
class WikiQualityDimension(StrEnum):
    COMPLETENESS = "completeness"
    HELPFULNESS = "helpfulness"
    TRUTHFULNESS = "truthfulness"


@dataclass
class WikiPageQualityScore:
    page_path: str
    completeness: float
    helpfulness: float
    truthfulness: float
    overall: float
    issues: list[str] = field(default_factory=list)
```

- [ ] **Step 3: Tests and commit**

---

### Task 2: Implement structural quality checks

**Files:**
- Create: `wiki/quality_evaluator.py`
- Create: `tests/wiki/test_quality_evaluator.py`

- [ ] **Step 1: Write failing tests for structural checks**

```python
import pytest
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.models import WikiPage, WikiPageMetadata, PageType


def test_structural_check_complete_page():
    page = WikiPage(
        path="test.md", title="Test", page_type=PageType.CLASS_DETAIL,
        content="# Test\n\n## Overview\n\nDescription.\n\n## Key components\n\nMethods.\n\n## Relationships\n\nCalls X.",
        diagrams=[], source_locations=[], metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert score.completeness >= 0.7  # has overview, components, relationships


def test_structural_check_empty_page():
    page = WikiPage(
        path="test.md", title="Test", page_type=PageType.CLASS_DETAIL,
        content="# Test\n\n_No content._",
        diagrams=[], source_locations=[], metadata=WikiPageMetadata(0, 0),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert score.completeness < 0.5
    assert len(score.issues) > 0
```

- [ ] **Step 2: Implement WikiQualityEvaluator structural checks**

```python
# wiki/quality_evaluator.py
class WikiQualityEvaluator:
    def __init__(self, llm=None, judge_model: str = ""):
        self._llm = llm
        self._judge_model = judge_model

    def structural_check(self, page: WikiPage) -> WikiPageQualityScore:
        """Quick structural quality assessment without LLM."""
        issues = []
        completeness = 0.0
        checks = [
            ("## Overview" in page.content, "missing_overview", 0.25),
            ("## Key components" in page.content or "## Methods" in page.content, "missing_components", 0.25),
            ("## Relationships" in page.content, "missing_relationships", 0.2),
            (len(page.content) > 200, "content_too_short", 0.15),
            (len(page.diagrams) > 0, "no_diagrams", 0.15),
        ]
        for present, issue_id, weight in checks:
            if present:
                completeness += weight
            else:
                issues.append(issue_id)
        return WikiPageQualityScore(
            page_path=page.path,
            completeness=completeness,
            helpfulness=completeness * 0.8,  # rough proxy
            truthfulness=1.0,  # structural check can't verify truthfulness
            overall=completeness * 0.9,
            issues=issues,
        )
```

- [ ] **Step 3: Tests and commit**

---

### Task 3: Implement LLM-as-Judge evaluation

**Files:**
- Modify: `wiki/quality_evaluator.py`
- Test: `tests/wiki/test_quality_evaluator.py`

- [ ] **Step 1: Add `llm_judge_evaluate` method**

```python
async def llm_judge_evaluate(
    self,
    page: WikiPage,
    source_code: str = "",
    graph_metadata: str = "",
) -> WikiPageQualityScore:
    """Full quality evaluation using LLM as judge."""
    if not self._llm:
        return self.structural_check(page)

    prompt = f"""Evaluate this documentation page on three dimensions.

Page content:
{page.content[:3000]}

Source code context:
{source_code[:2000]}

Graph metadata:
{graph_metadata[:1000]}

Score each dimension 0.0-1.0 and list any issues:
1. Completeness: Does it cover purpose, methods, relationships, usage patterns?
2. Helpfulness: Can a developer new to this codebase understand the component?
3. Truthfulness: Are code references accurate? Any hallucinations?

Output JSON:
{{"completeness": 0.0, "helpfulness": 0.0, "truthfulness": 0.0, "issues": ["issue1"]}}"""

    result = await self._llm.complete_json(
        [{"role": "user", "content": prompt}],
        schema={"type": "object"},
    )
    return WikiPageQualityScore(
        page_path=page.path,
        completeness=float(result.get("completeness", 0)),
        helpfulness=float(result.get("helpfulness", 0)),
        truthfulness=float(result.get("truthfulness", 0)),
        overall=(float(result.get("completeness", 0)) + float(result.get("helpfulness", 0)) + float(result.get("truthfulness", 0))) / 3,
        issues=result.get("issues", []),
    )
```

- [ ] **Step 2: Tests with mocked LLM and commit**

---

### Task 4: Implement hierarchical score aggregation

**Files:**
- Modify: `wiki/quality_evaluator.py`

- [ ] **Step 1: Add aggregation method**

```python
def aggregate_scores(
    self,
    page_scores: list[WikiPageQualityScore],
    tier_map: dict[str, ImportanceTier],
) -> dict[str, float]:
    """Aggregate page scores into module/repo score with tier weighting."""
    tier_weights = {ImportanceTier.CORE: 3.0, ImportanceTier.STANDARD: 2.0, ImportanceTier.SKELETON: 1.0}
    total_weight = 0.0
    weighted_sum = 0.0
    for score in page_scores:
        tier = tier_map.get(score.page_path)
        w = tier_weights.get(tier, 1.0) if tier else 1.0
        weighted_sum += score.overall * w
        total_weight += w
    return {
        "overall": weighted_sum / total_weight if total_weight > 0 else 0,
        "page_count": len(page_scores),
    }
```

- [ ] **Step 2: Tests and commit**

---

### Task 5: Add configuration, sampling strategy, API endpoint, and quality storage

**Files:**
- Modify: `config.py`
- Modify: `api/routes/wiki_routes.py`
- Modify: `wiki/quality_evaluator.py` — add sampling logic
- Modify: `store/wiki_store.py` — add quality score persistence

- [ ] **Step 1: Add quality_* config fields**

```python
# config.py WikiConfig additions
quality_evaluation_mode: str = Field(default="quick")  # quick | sampled | full
quality_min_score: float = Field(default=0.6)
quality_auto_heal: bool = Field(default=False)
quality_judge_model: str = Field(default="")
quality_sample_size: int = Field(default=20)  # for sampled mode
```

- [ ] **Step 2: Implement sampling strategy for `sampled` mode**

```python
# wiki/quality_evaluator.py — add method

def select_sample_pages(
    self,
    pages: list[WikiPage],
    tier_map: dict[str, ImportanceTier],
    sample_size: int = 20,
) -> list[WikiPage]:
    """Select representative pages for sampled quality evaluation.
    Strategy: All CORE pages + random sample of STANDARD pages to fill quota."""
    import random

    core_pages = [p for p in pages if tier_map.get(p.path) == ImportanceTier.CORE]
    standard_pages = [p for p in pages if tier_map.get(p.path) == ImportanceTier.STANDARD]

    # Always include all CORE pages
    sample = list(core_pages)

    # Fill remaining quota from STANDARD
    remaining = max(0, sample_size - len(sample))
    if remaining > 0 and standard_pages:
        sample.extend(random.sample(standard_pages, min(remaining, len(standard_pages))))

    return sample
```

- [ ] **Step 3: Write test for sampling**

```python
# Append to tests/wiki/test_quality_evaluator.py

def test_select_sample_all_core_included():
    evaluator = WikiQualityEvaluator(llm=None)
    pages = [
        WikiPage(path=f"p{i}.md", title=f"P{i}", page_type=PageType.CLASS_DETAIL,
                 content="# Test", diagrams=[], source_locations=[],
                 metadata=WikiPageMetadata(1, 1))
        for i in range(50)
    ]
    tier_map = {
        "p0.md": ImportanceTier.CORE,
        "p1.md": ImportanceTier.CORE,
        "p2.md": ImportanceTier.CORE,
    }
    for i in range(3, 50):
        tier_map[f"p{i}.md"] = ImportanceTier.STANDARD

    sample = evaluator.select_sample_pages(pages, tier_map, sample_size=10)
    assert len(sample) == 10
    core_in_sample = [p for p in sample if tier_map[p.path] == ImportanceTier.CORE]
    assert len(core_in_sample) == 3  # all CORE pages included
```

- [ ] **Step 4: Add quality score persistence**

```python
# store/wiki_store.py — add methods

async def save_quality_scores(
    self, repository: str, scores: list["WikiPageQualityScore"],
) -> None:
    """Persist quality scores to graph for historical tracking."""
    for score in scores:
        await self._store.execute_query(
            "MATCH (p:WikiPage {repository: $repo, path: $path}) "
            "SET p.quality_completeness = $comp, "
            "    p.quality_helpfulness = $help, "
            "    p.quality_truthfulness = $truth, "
            "    p.quality_overall = $overall, "
            "    p.quality_issues = $issues, "
            "    p.quality_evaluated_at = datetime()",
            {
                "repo": repository, "path": score.page_path,
                "comp": score.completeness, "help": score.helpfulness,
                "truth": score.truthfulness, "overall": score.overall,
                "issues": ",".join(score.issues),
            },
        )

async def get_quality_summary(self, repository: str) -> dict[str, Any]:
    """Get aggregate quality statistics for a repository."""
    result = await self._store.execute_query(
        "MATCH (p:WikiPage {repository: $repo}) "
        "WHERE p.quality_overall IS NOT NULL "
        "RETURN avg(p.quality_overall) AS avg_score, "
        "       count(p) AS evaluated_count, "
        "       count(CASE WHEN p.quality_overall < 0.6 THEN 1 END) AS low_quality_count",
        {"repo": repository},
    )
    rows = getattr(result, 'data', None) or []
    if rows and rows[0]:
        return {
            "avg_score": round(float(rows[0][0] or 0), 3),
            "evaluated_count": int(rows[0][1] or 0),
            "low_quality_count": int(rows[0][2] or 0),
        }
    return {"avg_score": 0, "evaluated_count": 0, "low_quality_count": 0}
```

- [ ] **Step 5: Add `/wiki/quality` API endpoint**

```python
# api/routes/wiki_routes.py

@router.post("/quality/evaluate")
async def evaluate_wiki_quality(
    repository: str,
    mode: str = Query(default="quick", regex="^(quick|sampled|full)$"),
    wiki_service: WikiService = Depends(get_wiki_service),
):
    """Evaluate quality of generated wiki pages."""
    evaluator = WikiQualityEvaluator(
        llm=wiki_service._llm if mode != "quick" else None,
        judge_model=getattr(wiki_service._wiki_cfg, 'quality_judge_model', ''),
    )
    # Load pages from store
    wiki_store = WikiStore(wiki_service._store)
    pages = await wiki_store.list_wiki_pages_all(repository)

    if mode == "sampled":
        pages = evaluator.select_sample_pages(
            pages, tier_map={},
            sample_size=getattr(wiki_service._wiki_cfg, 'quality_sample_size', 20),
        )

    if mode == "quick":
        scores = [evaluator.structural_check(p) for p in pages]
    else:
        scores = [await evaluator.llm_judge_evaluate(p) for p in pages]

    # Persist scores
    await wiki_store.save_quality_scores(repository, scores)
    summary = evaluator.aggregate_scores(scores, tier_map={})

    # Alert if quality degraded (Hubble integration)
    if summary.get("overall", 1.0) < getattr(wiki_service._wiki_cfg, 'quality_min_score', 0.6):
        log.error("wiki_quality_below_threshold",
                  repository=repository, score=summary["overall"])

    return {"mode": mode, "scores": summary, "evaluated_pages": len(scores)}


@router.get("/quality/summary")
async def get_wiki_quality_summary(
    repository: str,
    wiki_service: WikiService = Depends(get_wiki_service),
):
    """Get quality summary for a repository's wiki."""
    wiki_store = WikiStore(wiki_service._store)
    return await wiki_store.get_quality_summary(repository)
```

- [ ] **Step 6: Tests and commit**

```bash
git add config.py wiki/quality_evaluator.py store/wiki_store.py api/routes/wiki_routes.py tests/wiki/test_quality_evaluator.py
git commit -m "feat(wiki): add quality evaluation sampling, persistence, and API endpoints"
```

---

### Task 6: Quality feedback loop (auto-heal)

**Files:**
- Modify: `wiki/quality_evaluator.py`
- Modify: `wiki/service.py`
- Modify: `wiki/composer.py` — accept quality hints in compose_page

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/wiki/test_quality_evaluator.py

def test_identify_pages_for_heal():
    evaluator = WikiQualityEvaluator(llm=None)
    scores = [
        WikiPageQualityScore("a.md", 0.9, 0.8, 0.9, 0.87, []),
        WikiPageQualityScore("b.md", 0.3, 0.4, 0.5, 0.4, ["missing_overview", "content_too_short"]),
        WikiPageQualityScore("c.md", 0.5, 0.5, 0.6, 0.53, ["no_diagrams"]),
    ]
    to_heal = evaluator.identify_pages_for_heal(scores, min_score=0.6)
    assert "b.md" in to_heal
    assert "c.md" in to_heal
    assert "a.md" not in to_heal


def test_build_heal_prompt_includes_issues():
    evaluator = WikiQualityEvaluator(llm=None)
    score = WikiPageQualityScore("b.md", 0.3, 0.4, 0.5, 0.4,
                                  ["missing_overview", "content_too_short"])
    prompt_hint = evaluator.build_heal_prompt_hint(score)
    assert "missing_overview" in prompt_hint
    assert "content_too_short" in prompt_hint
```

- [ ] **Step 2: Implement identification and prompt enhancement**

```python
# wiki/quality_evaluator.py — add methods

def identify_pages_for_heal(
    self,
    scores: list[WikiPageQualityScore],
    min_score: float = 0.6,
) -> list[str]:
    """Return page paths scoring below threshold."""
    return [s.page_path for s in scores if s.overall < min_score]

def build_heal_prompt_hint(self, score: WikiPageQualityScore) -> str:
    """Build a prompt enhancement hint from quality issues."""
    if not score.issues:
        return ""
    issue_descriptions = {
        "missing_overview": "Add a clear ## Overview section explaining the component's purpose.",
        "missing_components": "Add a ## Key components or ## Methods section listing important members.",
        "missing_relationships": "Add a ## Relationships section showing dependencies and callers.",
        "content_too_short": "Expand the documentation with more detail about behavior and usage.",
        "no_diagrams": "Consider what visual diagram would help explain the architecture.",
    }
    hints = [issue_descriptions.get(i, f"Address: {i}") for i in score.issues]
    return (
        "\n\n## Quality Improvement Instructions\n"
        "The previous version of this documentation was flagged for quality issues. "
        "Please specifically address:\n"
        + "\n".join(f"- {h}" for h in hints)
    )
```

- [ ] **Step 3: Wire into post-generation flow in WikiService**

Add auto-heal pass after quality evaluation in `generate_wiki`:

```python
# In wiki/service.py, after quality evaluation
if getattr(self._wiki_cfg, 'quality_auto_heal', False):
    evaluator = WikiQualityEvaluator(llm=self._llm)
    # Quick structural check on all pages
    scores = [evaluator.structural_check(p) for p in pages]
    to_heal = evaluator.identify_pages_for_heal(scores,
        min_score=getattr(self._wiki_cfg, 'quality_min_score', 0.6))

    if to_heal:
        log.info("auto_heal_start", repository=repository,
                 pages_to_heal=len(to_heal), max_attempts=2)
        heal_attempts: dict[str, int] = {}  # path → attempt count

        for page_path in to_heal:
            attempts = heal_attempts.get(page_path, 0)
            if attempts >= 2:
                log.warning("auto_heal_max_attempts", path=page_path)
                continue

            score = next(s for s in scores if s.page_path == page_path)
            hint = evaluator.build_heal_prompt_hint(score)

            # Re-compose with quality hints injected into parent_context
            page_idx = next(i for i, p in enumerate(pages) if p.path == page_path)
            original_page = pages[page_idx]
            # ... recompose with hint as additional context ...
            heal_attempts[page_path] = attempts + 1

        log.info("auto_heal_complete", repository=repository,
                 healed=len(heal_attempts))
```

> **Integration with existing quality_score:** The new `WikiQualityEvaluator` **extends** (not replaces)
> the existing `quality_score` field in `WikiPageMetadata`. The structural check reuses the same
> section-presence logic. The new system adds LLM-based evaluation and hierarchical aggregation
> on top of it. The `quality_score` field on `WikiPageMetadata` will be updated to store the
> `overall` score from `WikiPageQualityScore`.

- [ ] **Step 4: Tests and commit**

Run: `uv run pytest tests/wiki/test_quality_evaluator.py -v`
Expected: ALL PASS

```bash
git add wiki/quality_evaluator.py wiki/service.py wiki/composer.py tests/wiki/test_quality_evaluator.py
git commit -m "feat(wiki): add quality auto-heal with enhanced prompts"
```

---

## Self-Review Checklist

- [x] Spec §3.9.1 (Three dimensions): Tasks 1, 3
- [x] Spec §3.9.2 (Evaluation pipeline): Tasks 2, 3
- [x] Spec §3.9.3 (Evaluation modes): Task 5
- [x] Spec §3.9.4 (Auto-heal): Task 6
- [x] Hierarchical aggregation: Task 4
- [x] Configuration: Task 5
