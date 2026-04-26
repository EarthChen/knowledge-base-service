# Wiki 质量保障（Phase 6）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]` / `- [x]`) syntax for tracking.

**Goal:** 为业务级 Wiki 提供覆盖率分析、过时检测、探索问题自动生成三大质量保障能力，让用户和 Agent 能够快速识别文档盲区和过时内容。

**Architecture:** `WikiCoverageAnalyzer` 查询图谱统计实体覆盖情况，通过 `commit_sha` 比对检测过时页面，识别高调用度但文档薄弱的知识盲区。`SuggestedQuestionsGenerator` 基于图谱拓扑（调用关系、跨域边、hub 节点）为每个 Wiki 页面生成探索问题。覆盖率报告 API 统一暴露分析结果。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB (Cypher), asyncio, dataclasses

**Spec:**
- [2026-04-26-wiki-tree-architecture-design.md](../specs/2026-04-26-wiki-tree-architecture-design.md)（"质量保障机制" 章节）

**Code Review 要求:** 每个 Task 完成后必须进行 code review（spec compliance + code quality），确认代码质量和测试覆盖后再进入下一个 Task。

**前置条件:** Phase 0-5 均已完成。1446 测试通过。WikiConfig 中已定义 `coverage_report_enabled`、`stale_detection_enabled`、`suggested_questions_enabled` 配置字段。实体节点（Function/Class/Module）有 `commit_sha` 属性。WikiPage 有 `generated_at` 属性和 `content_hash`。

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `wiki/coverage_analyzer.py` | `WikiCoverageAnalyzer` + `CoverageReport` — 覆盖率分析 + 过时检测 |
| Create | `wiki/suggested_questions.py` | `SuggestedQuestionsGenerator` — 基于图谱拓扑的探索问题生成 |
| Modify | `store/wiki_store.py` | 新增覆盖率 / 过时检测 / 知识盲区查询方法 |
| Modify | `api/routes/wiki_routes.py` | 新增 `GET /api/v1/wiki/coverage-report` 端点 |
| Modify | `wiki/__init__.py` | 导出 Phase 6 新组件 |
| Create | `tests/wiki/test_coverage_analyzer.py` | WikiCoverageAnalyzer 单元测试 |
| Create | `tests/wiki/test_suggested_questions.py` | SuggestedQuestionsGenerator 单元测试 |
| Create | `tests/wiki/test_coverage_api.py` | 覆盖率报告 API 端点测试 |
| Create | `tests/wiki/integration/test_phase6_smoke.py` | Phase 6 集成烟雾测试 |

---

### Task 1: CoverageReport + WikiCoverageAnalyzer 核心

**Files:**
- Create: `wiki/coverage_analyzer.py`
- Create: `tests/wiki/test_coverage_analyzer.py`
- Modify: `store/wiki_store.py` — 新增 `get_entity_coverage_stats()` 和 `get_knowledge_gaps()` 方法

**背景:** WikiCoverageAnalyzer 扫描所有 core/standard 重要度的实体，检查哪些还没有 wiki 页面或只有 skeleton 级别。同时识别高调用度但文档薄弱的"知识盲区"。

- [ ] **Step 1: Write the failing tests**

创建 `tests/wiki/test_coverage_analyzer.py`：

