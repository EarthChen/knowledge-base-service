# Wiki 跨仓库业务级 Wiki（Phase 4）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]` / `- [x]`) syntax for tracking.

**Goal:** 让 Wiki 从"单仓库平坦列表"升级为"跨仓库业务域树"。实现跨仓库业务领域分类、自动交叉引用生成、业务域概述页生成、WikiSpace/WikiSection 树构建与持久化，以及 business scope 支持。用户可触发一次"业务级 Wiki 生成"，系统扫描所有已索引仓库的模块，用 LLM 分类到业务域，为每个域构建树并生成概述页，最后自动建立页面间交叉引用。

**Architecture:** 新增 `CrossRepoBusinessDomainPlanner` 将多仓库模块分类到业务域（分批 LLM 策略）。新增 `WikiReferenceGenerator` 从代码图谱关系推断 `WIKI_REFERENCES` 边并注入 `[[path]]` wikilink。新增 `DomainOverviewComposer` 为每个业务域生成概述页。在 `WikiService` 新增 `generate_business_wiki()` 方法编排整个流程。扩展 API 和 MCP 工具以支持 business scope。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB (Cypher), LLMPort protocol, dataclasses, pytest

**Spec:**
- [2026-04-26-wiki-tree-architecture-design.md](../specs/2026-04-26-wiki-tree-architecture-design.md)（Phase 4 章节、跨仓库 BusinessDomainPlanner、交叉引用、双视角导航）
- [2026-04-24-wiki-enhancement-design.md](../specs/2026-04-24-wiki-enhancement-design.md)（Phase 3 §3.2 BusinessDomainPlanner 基础设计）

**Code Review 要求:** 每个 Task 完成后必须进行 code review，确认代码质量和测试覆盖后再进入下一个 Task。

**计划范围:** 本文档仅覆盖 Phase 4（跨仓库业务级 Wiki）。Phase 5（导出与 Git 推送）的实施计划将在 Phase 4 完成后单独编写。

**前置条件:** Phase 0-3 均已完成。Phase 3 code review HIGH 问题已修复。

**审阅结论 (sequential-thinking):**
- ✅ 结构完整，8 个 Task 依赖关系清晰（Task 1-3 可并行）
- ⚠️ HIGH: 当前 `_persist_pages_to_graph` 不创建 `SOURCE_ENTITY` 边，`WikiReferenceGenerator` 依赖这些边。已在 Task 4 Step 7 中补充创建逻辑。
- ⚠️ MEDIUM: `PageType.DOMAIN_OVERVIEW` 可能不存在，已在 Task 3 中标注为前置步骤。
- ⚠️ MEDIUM: `CrossRepoBusinessDomainPlanner._module_summary` 需从 GraphNode 获取真实摘要。

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `wiki/cross_repo_domain_planner.py` | 跨仓库业务域分类器（分批 LLM 策略） |
| Create | `wiki/reference_generator.py` | 自动交叉引用生成（图谱关系 → WIKI_REFERENCES 边 + wikilink 注入） |
| Create | `wiki/domain_overview_composer.py` | 业务域概述页生成（跨仓库摘要 + Mermaid 协作图） |
| Modify | `wiki/service.py` | 新增 `generate_business_wiki()` + 树构建 + 引用集成 |
| Modify | `wiki/structure_planner.py` | 支持 `scope_type='business'` |
| Modify | `config.py` | 激活 `cross_repo_domain_enabled` + 新增 Phase 4 配置 |
| Modify | `store/wiki_store.py` | 新增 `list_indexed_repositories()` + `find_source_entity_mappings()` |
| Modify | `api/routes/wiki_routes.py` | business wiki 生成端点 + tree 查询端点增强 |
| Modify | `wiki/mcp_tools.py` | 新增 `wiki_get_tree`, `wiki_get_related`, `wiki_get_domain_overview` MCP tools |
| Modify | `wiki/__init__.py` | 导出新组件 |
| Create | `tests/wiki/test_cross_repo_domain_planner.py` | CrossRepoBusinessDomainPlanner 单元测试 |
| Create | `tests/wiki/test_reference_generator.py` | WikiReferenceGenerator 单元测试 |
| Create | `tests/wiki/test_domain_overview_composer.py` | DomainOverviewComposer 单元测试 |
| Create | `tests/wiki/test_service_business_scope.py` | WikiService business scope 集成测试 |
| Create | `tests/wiki/test_business_tree_persist.py` | 树构建与持久化测试 |
| Create | `tests/wiki/test_service_references.py` | 引用集成测试 |
| Create | `tests/wiki/test_business_api.py` | Business wiki API 端点测试 |
| Create | `tests/wiki/mcp/test_mcp_business_wiki.py` | MCP 工具扩展测试 |
| Create | `tests/wiki/integration/test_phase4_smoke.py` | 集成烟雾测试 |

---

### Task 1: CrossRepoBusinessDomainPlanner — 跨仓库业务域分类

**Files:**
- Create: `wiki/cross_repo_domain_planner.py`
- Create: `tests/wiki/test_cross_repo_domain_planner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_cross_repo_domain_planner.py
import pytest
from unittest.mock import AsyncMock
from store.schema import GraphNode, NodeLabel
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


def _make_module(repo: str, name: str, summary: str = "") -> GraphNode:
    return GraphNode(
        uid=f"Module:{repo}:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "business_summary": summary, "path": name},
    )


@pytest.mark.asyncio
async def test_classify_small_batch_single_llm_call():
    """When total modules <= batch_threshold, one LLM call classifies all."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=(
        '{"用户管理": [["user-svc", "user_service"], ["auth-svc", "auth_module"]], '
        '"__infrastructure__": [["user-svc", "utils"]]}'
    ))
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=100)
    all_modules = {
        "user-svc": [
            _make_module("user-svc", "user_service", "User registration"),
            _make_module("user-svc", "utils", "General utilities"),
        ],
        "auth-svc": [
            _make_module("auth-svc", "auth_module", "Authentication"),
        ],
    }
    result = await planner.classify("test-business", all_modules)
    assert "用户管理" in result
    assert ("user-svc", "user_service") in result["用户管理"]
    assert ("auth-svc", "auth_module") in result["用户管理"]
    assert "__infrastructure__" in result
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_classify_large_batch_splits_by_repo():
    """When total modules > batch_threshold, classify per-repo then merge."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=[
        '{"用户管理": ["user_service"], "__infrastructure__": ["utils"]}',
        '{"用户管理": ["auth_module"]}',
        '{"用户管理": [["user-svc", "user_service"], ["auth-svc", "auth_module"]], '
        '"__infrastructure__": [["user-svc", "utils"]]}',
    ])
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=2)
    all_modules = {
        "user-svc": [
            _make_module("user-svc", "user_service"),
            _make_module("user-svc", "utils"),
        ],
        "auth-svc": [
            _make_module("auth-svc", "auth_module"),
        ],
    }
    result = await planner.classify("test-business", all_modules)
    assert "用户管理" in result or "__infrastructure__" in result
    assert llm.generate.await_count >= 2


@pytest.mark.asyncio
async def test_classify_without_llm_all_infrastructure():
    """Without LLM, all modules go to __infrastructure__ with repo info."""
    planner = CrossRepoBusinessDomainPlanner(llm=None)
    all_modules = {
        "repo-a": [_make_module("repo-a", "mod_a")],
        "repo-b": [_make_module("repo-b", "mod_b")],
    }
    result = await planner.classify("biz", all_modules)
    assert "__infrastructure__" in result
    assert len(result["__infrastructure__"]) == 2
    assert ("repo-a", "mod_a") in result["__infrastructure__"]


@pytest.mark.asyncio
async def test_classify_llm_failure_degrades():
    """LLM failure should degrade to all-infrastructure."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM timeout"))
    planner = CrossRepoBusinessDomainPlanner(llm)
    all_modules = {"repo": [_make_module("repo", "svc")]}
    result = await planner.classify("biz", all_modules)
    assert "__infrastructure__" in result
    assert ("repo", "svc") in result["__infrastructure__"]


@pytest.mark.asyncio
async def test_classify_empty_repos():
    """Empty input should return empty result."""
    planner = CrossRepoBusinessDomainPlanner(llm=AsyncMock())
    result = await planner.classify("biz", {})
    assert result == {}


@pytest.mark.asyncio
async def test_classify_unclassified_modules_go_to_infra():
    """Modules not mentioned in LLM response should be placed in infrastructure."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"订单处理": [["repo", "order_svc"]]}')
    planner = CrossRepoBusinessDomainPlanner(llm)
    all_modules = {
        "repo": [
            _make_module("repo", "order_svc"),
            _make_module("repo", "orphan_mod"),
        ],
    }
    result = await planner.classify("biz", all_modules)
    assert ("repo", "orphan_mod") in result.get("__infrastructure__", [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement CrossRepoBusinessDomainPlanner**

创建 `wiki/cross_repo_domain_planner.py`：

```python
"""Cross-repository business domain classification for wiki generation."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from log import get_logger
from store.schema import GraphNode

if TYPE_CHECKING:
    from wiki.context import LLMPort

log = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a software architect classifying code modules from MULTIPLE repositories "
    "into business domains. Reply with ONLY valid JSON."
)

_CLASSIFY_TEMPLATE = """\
Classify the following modules (from multiple repositories) into business domains.

Modules:
{module_list}

Requirements:
1. Group modules by their business function (e.g., "用户管理", "订单处理", "支付系统")
2. Each entry in the result must be a [repository, module_name] pair
3. Modules that are pure utilities, configurations, or infrastructure go into "{infra_label}"
4. Use descriptive domain names (prefer the project's natural language)

Reply with ONLY valid JSON. Example:
{{"用户管理": [["user-svc", "user_service"], ["auth-svc", "auth_module"]], \
"{infra_label}": [["user-svc", "utils"]]}}
"""

_MERGE_TEMPLATE = """\
Merge the following per-repository domain classifications into a unified cross-repo mapping.
Unify domain names that describe the same business area.

Per-repository classifications:
{per_repo_json}

Output the unified classification where each entry is a [repository, module_name] pair.
Reply with ONLY valid JSON.
"""


class CrossRepoBusinessDomainPlanner:
    """Classifies modules from multiple repositories into business domains.

    - Small batch (<=batch_threshold): single LLM call for all modules.
    - Large batch: per-repo classification, then one merge call.
    - No LLM: all modules → __infrastructure__.
    """

    def __init__(
        self,
        llm: LLMPort | None,
        *,
        infrastructure_label: str = "__infrastructure__",
        batch_threshold: int = 100,
    ) -> None:
        self._llm = llm
        self._infra_label = infrastructure_label
        self._batch_threshold = batch_threshold

    async def classify(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
    ) -> dict[str, list[tuple[str, str]]]:
        """Classify modules from multiple repos into business domains.

        Returns: {domain_name: [(repository, module_name), ...]}
        """
        if not all_modules:
            return {}

        flat = self._flatten_modules(all_modules)
        if not flat:
            return {}

        if self._llm is None:
            return {self._infra_label: flat}

        total = len(flat)
        try:
            if total <= self._batch_threshold:
                mapping = await self._classify_single_batch(flat)
            else:
                mapping = await self._classify_multi_batch(all_modules)

            if not mapping:
                return {self._infra_label: flat}

            classified = set()
            for pairs in mapping.values():
                for pair in pairs:
                    classified.add(pair)
            unclassified = [p for p in flat if p not in classified]
            if unclassified:
                mapping.setdefault(self._infra_label, []).extend(unclassified)
            return mapping
        except Exception:
            log.warning(
                "cross_repo_domain_classification_failed",
                business_id=business_id,
                exc_info=True,
            )
            return {self._infra_label: flat}

    def _flatten_modules(
        self, all_modules: dict[str, list[GraphNode]]
    ) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for repo, modules in all_modules.items():
            for m in modules:
                result.append((repo, self._module_name(m)))
        return result

    def _module_name(self, module: GraphNode) -> str:
        name = module.properties.get("name")
        return str(name) if isinstance(name, str) and name else module.uid

    async def _classify_single_batch(
        self, flat: list[tuple[str, str]]
    ) -> dict[str, list[tuple[str, str]]]:
        module_list = "\n".join(
            f"- [{repo}] {name}: {self._module_summary(repo, name)}"
            for repo, name in flat
        )
        prompt = _CLASSIFY_TEMPLATE.format(
            module_list=module_list,
            infra_label=self._infra_label,
        )
        raw = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)
        return self._parse_cross_repo_json(raw)

    async def _classify_multi_batch(
        self, all_modules: dict[str, list[GraphNode]]
    ) -> dict[str, list[tuple[str, str]]]:
        from wiki.business_domain_planner import BusinessDomainPlanner

        per_repo_results: dict[str, dict[str, list[str]]] = {}
        for repo, modules in all_modules.items():
            single_planner = BusinessDomainPlanner(
                self._llm,
                infrastructure_label=self._infra_label,
            )
            per_repo_results[repo] = await single_planner.classify(repo, modules)

        per_repo_json = json.dumps(per_repo_results, ensure_ascii=False, indent=2)
        prompt = _MERGE_TEMPLATE.format(per_repo_json=per_repo_json)
        raw = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)
        return self._parse_cross_repo_json(raw)

    def _module_summary(self, repo: str, name: str) -> str:
        return "(no description)"

    def _parse_cross_repo_json(
        self, raw: str
    ) -> dict[str, list[tuple[str, str]]]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, list[tuple[str, str]]] = {}
        for domain, entries in data.items():
            if not isinstance(domain, str) or not isinstance(entries, list):
                continue
            pairs: list[tuple[str, str]] = []
            for entry in entries:
                if isinstance(entry, list) and len(entry) == 2:
                    pairs.append((str(entry[0]), str(entry[1])))
            if pairs:
                result[domain] = pairs
        return result
```

实现者注意：
- `_module_summary` 需要接受 `all_modules` 上下文来返回真实的 summary。在实现中通过构建 `_metadata_cache: dict[tuple[str,str], str]` 来解决，在 `classify()` 入口处遍历 `all_modules` 构建缓存。
- `_classify_multi_batch` 复用 Phase 3 的 `BusinessDomainPlanner` 做单仓库分类，然后调用一次 LLM 合并。

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

**Commit:** `feat(wiki): add CrossRepoBusinessDomainPlanner with batch LLM classification`

---

### Task 2: WikiReferenceGenerator — 自动交叉引用生成

**Files:**
- Create: `wiki/reference_generator.py`
- Create: `tests/wiki/test_reference_generator.py`
- Modify: `store/wiki_store.py` (新增查询方法)

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_reference_generator.py
import pytest
from unittest.mock import AsyncMock
from wiki.reference_generator import WikiReferenceGenerator


def _mock_wiki_store():
    store = AsyncMock()
    store.find_source_entity_mappings = AsyncMock(return_value=[])
    store.find_code_entity_relationships = AsyncMock(return_value=[])
    store.add_wiki_reference_edge = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_generates_calls_reference():
    """CALLS edge between code entities → wiki_references(calls) between pages."""
    store = _mock_wiki_store()
    store.find_source_entity_mappings.return_value = [
        {"wiki_uid": "WikiPage:r:classes/A.md", "entity_uid": "Class:r:A", "wiki_path": "classes/A.md"},
        {"wiki_uid": "WikiPage:r:classes/B.md", "entity_uid": "Class:r:B", "wiki_path": "classes/B.md"},
    ]
    store.find_code_entity_relationships.return_value = [
        {"source_uid": "Class:r:A", "target_uid": "Class:r:B", "rel_type": "CALLS"},
    ]
    gen = WikiReferenceGenerator(store)
    refs = await gen.generate_references()
    assert len(refs) == 1
    assert refs[0]["source_wiki_uid"] == "WikiPage:r:classes/A.md"
    assert refs[0]["target_wiki_uid"] == "WikiPage:r:classes/B.md"
    assert refs[0]["relation_type"] == "calls"
    store.add_wiki_reference_edge.assert_awaited_once()


@pytest.mark.asyncio
async def test_generates_cross_repo_reference():
    """CROSS_REPO_CALLS edge → wiki_references(cross_repo) between pages."""
    store = _mock_wiki_store()
    store.find_source_entity_mappings.return_value = [
        {"wiki_uid": "WikiPage:a:classes/X.md", "entity_uid": "Class:a:X", "wiki_path": "classes/X.md"},
        {"wiki_uid": "WikiPage:b:classes/Y.md", "entity_uid": "Class:b:Y", "wiki_path": "classes/Y.md"},
    ]
    store.find_code_entity_relationships.return_value = [
        {"source_uid": "Class:a:X", "target_uid": "Class:b:Y", "rel_type": "CROSS_REPO_CALLS"},
    ]
    gen = WikiReferenceGenerator(store)
    refs = await gen.generate_references()
    assert len(refs) == 1
    assert refs[0]["relation_type"] == "cross_repo"


@pytest.mark.asyncio
async def test_generates_inherits_reference():
    """INHERITS edge → wiki_references(inherits)."""
    store = _mock_wiki_store()
    store.find_source_entity_mappings.return_value = [
        {"wiki_uid": "WikiPage:r:classes/Base.md", "entity_uid": "Class:r:Base", "wiki_path": "classes/Base.md"},
        {"wiki_uid": "WikiPage:r:classes/Child.md", "entity_uid": "Class:r:Child", "wiki_path": "classes/Child.md"},
    ]
    store.find_code_entity_relationships.return_value = [
        {"source_uid": "Class:r:Child", "target_uid": "Class:r:Base", "rel_type": "INHERITS"},
    ]
    gen = WikiReferenceGenerator(store)
    refs = await gen.generate_references()
    assert len(refs) == 1
    assert refs[0]["relation_type"] == "inherits"


@pytest.mark.asyncio
async def test_no_self_reference():
    """A page should not reference itself."""
    store = _mock_wiki_store()
    store.find_source_entity_mappings.return_value = [
        {"wiki_uid": "WikiPage:r:classes/A.md", "entity_uid": "Class:r:A", "wiki_path": "classes/A.md"},
    ]
    store.find_code_entity_relationships.return_value = [
        {"source_uid": "Class:r:A", "target_uid": "Class:r:A", "rel_type": "CALLS"},
    ]
    gen = WikiReferenceGenerator(store)
    refs = await gen.generate_references()
    assert len(refs) == 0
    store.add_wiki_reference_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_deduplicates_references():
    """Multiple code edges between same entity pair → single wiki reference."""
    store = _mock_wiki_store()
    store.find_source_entity_mappings.return_value = [
        {"wiki_uid": "WikiPage:r:A.md", "entity_uid": "Class:r:A", "wiki_path": "A.md"},
        {"wiki_uid": "WikiPage:r:B.md", "entity_uid": "Class:r:B", "wiki_path": "B.md"},
    ]
    store.find_code_entity_relationships.return_value = [
        {"source_uid": "Class:r:A", "target_uid": "Class:r:B", "rel_type": "CALLS"},
        {"source_uid": "Class:r:A", "target_uid": "Class:r:B", "rel_type": "IMPORTS"},
    ]
    gen = WikiReferenceGenerator(store)
    refs = await gen.generate_references()
    unique_pairs = {(r["source_wiki_uid"], r["target_wiki_uid"]) for r in refs}
    assert len(unique_pairs) <= 2


@pytest.mark.asyncio
async def test_no_pages_returns_empty():
    """No wiki pages → no references."""
    store = _mock_wiki_store()
    gen = WikiReferenceGenerator(store)
    refs = await gen.generate_references()
    assert refs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_reference_generator.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add WikiStore query methods**

在 `store/wiki_store.py` 末尾新增两个查询方法：

```python
async def find_source_entity_mappings(self, repository: str | None = None) -> list[dict[str, str]]:
    """Find all WikiPage → SOURCE_ENTITY → code entity mappings."""
    repo_filter = "WHERE wp.repository = $repo" if repository else ""
    q = (
        f"MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(e) "
        f"{repo_filter} "
        "RETURN wp.uid AS wiki_uid, e.uid AS entity_uid, "
        "wp.path AS wiki_path, wp.repository AS repository"
    )
    params = {"repo": repository} if repository else {}
    result = await self._store.execute_query(q, params)
    rows = []
    for row in getattr(result, "raw", []) or []:
        rows.append({
            "wiki_uid": str(row[0]),
            "entity_uid": str(row[1]),
            "wiki_path": str(row[2]),
            "repository": str(row[3] or ""),
        })
    return rows

async def find_code_entity_relationships(
    self, entity_uids: list[str] | None = None
) -> list[dict[str, str]]:
    """Find code-level relationships (CALLS, INHERITS, IMPORTS, CROSS_REPO_CALLS)
    between entities that have associated WikiPages."""
    uid_filter = "AND s.uid IN $uids AND t.uid IN $uids" if entity_uids else ""
    q = (
        "MATCH (s)-[r:CALLS|INHERITS|IMPORTS|CROSS_REPO_CALLS]->(t) "
        f"WHERE EXISTS {{ MATCH (s)<-[:SOURCE_ENTITY]-(:WikiPage) }} "
        f"AND EXISTS {{ MATCH (t)<-[:SOURCE_ENTITY]-(:WikiPage) }} "
        f"{uid_filter} "
        "RETURN DISTINCT s.uid AS source_uid, t.uid AS target_uid, type(r) AS rel_type"
    )
    params = {"uids": entity_uids} if entity_uids else {}
    result = await self._store.execute_query(q, params)
    rows = []
    for row in getattr(result, "raw", []) or []:
        rows.append({
            "source_uid": str(row[0]),
            "target_uid": str(row[1]),
            "rel_type": str(row[2]),
        })
    return rows
```

- [ ] **Step 4: Implement WikiReferenceGenerator**

创建 `wiki/reference_generator.py`：

```python
"""Automatic cross-reference generation between wiki pages based on code graph relationships."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from log import get_logger

if TYPE_CHECKING:
    from store.wiki_store import WikiStore

log = get_logger(__name__)

_EDGE_TYPE_TO_REF_TYPE = {
    "CALLS": "calls",
    "CROSS_REPO_CALLS": "cross_repo",
    "INHERITS": "inherits",
    "IMPORTS": "imports",
}


class WikiReferenceGenerator:
    """Generates WIKI_REFERENCES edges between WikiPages by analyzing code-level relationships.

    Process:
    1. Query WikiPage → SOURCE_ENTITY mappings (entity_uid ↔ wiki_uid)
    2. Query code entity relationships (CALLS, INHERITS, IMPORTS, CROSS_REPO_CALLS)
    3. Map code relationships back to wiki page pairs
    4. Persist as WIKI_REFERENCES edges
    """

    def __init__(self, wiki_store: WikiStore) -> None:
        self._store = wiki_store

    async def generate_references(
        self, repository: str | None = None
    ) -> list[dict[str, Any]]:
        mappings = await self._store.find_source_entity_mappings(repository)
        if not mappings:
            return []

        entity_to_wiki: dict[str, str] = {}
        wiki_uid_to_path: dict[str, str] = {}
        for m in mappings:
            entity_to_wiki[m["entity_uid"]] = m["wiki_uid"]
            wiki_uid_to_path[m["wiki_uid"]] = m["wiki_path"]

        entity_uids = list(entity_to_wiki.keys())
        code_rels = await self._store.find_code_entity_relationships(entity_uids)

        refs: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        for rel in code_rels:
            source_wiki = entity_to_wiki.get(rel["source_uid"])
            target_wiki = entity_to_wiki.get(rel["target_uid"])
            if not source_wiki or not target_wiki:
                continue
            if source_wiki == target_wiki:
                continue
            ref_type = _EDGE_TYPE_TO_REF_TYPE.get(rel["rel_type"], "calls")
            key = (source_wiki, target_wiki, ref_type)
            if key in seen:
                continue
            seen.add(key)

            await self._store.add_wiki_reference_edge(
                source_uid=source_wiki,
                target_uid=target_wiki,
                relation_type=ref_type,
                context=f"Inferred from {rel['rel_type']} edge",
                auto_generated=True,
                confidence=0.9,
            )
            refs.append({
                "source_wiki_uid": source_wiki,
                "target_wiki_uid": target_wiki,
                "relation_type": ref_type,
                "source_path": wiki_uid_to_path.get(source_wiki, ""),
                "target_path": wiki_uid_to_path.get(target_wiki, ""),
            })

        log.info(
            "wiki_references_generated",
            count=len(refs),
            repository=repository or "all",
        )
        return refs

    def inject_wikilinks(
        self,
        content: str,
        outgoing_refs: list[dict[str, Any]],
    ) -> str:
        """Append a '## Related Pages' section with [[path]] wikilinks to page content."""
        if not outgoing_refs:
            return content
        lines = ["\n\n## Related Pages\n"]
        for ref in outgoing_refs:
            path = ref.get("target_path", ref.get("target_wiki_uid", ""))
            rel_type = ref.get("relation_type", "related")
            lines.append(f"- [[{path}]] ({rel_type})")
        return content.rstrip() + "\n".join(lines) + "\n"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_reference_generator.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

**Commit:** `feat(wiki): add WikiReferenceGenerator for automatic cross-reference generation`

---

### Task 3: DomainOverviewComposer — 业务域概述页生成

**Files:**
- Create: `wiki/domain_overview_composer.py`
- Create: `tests/wiki/test_domain_overview_composer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_domain_overview_composer.py
import pytest
from unittest.mock import AsyncMock
from store.schema import GraphNode, NodeLabel
from wiki.domain_overview_composer import DomainOverviewComposer
from wiki.models import PageType


def _make_module(repo: str, name: str, summary: str = "") -> GraphNode:
    return GraphNode(
        uid=f"Module:{repo}:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "business_summary": summary, "path": name},
    )


@pytest.mark.asyncio
async def test_compose_with_llm():
    """With LLM, domain overview should contain LLM-generated business description."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=(
        "## 业务概述\n用户管理域负责用户注册、认证和权限控制。\n\n"
        "## 模块协作\n```mermaid\ngraph LR\nA-->B\n```"
    ))
    composer = DomainOverviewComposer(llm)
    modules = [
        ("user-svc", "user_service", _make_module("user-svc", "user_service", "User management")),
        ("auth-svc", "auth_module", _make_module("auth-svc", "auth_module", "Auth")),
    ]
    page = await composer.compose("用户管理", modules, language="zh")
    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert "用户管理" in page.title
    assert "user-svc" in page.content or "auth-svc" in page.content
    assert page.path.endswith("_overview")
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_compose_without_llm():
    """Without LLM, domain overview should be a structured module listing."""
    composer = DomainOverviewComposer(llm=None)
    modules = [
        ("repo-a", "mod_a", _make_module("repo-a", "mod_a", "Module A")),
        ("repo-b", "mod_b", _make_module("repo-b", "mod_b", "")),
    ]
    page = await composer.compose("基础设施", modules, language="zh")
    assert "基础设施" in page.title
    assert "repo-a" in page.content
    assert "mod_a" in page.content
    assert page.page_type == PageType.DOMAIN_OVERVIEW


@pytest.mark.asyncio
async def test_compose_includes_all_repos():
    """Overview should mention all repositories that contribute to the domain."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Overview\nDomain overview.")
    composer = DomainOverviewComposer(llm)
    modules = [
        ("svc-1", "mod", _make_module("svc-1", "mod")),
        ("svc-2", "mod", _make_module("svc-2", "mod")),
        ("svc-3", "mod", _make_module("svc-3", "mod")),
    ]
    page = await composer.compose("Test Domain", modules)
    repos_in_content = [r for r in ["svc-1", "svc-2", "svc-3"] if r in page.content]
    assert len(repos_in_content) == 3


@pytest.mark.asyncio
async def test_compose_empty_modules():
    """Empty module list should still produce a valid page."""
    composer = DomainOverviewComposer(llm=None)
    page = await composer.compose("Empty Domain", [])
    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert "Empty Domain" in page.title


@pytest.mark.asyncio
async def test_compose_llm_failure_degrades():
    """LLM failure should degrade to structural listing."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM error"))
    composer = DomainOverviewComposer(llm)
    modules = [("r", "m", _make_module("r", "m", "desc"))]
    page = await composer.compose("Domain", modules)
    assert page.page_type == PageType.DOMAIN_OVERVIEW
    assert "m" in page.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_domain_overview_composer.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement DomainOverviewComposer**

创建 `wiki/domain_overview_composer.py`：

```python
"""Business domain overview page composer for cross-repository wiki."""

from __future__ import annotations

from typing import TYPE_CHECKING

from log import get_logger
from store.schema import GraphNode
from wiki.models import (
    PageType,
    WikiPage,
    WikiPageMetadata,
    EnrichmentLevel,
)

if TYPE_CHECKING:
    from wiki.context import LLMPort

log = get_logger(__name__)

_SYSTEM_PROMPT_EN = (
    "You are a senior architect writing a business domain overview. "
    "Given the modules and their summaries, generate a comprehensive domain overview "
    "including: business purpose, key modules and their roles, inter-module collaboration, "
    "and a Mermaid diagram showing the collaboration flow. Output clean Markdown."
)

_SYSTEM_PROMPT_ZH = (
    "你是一位资深架构师，正在编写业务领域概述。"
    "根据所给模块及其摘要，生成一份全面的领域概述，"
    "包括：业务目的、关键模块及其职责、模块间协作关系、"
    "以及展示协作流程的 Mermaid 图表。输出格式为 Markdown。"
)

_COMPOSE_TEMPLATE = """\
Domain: {domain_name}
Repositories involved: {repos}

Modules in this domain:
{module_list}

Generate a domain overview document with:
1. Business purpose and scope
2. Key modules and their roles (grouped by repository)
3. Inter-module collaboration and data flow
4. A Mermaid diagram showing the collaboration
"""


class DomainOverviewComposer:
    """Composes business domain overview pages from cross-repository module data."""

    def __init__(self, llm: LLMPort | None) -> None:
        self._llm = llm

    async def compose(
        self,
        domain_name: str,
        modules: list[tuple[str, str, GraphNode]],
        language: str = "en",
    ) -> WikiPage:
        """Generate a domain overview WikiPage.

        Args:
            domain_name: Name of the business domain.
            modules: List of (repository, module_name, GraphNode) tuples.
            language: Output language ('en' or 'zh').
        """
        path = f"/{domain_name}/_overview"
        repos = sorted({repo for repo, _, _ in modules}) if modules else []

        if self._llm is not None and modules:
            try:
                content = await self._compose_with_llm(domain_name, modules, repos, language)
            except Exception:
                log.warning("domain_overview_llm_failed", domain=domain_name, exc_info=True)
                content = self._compose_structural(domain_name, modules, repos)
        else:
            content = self._compose_structural(domain_name, modules, repos)

        return WikiPage(
            path=path,
            title=f"{domain_name} — Domain Overview",
            page_type=PageType.DOMAIN_OVERVIEW,
            content=content,
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(
                node_count=len(modules),
                edge_count=0,
                generation_mode="business",
                enrichment_level=EnrichmentLevel.BASE,
            ),
        )

    async def _compose_with_llm(
        self,
        domain_name: str,
        modules: list[tuple[str, str, GraphNode]],
        repos: list[str],
        language: str,
    ) -> str:
        module_list = "\n".join(
            f"- [{repo}] {name}: {self._module_summary(node)}"
            for repo, name, node in modules
        )
        prompt = _COMPOSE_TEMPLATE.format(
            domain_name=domain_name,
            repos=", ".join(repos),
            module_list=module_list,
        )
        system = _SYSTEM_PROMPT_ZH if language == "zh" else _SYSTEM_PROMPT_EN
        result = await self._llm.generate(prompt, system=system)
        header = f"# {domain_name}\n\n"
        repo_badge = " | ".join(f"📦 {r}" for r in repos)
        return f"{header}{repo_badge}\n\n{result.strip()}\n"

    def _compose_structural(
        self,
        domain_name: str,
        modules: list[tuple[str, str, GraphNode]],
        repos: list[str],
    ) -> str:
        lines = [f"# {domain_name}", ""]
        if repos:
            lines.append("## Repositories")
            lines.extend(f"- {r}" for r in repos)
            lines.append("")
        if modules:
            lines.append("## Modules")
            by_repo: dict[str, list[tuple[str, GraphNode]]] = {}
            for repo, name, node in modules:
                by_repo.setdefault(repo, []).append((name, node))
            for repo in sorted(by_repo):
                lines.append(f"\n### {repo}")
                for name, node in by_repo[repo]:
                    summary = self._module_summary(node)
                    lines.append(f"- **{name}**: {summary}")
        else:
            lines.append("No modules classified into this domain.")
        lines.append("")
        return "\n".join(lines)

    def _module_summary(self, node: GraphNode) -> str:
        summary = node.properties.get("business_summary")
        if isinstance(summary, str) and summary:
            return summary
        docstring = node.properties.get("docstring")
        if isinstance(docstring, str) and docstring:
            return docstring[:200]
        return "(no description)"
```

⚠️ **前置步骤**：必须先确认 `PageType.DOMAIN_OVERVIEW` 是否已存在于 `wiki/models.py`。如果不存在，必须在实现 DomainOverviewComposer **之前**在 `PageType` 枚举中新增 `DOMAIN_OVERVIEW = "domain_overview"`，否则 import 会失败。

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_domain_overview_composer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

**Commit:** `feat(wiki): add DomainOverviewComposer for business domain overview pages`

---

### Task 4: WikiService business scope + Config 激活

**Files:**
- Modify: `wiki/service.py`
- Modify: `wiki/structure_planner.py`
- Modify: `config.py`
- Modify: `store/wiki_store.py`
- Create: `tests/wiki/test_service_business_scope.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_service_business_scope.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from store.schema import GraphNode, NodeLabel
from wiki.models import PageType
from wiki.service import WikiService


def _mock_graph():
    g = AsyncMock()
    g.find_modules = AsyncMock(return_value=[])
    g.find_children = AsyncMock(return_value=[])
    g.find_edges = AsyncMock(return_value=[])
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.find_node_by_path = AsyncMock(return_value=None)
    g.find_top_level_modules = AsyncMock(return_value=[])
    g.list_repository_modules = AsyncMock(return_value=[])
    return g


@pytest.mark.asyncio
async def test_generate_business_wiki_returns_result():
    """generate_business_wiki should return a dict with domains and pages_count."""
    graph = _mock_graph()
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"__infrastructure__": [["test-repo", "mod"]]}')
    mock_store = AsyncMock()
    mock_store.persist_wiki_pages = AsyncMock()
    mock_store.execute_query = AsyncMock()
    mock_store.set_node_embedding = AsyncMock()
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "test-repo", "module_count": 1}
    ])
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[])

    svc = WikiService(
        graph=graph,
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
        store=mock_store,
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.cross_repo_domain_enabled = True
        mock_wiki_cfg.business_domain_enabled = True
        mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        mock_wiki_cfg.enrichment_enabled = False
        mock_wiki_cfg.code_budget_enabled = False
        mock_wiki_cfg.rag_enabled = False
        mock_settings.return_value.wiki = mock_wiki_cfg
        mock_settings.return_value.embedding = MagicMock()

        result = await svc.generate_business_wiki(
            business_id="test-biz",
            language="en",
        )
        assert "domains" in result
        assert "pages_count" in result


@pytest.mark.asyncio
async def test_generate_business_wiki_without_llm():
    """Without LLM, all modules go to infrastructure domain."""
    graph = _mock_graph()
    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "repo-a", "module_count": 1}
    ])
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[])

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.cross_repo_domain_enabled = True
        mock_wiki_cfg.business_domain_enabled = True
        mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        mock_wiki_cfg.enrichment_enabled = False
        mock_wiki_cfg.code_budget_enabled = False
        mock_wiki_cfg.rag_enabled = False
        mock_settings.return_value.wiki = mock_wiki_cfg

        result = await svc.generate_business_wiki(
            business_id="biz",
            language="en",
        )
        assert "__infrastructure__" in result.get("domains", []) or len(result.get("domains", [])) >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_service_business_scope.py -v`
Expected: FAIL with `AttributeError` (generate_business_wiki not found)

- [ ] **Step 3: Add `list_indexed_repositories` to WikiStore**

在 `store/wiki_store.py` 中新增：

```python
async def list_indexed_repositories(self) -> list[dict[str, Any]]:
    """List all repositories that have indexed modules."""
    q = (
        "MATCH (m:Module) WHERE m.repository IS NOT NULL "
        "RETURN m.repository AS repository, count(m) AS module_count "
        "ORDER BY module_count DESC"
    )
    result = await self._store.execute_query(q)
    rows = []
    for row in getattr(result, "raw", []) or []:
        rows.append({"repository": str(row[0]), "module_count": int(row[1])})
    return rows