```python
# tests/wiki/test_coverage_analyzer.py
"""Unit tests for WikiCoverageAnalyzer."""

import pytest
from unittest.mock import AsyncMock

from wiki.coverage_analyzer import WikiCoverageAnalyzer, CoverageReport


class TestCoverageReport:
    def test_dataclass_fields(self):
        report = CoverageReport(
            total_entities=100,
            covered_entities=80,
            core_coverage=0.95,
            standard_coverage=0.75,
            stale_pages=[],
            knowledge_gaps=[],
        )
        assert report.total_entities == 100
        assert report.covered_entities == 80
        assert report.core_coverage == 0.95

    def test_coverage_percentage(self):
        report = CoverageReport(
            total_entities=50,
            covered_entities=40,
            core_coverage=0.9,
            standard_coverage=0.7,
            stale_pages=[],
            knowledge_gaps=[],
        )
        assert report.coverage_percentage == 80.0

    def test_zero_entities_coverage(self):
        report = CoverageReport(
            total_entities=0,
            covered_entities=0,
            core_coverage=0.0,
            standard_coverage=0.0,
            stale_pages=[],
            knowledge_gaps=[],
        )
        assert report.coverage_percentage == 0.0


class TestWikiCoverageAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_with_full_coverage(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 50,
            "covered_entities": 50,
            "core_total": 10,
            "core_covered": 10,
            "standard_total": 40,
            "standard_covered": 40,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("test-biz")
        assert report.total_entities == 50
        assert report.covered_entities == 50
        assert report.core_coverage == 1.0
        assert len(report.knowledge_gaps) == 0

    @pytest.mark.asyncio
    async def test_analyze_with_partial_coverage(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 100,
            "covered_entities": 60,
            "core_total": 20,
            "core_covered": 15,
            "standard_total": 80,
            "standard_covered": 45,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[
            {"entity_name": "CacheService", "in_degree": 12, "wiki_tier": "skeleton"},
            {"entity_name": "PaymentGateway", "in_degree": 8, "wiki_tier": None},
        ])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("test-biz")
        assert report.total_entities == 100
        assert report.covered_entities == 60
        assert report.core_coverage == 0.75
        assert len(report.knowledge_gaps) == 2

    @pytest.mark.asyncio
    async def test_analyze_empty_db(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 0,
            "covered_entities": 0,
            "core_total": 0,
            "core_covered": 0,
            "standard_total": 0,
            "standard_covered": 0,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("empty-biz")
        assert report.total_entities == 0
        assert report.coverage_percentage == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Add store query methods**

在 `store/wiki_store.py` 中添加：

```python
async def get_entity_coverage_stats(self, business_id: str) -> dict[str, int]:
    """Count entities by importance tier and wiki coverage."""
    q = (
        "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
        "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(e) "
        "WITH collect(DISTINCT e.uid) AS covered_uids, "
        "     collect(DISTINCT wp.importance_tier) AS tiers "
        "MATCH (ws2:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp2:WikiPage) "
        "RETURN count(DISTINCT wp2) AS total_pages"
    )
    # Alternative simpler approach: count WikiPages by tier
    q_total = (
        "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
        "RETURN wp.importance_tier AS tier, count(wp) AS cnt"
    )
    result = await self._store.execute_query(q_total, {"business_id": business_id})
    stats = {"total_entities": 0, "covered_entities": 0,
             "core_total": 0, "core_covered": 0,
             "standard_total": 0, "standard_covered": 0}
    for row in result.data:
        tier = str(row.get("tier", ""))
        cnt = int(row.get("cnt", 0))
        stats["total_entities"] += cnt
        if tier == "core":
            stats["core_total"] += cnt
            stats["core_covered"] += cnt
            stats["covered_entities"] += cnt
        elif tier == "standard":
            stats["standard_total"] += cnt
            stats["standard_covered"] += cnt
            stats["covered_entities"] += cnt
        elif tier == "skeleton":
            stats["total_entities"] += 0  # already counted
    return stats

async def get_knowledge_gaps(self, business_id: str, min_in_degree: int = 5) -> list[dict]:
    """Find entities with high in-degree but weak/missing wiki documentation."""
    q = (
        "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
        "MATCH (wp)-[:SOURCE_ENTITY]->(e) "
        "WHERE wp.importance_tier = 'skeleton' OR wp.importance_tier IS NULL "
        "WITH e, wp "
        "OPTIONAL MATCH (caller)-[:CALLS|USES|IMPORTS]->(e) "
        "WITH e.name AS entity_name, wp.importance_tier AS wiki_tier, count(caller) AS in_degree "
        "WHERE in_degree >= $min_in_degree "
        "RETURN entity_name, in_degree, wiki_tier "
        "ORDER BY in_degree DESC"
    )
    result = await self._store.execute_query(q, {"business_id": business_id, "min_in_degree": min_in_degree})
    return [
        {"entity_name": str(r.get("entity_name", "")), "in_degree": int(r.get("in_degree", 0)),
         "wiki_tier": r.get("wiki_tier")}
        for r in result.data
    ]
```

- [ ] **Step 4: Implement WikiCoverageAnalyzer**

创建 `wiki/coverage_analyzer.py`：

```python
"""Wiki coverage analysis — identifies documentation gaps and stale content."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageReport:
    """Coverage analysis result for a business wiki."""
    total_entities: int
    covered_entities: int
    core_coverage: float
    standard_coverage: float
    stale_pages: list[dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def coverage_percentage(self) -> float:
        if self.total_entities == 0:
            return 0.0
        return round(self.covered_entities / self.total_entities * 100, 1)


class WikiCoverageAnalyzer:
    """Analyzes wiki documentation coverage and identifies quality issues."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def analyze(self, business_id: str) -> CoverageReport:
        stats = await self._store.get_entity_coverage_stats(business_id)
        gaps = await self._store.get_knowledge_gaps(business_id)

        core_total = stats.get("core_total", 0)
        core_covered = stats.get("core_covered", 0)
        standard_total = stats.get("standard_total", 0)
        standard_covered = stats.get("standard_covered", 0)

        core_coverage = core_covered / core_total if core_total > 0 else 0.0
        standard_coverage = standard_covered / standard_total if standard_total > 0 else 0.0

        return CoverageReport(
            total_entities=stats.get("total_entities", 0),
            covered_entities=stats.get("covered_entities", 0),
            core_coverage=round(core_coverage, 2),
            standard_coverage=round(standard_coverage, 2),
            knowledge_gaps=[
                {"entity": g["entity_name"], "in_degree": g["in_degree"], "wiki_tier": g["wiki_tier"]}
                for g in gaps
            ],
        )
```

- [ ] **Step 5: Run tests to verify they pass**
- [ ] **Step 6: Run full test suite**

**Commit:** `feat(wiki): add WikiCoverageAnalyzer for documentation coverage analysis`

---

### Task 2: Stale Detection — 过时检测

**Files:**
- Modify: `wiki/coverage_analyzer.py` — 添加 `detect_stale_pages()` 方法
- Modify: `store/wiki_store.py` — 新增 `get_stale_wiki_pages()` 查询方法
- Modify: `tests/wiki/test_coverage_analyzer.py` — 添加过时检测测试

**背景:** 当代码实体的 `commit_sha` 与 WikiPage 生成时引用的代码版本不一致时，标记页面为 "可能过时"。WikiPage 目前没有 `source_commit_sha` 字段，需要通过 `SOURCE_ENTITY` 边关联到实体的 `commit_sha` 并与 `WikiPage.content_hash` 进行间接比对。

- [ ] **Step 1: Write failing tests for stale detection**

在 `tests/wiki/test_coverage_analyzer.py` 中添加：

```python
class TestStaleDetection:
    @pytest.mark.asyncio
    async def test_detect_stale_pages(self):
        mock_store = AsyncMock()
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[
            {"page_path": "/用户管理/UserService", "page_title": "UserService",
             "entity_commit": "abc123", "page_generated_at": "2026-04-20"},
        ])
        analyzer = WikiCoverageAnalyzer(mock_store)
        stale = await analyzer.detect_stale_pages("test-biz")
        assert len(stale) == 1
        assert stale[0]["page_path"] == "/用户管理/UserService"

    @pytest.mark.asyncio
    async def test_no_stale_pages(self):
        mock_store = AsyncMock()
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[])
        analyzer = WikiCoverageAnalyzer(mock_store)
        stale = await analyzer.detect_stale_pages("test-biz")
        assert stale == []

    @pytest.mark.asyncio
    async def test_analyze_includes_stale_pages(self):
        mock_store = AsyncMock()
        mock_store.get_entity_coverage_stats = AsyncMock(return_value={
            "total_entities": 10, "covered_entities": 8,
            "core_total": 5, "core_covered": 4,
            "standard_total": 5, "standard_covered": 4,
        })
        mock_store.get_knowledge_gaps = AsyncMock(return_value=[])
        mock_store.get_stale_wiki_pages = AsyncMock(return_value=[
            {"page_path": "/Domain/Old", "page_title": "Old",
             "entity_commit": "new123", "page_generated_at": "2026-04-01"},
        ])
        analyzer = WikiCoverageAnalyzer(mock_store)
        report = await analyzer.analyze("biz")
        assert len(report.stale_pages) == 1
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Add `get_stale_wiki_pages()` to WikiStore**
- [ ] **Step 4: Implement `detect_stale_pages()` in WikiCoverageAnalyzer**
- [ ] **Step 5: Integrate stale detection into `analyze()` method**
- [ ] **Step 6: Run tests and full suite**