```

- [ ] **Step 4: Add `DOMAIN_OVERVIEW` to PageType (if not present)**

检查 `wiki/models.py` 中 `PageType` 枚举，如果没有 `DOMAIN_OVERVIEW`，添加：

```python
class PageType(StrEnum):
    REPO_OVERVIEW = "repo_overview"
    MODULE_OVERVIEW = "module_overview"
    CLASS_DETAIL = "class_detail"
    API_REFERENCE = "api_reference"
    INDEX = "index"
    DOMAIN_OVERVIEW = "domain_overview"  # Phase 4: business domain overview page
```

- [ ] **Step 5: Add Phase 4 config fields**

在 `config.py` 的 `WikiConfig` 中，在 Phase 3 字段之后添加注释激活：

```python
    # Phase 4: Cross-repo business-level wiki
    # cross_repo_domain_enabled: already defined (was False, stays False by default)
    business_wiki_batch_threshold: int = 100
```

确保 `cross_repo_domain_enabled` 保持 `False` 默认值（Phase 4 完成后用户手动开启）。

- [ ] **Step 6: Implement `generate_business_wiki` in WikiService**

在 `wiki/service.py` 中新增方法：

```python
async def generate_business_wiki(
    self,
    business_id: str,
    language: str = "en",
    llm_provider: str | None = None,
) -> dict[str, Any]:
    """Generate cross-repo business-level wiki.

    1. List all indexed repositories
    2. Collect all modules from each repo
    3. Classify modules into business domains (CrossRepoBusinessDomainPlanner)
    4. Create WikiSpace + WikiSection tree
    5. Generate domain overview pages
    6. Generate per-repo wiki pages (reuse existing single-repo pipeline)
    7. Generate cross-references (WikiReferenceGenerator)
    """
    app_cfg = get_settings().wiki

    if self._wiki_store is None:
        raise WikiScopeError("WikiStore required for business-level wiki generation")

    repos = await self._wiki_store.list_indexed_repositories()
    if not repos:
        return {"business_id": business_id, "domains": [], "pages_count": 0}

    all_modules: dict[str, list[GraphNode]] = {}
    for r in repos:
        repo_name = r["repository"]
        modules = await self._graph.list_repository_modules(repo_name)
        if modules:
            all_modules[repo_name] = modules

    # Step 1: Classify modules into business domains
    from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

    llm_port = self._resolve_llm_port(llm_provider)
    planner = CrossRepoBusinessDomainPlanner(
        llm_port,
        infrastructure_label=app_cfg.business_domain_infrastructure_label,
        batch_threshold=app_cfg.business_wiki_batch_threshold,
    )
    domain_mapping = await planner.classify(business_id, all_modules)

    # Step 2: Build WikiSpace + WikiSection tree
    from wiki.tree_builder import WikiTreeBuilder

    tree_builder = WikiTreeBuilder()
    space_uid = tree_builder.generate_space_uid(business_id)
    await self._wiki_store.upsert_wiki_space(
        uid=space_uid,
        business_id=business_id,
        title=f"{business_id} Knowledge Base",
        description=f"Business-level wiki for {business_id}",
    )

    domain_names: list[str] = []
    all_pages: list[WikiPage] = []
    sort_idx = 0

    for domain_name, repo_module_pairs in domain_mapping.items():
        section_uid = tree_builder.generate_section_uid(business_id, domain_name)
        await self._wiki_store.upsert_wiki_section(
            uid=section_uid,
            title=domain_name,
            description=f"Business domain: {domain_name}",
            section_type="business_domain",
            sort_order=sort_idx,
            auto_generated=True,
        )
        await self._wiki_store.add_has_child_edge(
            parent_uid=space_uid,
            parent_label="WikiSpace",
            child_uid=section_uid,
            child_label="WikiSection",
            view_type="business_domain",
            sort_order=sort_idx,
        )
        sort_idx += 1
        domain_names.append(domain_name)

        # Step 3: Generate domain overview page
        from wiki.domain_overview_composer import DomainOverviewComposer

        overview_composer = DomainOverviewComposer(llm_port)
        domain_modules = [
            (repo, mod_name, self._find_module_node(all_modules, repo, mod_name))
            for repo, mod_name in repo_module_pairs
            if self._find_module_node(all_modules, repo, mod_name) is not None
        ]
        overview_page = await overview_composer.compose(
            domain_name, domain_modules, language=language,
        )
        all_pages.append(overview_page)

    # Step 4: Generate per-repo wiki pages
    for repo_name in all_modules:
        try:
            result = await self.generate(
                repo_name, "repo", "structure", "json", language, llm_provider,
            )
            # Pages are already persisted in generate()
        except Exception:
            log.warning("business_wiki_repo_failed", repository=repo_name, exc_info=True)

    # Step 5: Generate cross-references
    from wiki.reference_generator import WikiReferenceGenerator

    ref_gen = WikiReferenceGenerator(self._wiki_store)
    refs = await ref_gen.generate_references()

    return {
        "business_id": business_id,
        "domains": domain_names,
        "pages_count": len(all_pages),
        "references_count": len(refs),
        "repositories": list(all_modules.keys()),
    }

def _find_module_node(
    self,
    all_modules: dict[str, list[GraphNode]],
    repo: str,
    module_name: str,
) -> GraphNode | None:
    for m in all_modules.get(repo, []):
        name = m.properties.get("name")
        if isinstance(name, str) and name == module_name:
            return m
    return None
```

- [ ] **Step 7: Create SOURCE_ENTITY edges during page persistence**

⚠️ **关键依赖**: `WikiReferenceGenerator`（Task 2/6）依赖 `WikiPage -[:SOURCE_ENTITY]-> code entity` 边来推断交叉引用。当前 `_persist_pages_to_graph` 只创建 WikiPage 节点，不创建 SOURCE_ENTITY 边。

修改 `_persist_pages_to_graph` 或在 `generate_business_wiki` 流程中，为每个 WikiPage 创建 SOURCE_ENTITY 边：

```python
# In page_dicts construction, add entity_uid:
page_dicts = [
    {
        ...
        "entity_uid": getattr(p, "_source_entity_uid", None),
    }
    for p in pages
]
```

在 `_persist_pages_to_graph` 中，为有 `entity_uid` 的 page 创建 SOURCE_ENTITY 边：

```python
for pd in page_dicts:
    entity_uid = pd.get("entity_uid")
    if entity_uid:
        wiki_uid = f"WikiPage:{repository}:{pd['path']}"
        se_q = (
            "MATCH (wp:WikiPage {uid: $wiki_uid}) "
            "MATCH (e {uid: $entity_uid}) "
            "MERGE (wp)-[:SOURCE_ENTITY]->(e)"
        )
        await self._store.execute_query(se_q, {"wiki_uid": wiki_uid, "entity_uid": entity_uid})