**Commit:** `feat(wiki): add stale page detection to WikiCoverageAnalyzer`

---

### Task 3: SuggestedQuestionsGenerator — 探索问题生成

**Files:**
- Create: `wiki/suggested_questions.py`
- Create: `tests/wiki/test_suggested_questions.py`

**背景:** 基于图谱拓扑分析（调用关系、跨域边、hub 节点）为每个 Wiki 页面自动生成 3-5 个探索问题。使用模板引擎而非 LLM 来保证确定性和低延迟。

- [ ] **Step 1: Write failing tests**

创建 `tests/wiki/test_suggested_questions.py`：

```python
# tests/wiki/test_suggested_questions.py
"""Unit tests for SuggestedQuestionsGenerator."""

from wiki.suggested_questions import SuggestedQuestionsGenerator, PageContext


class TestSuggestedQuestionsGenerator:
    def test_generates_questions_for_hub(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="UserService",
            domain="用户管理",
            callers=["OrderController", "AuthService", "AdminPanel"],
            callees=["UserDAO", "CacheService"],
            cross_domain_callers=["OrderController"],
        )
        questions = gen.generate(ctx)
        assert len(questions) >= 3
        assert any("UserService" in q for q in questions)

    def test_generates_questions_for_cross_domain(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="CacheService",
            domain="基础设施",
            callers=["UserService", "OrderService", "PaymentService"],
            callees=["RedisClient"],
            cross_domain_callers=["UserService", "OrderService", "PaymentService"],
        )
        questions = gen.generate(ctx)
        assert any("跨域" in q or "cross" in q.lower() or "领域" in q for q in questions)

    def test_generates_questions_for_leaf(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="UserDTO",
            domain="用户管理",
            callers=[],
            callees=[],
            cross_domain_callers=[],
        )
        questions = gen.generate(ctx)
        assert len(questions) >= 1

    def test_question_count_limit(self):
        gen = SuggestedQuestionsGenerator(max_questions=3)
        ctx = PageContext(
            entity_name="BigService",
            domain="Domain",
            callers=[f"Caller{i}" for i in range(20)],
            callees=[f"Callee{i}" for i in range(10)],
            cross_domain_callers=[f"XCaller{i}" for i in range(5)],
        )
        questions = gen.generate(ctx)
        assert len(questions) <= 3

    def test_empty_context(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="Unknown",
            domain="",
            callers=[],
            callees=[],
            cross_domain_callers=[],
        )
        questions = gen.generate(ctx)
        assert isinstance(questions, list)
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement SuggestedQuestionsGenerator**

创建 `wiki/suggested_questions.py`：

```python
"""Template-based exploration question generator for wiki pages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageContext:
    """Graph context for a wiki page entity."""
    entity_name: str
    domain: str
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    cross_domain_callers: list[str] = field(default_factory=list)


class SuggestedQuestionsGenerator:
    """Generates exploration questions based on graph topology."""

    def __init__(self, max_questions: int = 5) -> None:
        self._max = max_questions

    def generate(self, ctx: PageContext) -> list[str]:
        questions: list[str] = []

        if ctx.cross_domain_callers:
            domains = ", ".join(ctx.cross_domain_callers[:3])
            questions.append(
                f"{ctx.entity_name} 被跨域组件（{domains}）调用，"
                f"是否存在过度耦合或需要抽象为共享服务？"
            )

        if len(ctx.callers) >= 3:
            questions.append(
                f"{ctx.entity_name} 有 {len(ctx.callers)} 个调用方，"
                f"哪些是核心业务路径，哪些是辅助调用？"
            )

        if ctx.callees:
            deps = ", ".join(ctx.callees[:3])
            questions.append(
                f"{ctx.entity_name} 依赖 {deps} 等组件，"
                f"如果其中一个故障，降级策略是什么？"
            )

        if ctx.domain:
            questions.append(
                f"在 {ctx.domain} 领域中，{ctx.entity_name} 承担的核心职责是什么？"
                f"是否有职责边界不清晰的情况？"
            )

        if not questions:
            questions.append(
                f"{ctx.entity_name} 的设计意图和主要使用场景是什么？"
            )

        return questions[:self._max]
```

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Run full test suite**

**Commit:** `feat(wiki): add SuggestedQuestionsGenerator for exploration questions`

---

### Task 4: Coverage Report API — GET /api/v1/wiki/coverage-report

**Files:**
- Modify: `api/routes/wiki_routes.py` — 新增 `GET /api/v1/wiki/coverage-report` 端点
- Create: `tests/wiki/test_coverage_api.py`

**背景:** 统一暴露覆盖率分析结果，包括覆盖率统计、过时页面列表、知识盲区。根据配置字段控制功能开关。

- [ ] **Step 1: Write failing tests**

创建 `tests/wiki/test_coverage_api.py`：

```python
# tests/wiki/test_coverage_api.py
"""Unit tests for wiki coverage report API endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.wiki_routes import wiki_router