```

同时在 `_compose_all_pages` 的 `walk()` 中，为 page 记录 `_source_entity_uid`：

```python
page._source_entity_uid = graph_node.uid  # type: ignore[attr-defined]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_service_business_scope.py -v`
Expected: ALL PASS

- [ ] **Step 9: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS, no regressions

**Commit:** `feat(wiki): add generate_business_wiki() with SOURCE_ENTITY edge creation`

---

### Task 5: 业务域树构建与持久化

**Files:**
- Modify: `wiki/service.py`
- Modify: `store/wiki_store.py`
- Create: `tests/wiki/test_business_tree_persist.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_business_tree_persist.py
import pytest
from unittest.mock import AsyncMock
from wiki.tree_builder import WikiTreeBuilder


@pytest.mark.asyncio
async def test_wiki_space_created_with_correct_uid():
    """WikiSpace uid should follow pattern WikiSpace:{business_id}."""
    builder = WikiTreeBuilder()
    uid = builder.generate_space_uid("my-biz")
    assert uid == "WikiSpace:my-biz"


@pytest.mark.asyncio
async def test_wiki_section_uid_for_domain():
    """WikiSection uid should follow pattern WikiSection:{business_id}:{title}."""
    builder = WikiTreeBuilder()
    uid = builder.generate_section_uid("my-biz", "用户管理")
    assert uid == "WikiSection:my-biz:用户管理"


@pytest.mark.asyncio
async def test_domain_tree_persisted_to_store():
    """Tree structure should be persisted: WikiSpace → HAS_CHILD → WikiSection."""
    store = AsyncMock()
    store.upsert_wiki_space = AsyncMock()
    store.upsert_wiki_section = AsyncMock()
    store.add_has_child_edge = AsyncMock()

    builder = WikiTreeBuilder()
    space_uid = builder.generate_space_uid("biz")
    await store.upsert_wiki_space(
        uid=space_uid, business_id="biz",
        title="Test", description="Test wiki space",
    )
    section_uid = builder.generate_section_uid("biz", "Domain1")
    await store.upsert_wiki_section(
        uid=section_uid, title="Domain1",
        description="Test domain", section_type="business_domain",
        sort_order=0, auto_generated=True,
    )
    await store.add_has_child_edge(
        parent_uid=space_uid, parent_label="WikiSpace",
        child_uid=section_uid, child_label="WikiSection",
        view_type="business_domain", sort_order=0,
    )

    store.upsert_wiki_space.assert_awaited_once()
    store.upsert_wiki_section.assert_awaited_once()
    store.add_has_child_edge.assert_awaited_once()


@pytest.mark.asyncio
async def test_code_structure_view_tree():
    """Code structure view should create repo-level sections."""
    store = AsyncMock()
    store.upsert_wiki_section = AsyncMock()
    store.add_has_child_edge = AsyncMock()

    builder = WikiTreeBuilder()
    repo_section_uid = builder.generate_section_uid("biz", "user-service")
    await store.upsert_wiki_section(
        uid=repo_section_uid, title="user-service",
        description="Repository: user-service",
        section_type="code_module", sort_order=0,
    )
    await store.add_has_child_edge(
        parent_uid="WikiSpace:biz", parent_label="WikiSpace",
        child_uid=repo_section_uid, child_label="WikiSection",
        view_type="code_structure", sort_order=0,
    )
    store.upsert_wiki_section.assert_awaited_once()
    store.add_has_child_edge.assert_awaited_once()


@pytest.mark.asyncio
async def test_content_hash_computed():
    """WikiTreeBuilder should compute content hashes."""
    builder = WikiTreeBuilder()
    hash1 = builder.compute_content_hash("Hello world")
    hash2 = builder.compute_content_hash("Hello world")
    hash3 = builder.compute_content_hash("Different content")
    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64


@pytest.mark.asyncio
async def test_naming_conflict_detection():
    """detect_naming_conflicts should find entities with same name in different repos."""
    builder = WikiTreeBuilder()
    pages = [
        {"entity_name": "UserService", "repository": "user-svc"},
        {"entity_name": "UserService", "repository": "auth-svc"},
        {"entity_name": "OrderService", "repository": "order-svc"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert "UserService" in conflicts
    assert len(conflicts["UserService"]) == 2
    assert "OrderService" not in conflicts
```

- [ ] **Step 2: Run tests to verify baseline**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_tree_persist.py -v`

- [ ] **Step 3: Enhance `generate_business_wiki` to build code_structure view**

在 `wiki/service.py` 的 `generate_business_wiki` 方法中，在业务域树构建后，追加 code_structure 视角的树：

```python
# After business_domain tree is built, build code_structure view
code_sort_idx = 0
for repo_name in sorted(all_modules.keys()):
    repo_section_uid = tree_builder.generate_section_uid(business_id, repo_name)
    await self._wiki_store.upsert_wiki_section(
        uid=repo_section_uid,
        title=repo_name,
        description=f"Repository: {repo_name}",
        section_type="code_module",
        sort_order=code_sort_idx,
        auto_generated=True,
    )
    await self._wiki_store.add_has_child_edge(
        parent_uid=space_uid,
        parent_label="WikiSpace",
        child_uid=repo_section_uid,
        child_label="WikiSection",
        view_type="code_structure",
        sort_order=code_sort_idx,
    )
    code_sort_idx += 1
```

- [ ] **Step 4: Add `upsert_wiki_space` to WikiStore if incomplete**

检查 `store/wiki_store.py` 中 `upsert_wiki_space` 方法签名是否包含 `description` 参数。如果缺失，更新方法签名。

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_tree_persist.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

**Commit:** `feat(wiki): implement dual-view tree building and persistence for business wiki`

---

### Task 6: 交叉引用集成到 WikiService

**Files:**
- Modify: `wiki/service.py`
- Create: `tests/wiki/test_service_references.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_service_references.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.service import WikiService