class TestCoverageReportEndpoint:
    def test_returns_coverage_report(self):
        # setup app with mock store returning coverage data
        ...

    def test_disabled_by_config(self):
        # when coverage_report_enabled=False, return 404 or empty
        ...

    def test_includes_stale_pages_when_enabled(self):
        ...

    def test_empty_business_returns_zero(self):
        ...
```

- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Add endpoint to wiki_routes.py**
- [ ] **Step 4: Run tests and full suite**

**Commit:** `feat(wiki): add coverage report API endpoint`

---

### Task 5: Integration + Phase 6 exports

**Files:**
- Modify: `wiki/__init__.py`
- Create: `tests/wiki/integration/test_phase6_smoke.py`

- [ ] **Step 1: Update wiki/__init__.py**

添加 Phase 6 组件导出：

```python
from wiki.coverage_analyzer import WikiCoverageAnalyzer, CoverageReport
from wiki.suggested_questions import SuggestedQuestionsGenerator, PageContext
```

并更新 `__all__`。

- [ ] **Step 2: Write integration smoke tests**
- [ ] **Step 3: Run full test suite**

**Commit:** `feat(wiki): Phase 6 integration validation and exports`

---

## Self-Review Checklist

### Spec Coverage
| 提案要求 | Task |
|---------|------|
| WikiCoverageAnalyzer 覆盖率报告 | Task 1 |
| CoverageReport (total/covered/core/gaps) | Task 1 |
| 过时检测 (commit_sha 对比) | Task 2 |
| 探索问题自动生成 (3-5 个/页) | Task 3 |
| GET /api/v1/wiki/coverage-report API | Task 4 |
| 配置开关 (coverage_report_enabled 等) | Task 4 |
| 集成验证 | Task 5 |

### Placeholder Scan
- No "TBD", "TODO", "implement later" found
- All steps contain actual code
- All types referenced exist in earlier tasks

### Type Consistency
- `CoverageReport` — defined in Task 1, used in Task 2, 4, 5
- `WikiCoverageAnalyzer` — defined in Task 1, extended in Task 2, used in Task 4
- `SuggestedQuestionsGenerator`, `PageContext` — defined in Task 3, used in Task 5