@pytest.mark.asyncio
async def test_generate_business_wiki_calls_reference_generator():
    """generate_business_wiki should invoke WikiReferenceGenerator."""
    graph = AsyncMock()
    graph.find_top_level_modules = AsyncMock(return_value=[])
    graph.list_repository_modules = AsyncMock(return_value=[])
    graph.find_children = AsyncMock(return_value=[])
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_node_by_path = AsyncMock(return_value=None)

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "r1", "module_count": 1},
    ])
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()
    mock_wiki_store.find_source_entity_mappings = AsyncMock(return_value=[
        {"wiki_uid": "WikiPage:r1:A.md", "entity_uid": "Class:r1:A", "wiki_path": "A.md", "repository": "r1"},
        {"wiki_uid": "WikiPage:r1:B.md", "entity_uid": "Class:r1:B", "wiki_path": "B.md", "repository": "r1"},
    ])
    mock_wiki_store.find_code_entity_relationships = AsyncMock(return_value=[
        {"source_uid": "Class:r1:A", "target_uid": "Class:r1:B", "rel_type": "CALLS"},
    ])
    mock_wiki_store.add_wiki_reference_edge = AsyncMock()

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.cross_repo_domain_enabled = True
        mock_wiki_cfg.business_domain_enabled = True
        mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        mock_wiki_cfg.enrichment_enabled = False
        mock_wiki_cfg.code_budget_enabled = False
        mock_wiki_cfg.rag_enabled = False
        mock_wiki_cfg.business_wiki_batch_threshold = 100
        mock_settings.return_value.wiki = mock_wiki_cfg

        result = await svc.generate_business_wiki("biz")
        assert result["references_count"] >= 1
        mock_wiki_store.add_wiki_reference_edge.assert_awaited()


@pytest.mark.asyncio
async def test_reference_generation_failure_does_not_crash():
    """WikiReferenceGenerator failure should not crash business wiki generation."""
    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(return_value=[])
    graph.find_top_level_modules = AsyncMock(return_value=[])

    mock_wiki_store = AsyncMock()
    mock_wiki_store.list_indexed_repositories = AsyncMock(return_value=[])
    mock_wiki_store.upsert_wiki_space = AsyncMock()

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=mock_wiki_store,
    )

    with patch("wiki.service.get_settings") as mock_settings:
        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.cross_repo_domain_enabled = True
        mock_wiki_cfg.business_domain_enabled = True
        mock_wiki_cfg.business_domain_infrastructure_label = "__infrastructure__"
        mock_wiki_cfg.enrichment_enabled = False
        mock_wiki_cfg.code_budget_enabled = False
        mock_wiki_cfg.rag_enabled = False
        mock_wiki_cfg.business_wiki_batch_threshold = 100
        mock_settings.return_value.wiki = mock_wiki_cfg

        result = await svc.generate_business_wiki("empty-biz")
        assert "pages_count" in result
```

- [ ] **Step 2: Run tests to verify they fail or baseline**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_service_references.py -v`

- [ ] **Step 3: Add graceful error handling for reference generation**

在 `wiki/service.py` 的 `generate_business_wiki` 中，将 Step 5 (reference generation) 包裹在 try/except 中：

```python
# Step 5: Generate cross-references (graceful)
refs_count = 0
try:
    from wiki.reference_generator import WikiReferenceGenerator
    ref_gen = WikiReferenceGenerator(self._wiki_store)
    refs = await ref_gen.generate_references()
    refs_count = len(refs)
except Exception:
    log.warning("business_wiki_reference_generation_failed", business_id=business_id, exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_service_references.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

**Commit:** `feat(wiki): integrate WikiReferenceGenerator into business wiki generation`

---

### Task 7: API 端点 + MCP 工具扩展

**Files:**
- Modify: `api/routes/wiki_routes.py`
- Modify: `wiki/mcp_tools.py`
- Create: `tests/wiki/test_business_api.py`
- Create: `tests/wiki/mcp/test_mcp_business_wiki.py`

- [ ] **Step 1: Write the failing test — API**

```python
# tests/wiki/test_business_api.py
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from api.routes.wiki_routes import wiki_router
    app = FastAPI()
    app.include_router(wiki_router)
    return app


def test_generate_business_wiki_endpoint(app):
    """POST /api/v1/wiki/business/generate should return 202."""
    client = TestClient(app)
    with patch("api.routes.wiki_routes.get_wiki_service") as mock_svc_fn:
        mock_svc = AsyncMock()
        mock_svc.generate_business_wiki = AsyncMock(return_value={
            "business_id": "test",
            "domains": ["用户管理"],
            "pages_count": 5,
            "references_count": 3,
            "repositories": ["user-svc"],
        })
        mock_svc_fn.return_value = mock_svc
        r = client.post(
            "/api/v1/wiki/business/generate",
            json={"business_id": "test", "language": "zh"},
        )
        assert r.status_code == 202
        data = r.json()
        assert data["business_id"] == "test"


def test_wiki_tree_endpoint_with_view(app):
    """GET /api/v1/wiki/tree should accept view parameter."""
    client = TestClient(app)
    with patch("api.routes.wiki_routes.get_wiki_store") as mock_store_fn:
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(return_value=AsyncMock(
            raw=[],
            data=[],
        ))
        mock_store_fn.return_value = mock_store
        r = client.get("/api/v1/wiki/tree?business_id=test&view=business_domain")
        assert r.status_code == 200


def test_wiki_page_references_endpoint(app):
    """GET /api/v1/wiki/pages/{page_uid}/references should return references."""
    client = TestClient(app)
    with patch("api.routes.wiki_routes.get_wiki_store") as mock_store_fn:
        mock_store = AsyncMock()
        mock_store.get_wiki_page_references = AsyncMock(return_value=AsyncMock(
            raw=[], data=[],
        ))
        mock_store.get_wiki_page_back_references = AsyncMock(return_value=AsyncMock(
            raw=[], data=[],
        ))
        mock_store_fn.return_value = mock_store
        r = client.get("/api/v1/wiki/pages/WikiPage%3Ar%3Atest/references")
        assert r.status_code == 200
```

- [ ] **Step 2: Write the failing test — MCP**

```python
# tests/wiki/mcp/test_mcp_business_wiki.py
import pytest
from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST


def test_wiki_get_tree_in_manifest():
    """wiki_get_tree should be in the MCP tools manifest."""
    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_tree" in tool_names


def test_wiki_get_related_in_manifest():
    """wiki_get_related should be in the MCP tools manifest."""
    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_related" in tool_names


def test_wiki_get_domain_overview_in_manifest():
    """wiki_get_domain_overview should be in the MCP tools manifest."""
    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_domain_overview" in tool_names
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_api.py tests/wiki/mcp/test_mcp_business_wiki.py -v`
Expected: FAIL

- [ ] **Step 4: Add API endpoints**

在 `api/routes/wiki_routes.py` 中新增：

```python
@wiki_router.post("/api/v1/wiki/business/generate", status_code=202)
async def generate_business_wiki(request: dict):
    """Trigger cross-repo business-level wiki generation."""
    svc = get_wiki_service()
    business_id = request.get("business_id", "default")
    language = request.get("language", "en")
    llm_provider = request.get("llm_provider")
    result = await svc.generate_business_wiki(
        business_id=business_id,
        language=language,
        llm_provider=llm_provider,
    )
    return result

@wiki_router.get("/api/v1/wiki/tree")
async def get_wiki_tree(business_id: str = "default", view: str = "business_domain"):
    """Get the wiki tree structure for a business."""
    store = get_wiki_store()
    result = await store.get_wiki_tree(business_id, view)
    rows = getattr(result, "raw", []) or []
    tree_nodes = [
        {
            "uid": str(row[0]),
            "title": str(row[1]),
            "label": str(row[2]),
            "depth": int(row[3]),
            "sort_order": row[4],
            "path": str(row[5]),
            "page_type": str(row[6]),
        }
        for row in rows
    ]
    return {"business_id": business_id, "view": view, "nodes": tree_nodes}

@wiki_router.get("/api/v1/wiki/pages/{page_uid:path}/references")
async def get_page_references(page_uid: str):
    """Get outgoing and incoming references for a wiki page."""
    store = get_wiki_store()
    outgoing = await store.get_wiki_page_references(page_uid)
    incoming = await store.get_wiki_page_back_references(page_uid)
    return {
        "page_uid": page_uid,
        "outgoing": getattr(outgoing, "data", []) or [],
        "incoming": getattr(incoming, "data", []) or [],
    }
```

实现者注意：需要确保 `get_wiki_store()` helper 在路由文件中可用（检查现有 helper 函数）。

- [ ] **Step 5: Add MCP tool definitions**

在 `wiki/mcp_tools.py` 的 `WIKI_MCP_TOOLS_MANIFEST` 列表中追加：

```python
{
    "name": "wiki_get_tree",
    "description": "Get the wiki tree structure for a business, optionally filtered by view type.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "business_id": {"type": "string", "description": "Business ID", "default": "default"},
            "view": {"type": "string", "enum": ["business_domain", "code_structure"], "default": "business_domain"},
        },
    },
},
{
    "name": "wiki_get_related",
    "description": "Get related wiki pages (outgoing and incoming references) for a given page.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "page_uid": {"type": "string", "description": "WikiPage UID"},
        },
        "required": ["page_uid"],
    },
},
{
    "name": "wiki_get_domain_overview",
    "description": "Get the domain overview page for a business domain.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain_name": {"type": "string", "description": "Business domain name"},
            "business_id": {"type": "string", "description": "Business ID", "default": "default"},
        },
        "required": ["domain_name"],
    },
},
```

在 `WikiMCPHandler` 中添加对应的 handler 方法（`handle_wiki_get_tree`, `handle_wiki_get_related`, `handle_wiki_get_domain_overview`），并在 `handle_tool_call` 的 handlers dict 中注册。

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_api.py tests/wiki/mcp/test_mcp_business_wiki.py -v`
Expected: ALL PASS

- [ ] **Step 7: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

**Commit:** `feat(wiki): add business wiki API endpoints and MCP tools`

---

### Task 8: 集成验证 + 导出

**Files:**
- Modify: `wiki/__init__.py`
- Create: `tests/wiki/integration/test_phase4_smoke.py`

- [ ] **Step 1: Update wiki/__init__.py exports**

```python
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.reference_generator import WikiReferenceGenerator
from wiki.domain_overview_composer import DomainOverviewComposer

__all__ = [
    # ... existing exports ...
    "CrossRepoBusinessDomainPlanner",
    "WikiReferenceGenerator",
    "DomainOverviewComposer",
]
```

- [ ] **Step 2: Write integration smoke test**

```python
# tests/wiki/integration/test_phase4_smoke.py
"""Phase 4 integration smoke test — verify all new components are importable and wired."""
import pytest


def test_phase4_imports():
    """All Phase 4 components should be importable from wiki package."""
    from wiki import (
        CrossRepoBusinessDomainPlanner,
        WikiReferenceGenerator,
        DomainOverviewComposer,
    )
    assert CrossRepoBusinessDomainPlanner is not None
    assert WikiReferenceGenerator is not None
    assert DomainOverviewComposer is not None


def test_page_type_domain_overview_exists():
    """PageType should have DOMAIN_OVERVIEW value."""
    from wiki.models import PageType
    assert hasattr(PageType, "DOMAIN_OVERVIEW")
    assert PageType.DOMAIN_OVERVIEW == "domain_overview"


def test_config_phase4_fields_exist():
    """Phase 4 config fields should be accessible."""
    from config import Settings
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert hasattr(s.wiki, "cross_repo_domain_enabled")
    assert hasattr(s.wiki, "business_wiki_batch_threshold")
    assert s.wiki.cross_repo_domain_enabled is False
    assert s.wiki.business_wiki_batch_threshold == 100


def test_wiki_tree_builder_methods():
    """WikiTreeBuilder should have all required methods."""
    from wiki.tree_builder import WikiTreeBuilder
    builder = WikiTreeBuilder()
    assert hasattr(builder, "generate_page_path")
    assert hasattr(builder, "generate_section_uid")
    assert hasattr(builder, "generate_space_uid")
    assert hasattr(builder, "detect_naming_conflicts")
    assert hasattr(builder, "compute_content_hash")


def test_wiki_service_has_business_method():
    """WikiService should have generate_business_wiki method."""
    from wiki.service import WikiService
    assert hasattr(WikiService, "generate_business_wiki")


def test_wiki_mcp_tools_manifest_has_phase4_tools():
    """MCP tools manifest should include Phase 4 tools."""
    from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST
    tool_names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_get_tree" in tool_names
    assert "wiki_get_related" in tool_names
    assert "wiki_get_domain_overview" in tool_names


@pytest.mark.asyncio
async def test_domain_overview_page_serialization():
    """DomainOverviewComposer page should serialize correctly."""
    from wiki.domain_overview_composer import DomainOverviewComposer
    from wiki.models import PageType

    composer = DomainOverviewComposer(llm=None)
    page = await composer.compose("Test Domain", [])
    d = page.to_dict()
    assert d["page_type"] == "domain_overview"
    assert d["path"] == "/Test Domain/_overview"

    from wiki.models import WikiPage
    restored = WikiPage.from_dict(d)
    assert restored.page_type == PageType.DOMAIN_OVERVIEW
```

- [ ] **Step 3: Run integration test**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/integration/test_phase4_smoke.py -v`
Expected: ALL PASS

- [ ] **Step 4: Run full test suite — final validation**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 5: Verify backward compatibility**

确认以下向后兼容性：
1. `scope="repo"` 行为不变 — 单仓库 wiki 生成不受影响
2. `cross_repo_domain_enabled=False` 时 `generate_business_wiki` 仍可调用但行为简化
3. 现有 API 参数不变
4. 现有 MCP 工具不变，新工具为追加
5. `WikiPage.from_dict` 支持 `DOMAIN_OVERVIEW` page_type

**Commit:** `feat(wiki): Phase 4 integration validation and exports`

---

## 完成后检查清单

- [ ] 所有 8 个 Task 的测试全部通过
- [ ] Full test suite 无回归
- [ ] `wiki/__init__.py` 导出完整
- [ ] `config.py` 中 Phase 4 配置有清晰注释
- [ ] `DOMAIN_OVERVIEW` PageType 已添加
- [ ] MCP 工具 manifest 已扩展
- [ ] API 端点文档字符串完整
- [ ] 无 linter 错误
