# Wiki 树状元模型（Phase 0）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Wiki 系统引入 WikiSpace/WikiSection 节点和 HAS_CHILD/WIKI_REFERENCES 边，建立树状结构的数据基础。

**Architecture:** 在现有 FalkorDB 图谱中新增 WikiSpace、WikiSection 节点标签和 HAS_CHILD、WIKI_REFERENCES 关系类型。扩展 WikiPage 节点属性（version, repositories, importance_tier, manual_sections, content_hash）。修改 WikiStore 支持树状 CRUD，新增树结构 API 端点。现有功能通过 `WIKI__TREE_ENABLED` 开关保持向后兼容。

**Code Review 要求:** 每个 Task 完成后必须进行 code review，确认代码质量和测试覆盖后再进入下一个 Task。

**计划范围:** 本文档仅覆盖 Phase 0（Wiki 树状元模型）。Phase 4-6 的实施计划将在 Phase 0 完成并验证后单独编写。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB (Cypher), Pydantic, pytest

**Spec:** [2026-04-26-wiki-tree-architecture-design.md](../specs/2026-04-26-wiki-tree-architecture-design.md)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `store/schema.py` | 新增 NodeLabel、EdgeType 枚举值 |
| Modify | `wiki/models.py` | 新增 WikiSpaceNode、WikiSectionNode 数据类；扩展 WikiPage、PageType、ScopeParam |
| Modify | `config.py` | WikiConfig 新增 tree/引用/导出相关配置字段 |
| Modify | `store/wiki_store.py` | 新增树结构 CRUD Cypher 查询方法 |
| Modify | `store/falkordb_store.py` | 扩展 persist_wiki_pages 支持新属性；新增 WikiSpace/WikiSection 持久化 |
| Modify | `api/routes/wiki_routes.py` | 新增 tree API 端点 |
| Create | `wiki/tree_builder.py` | WikiTreeBuilder 树构建逻辑 |
| Create | `tests/wiki/test_tree_builder.py` | WikiTreeBuilder 单元测试 |
| Create | `tests/store/test_wiki_store_tree.py` | 树结构 Cypher 查询测试 |

---

### Task 1: 扩展 Schema 枚举

**Files:**
- Modify: `store/schema.py:44-73`

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_schema.py (append to existing or create)
from store.schema import NodeLabel, EdgeType

def test_wiki_space_label_exists():
    assert NodeLabel.WIKI_SPACE == "WikiSpace"

def test_wiki_section_label_exists():
    assert NodeLabel.WIKI_SECTION == "WikiSection"

def test_has_child_edge_exists():
    assert EdgeType.HAS_CHILD == "HAS_CHILD"

def test_wiki_references_edge_exists():
    assert EdgeType.WIKI_REFERENCES == "WIKI_REFERENCES"

def test_source_entity_edge_exists():
    assert EdgeType.SOURCE_ENTITY == "SOURCE_ENTITY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_schema.py -v -k "wiki_space or wiki_section or has_child or wiki_references or source_entity"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add new enum values to schema.py**

In `store/schema.py`, add to `NodeLabel`:
```python
class NodeLabel(StrEnum):
    FUNCTION = "Function"
    CLASS = "Class"
    MODULE = "Module"
    DOCUMENT = "Document"
    BUSINESS_FLOW = "BusinessFlow"
    BUSINESS_CONCEPT = "BusinessConcept"
    WIKI_PAGE = "WikiPage"
    WIKI_SPACE = "WikiSpace"
    WIKI_SECTION = "WikiSection"
    CHUNK = "Chunk"
```

Add to `EdgeType`:
```python
class EdgeType(StrEnum):
    # ... existing values ...
    SOURCE_DOC = "SOURCE_DOC"
    HAS_CHILD = "HAS_CHILD"
    WIKI_REFERENCES = "WIKI_REFERENCES"
    SOURCE_ENTITY = "SOURCE_ENTITY"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_schema.py -v -k "wiki_space or wiki_section or has_child or wiki_references or source_entity"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add store/schema.py tests/store/test_schema.py
git commit -m "feat(schema): add WikiSpace, WikiSection labels and HAS_CHILD, WIKI_REFERENCES, SOURCE_ENTITY edge types"
```

- [ ] **Step 6: Code Review**

Review checklist:
- 枚举值命名是否符合项目既有风格
- 新增枚举值是否与设计文档一致
- 测试覆盖是否完整
- 无拼写错误、无冗余代码

---

### Task 2: 新增 Wiki 树模型数据类

**Files:**
- Modify: `wiki/models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_tree_models.py
from wiki.models import WikiSpaceNode, WikiSectionNode, PageType, ScopeParam, parse_scope

def test_wiki_space_node_creation():
    node = WikiSpaceNode(
        uid="ws:default",
        business_id="default",
        title="Test Business",
        description="Test description",
    )
    assert node.business_id == "default"
    assert node.title == "Test Business"

def test_wiki_section_node_creation():
    node = WikiSectionNode(
        uid="wsec:user-mgmt",
        title="用户管理",
        description="User management domain",
        section_type="business_domain",
        sort_order=1,
    )
    assert node.section_type == "business_domain"
    assert node.auto_generated is True

def test_wiki_section_node_defaults():
    node = WikiSectionNode(
        uid="wsec:test",
        title="Test",
        description="",
        section_type="code_module",
        sort_order=0,
    )
    assert node.icon is None
    assert node.auto_generated is True

def test_page_type_domain_overview():
    assert PageType.DOMAIN_OVERVIEW == "domain_overview"

def test_page_type_business_flow():
    assert PageType.BUSINESS_FLOW == "business_flow"

def test_scope_param_business():
    scope = parse_scope("business")
    assert scope.scope_type == "business"
    assert scope.value is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_tree_models.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add new models to wiki/models.py**

Add new `PageType` values:
```python
class PageType(StrEnum):
    MODULE_OVERVIEW = "module_overview"
    CLASS_DETAIL = "class_detail"
    REPO_OVERVIEW = "repo_overview"
    ARCHITECTURE = "architecture"
    API_REFERENCE = "api_reference"
    DATA_FLOW = "data_flow"
    DOMAIN_OVERVIEW = "domain_overview"
    BUSINESS_FLOW = "business_flow"
    INDEX = "index"
```

Add `"business"` to `_VALID_SCOPE_TYPES`:
```python
_VALID_SCOPE_TYPES = frozenset({"repo", "module", "class", "business"})
```

Update `parse_scope` to handle `"business"`:
```python
def parse_scope(raw: str) -> ScopeParam:
    if not raw:
        raise ValueError("Invalid scope: empty string")
    if raw == "repo":
        return ScopeParam(scope_type="repo")
    if raw == "business":
        return ScopeParam(scope_type="business")
    # ... rest unchanged ...
```

Add new dataclasses after `WikiConfig`:
```python
@dataclass
class WikiSpaceNode:
    uid: str
    business_id: str
    title: str
    description: str
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class WikiSectionNode:
    uid: str
    title: str
    description: str
    section_type: str  # "business_domain" | "code_module" | "topic"
    sort_order: int
    icon: str | None = None
    auto_generated: bool = True
```

Add `datetime` and `timezone` imports at top of file:
```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_tree_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/models.py tests/wiki/test_tree_models.py
git commit -m "feat(wiki): add WikiSpaceNode, WikiSectionNode models and new PageType values"
```

- [ ] **Step 6: Code Review**

Review checklist:
- 数据类字段类型和默认值是否合理
- WikiSpaceNode/WikiSectionNode 是否与设计文档中的节点定义一致
- `parse_scope` 新增分支的边界条件
- 导入是否干净，无循环依赖

---

### Task 3: 扩展 WikiConfig 配置

**Files:**
- Modify: `config.py:168-175`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_wiki_tree.py
from config import Settings

def test_wiki_tree_config_defaults():
    s = Settings(falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.tree_enabled is True
    assert s.wiki.dual_view_enabled is True
    assert s.wiki.cross_reference_enabled is True
    assert s.wiki.cross_reference_min_confidence == 0.5

def test_wiki_export_config_defaults():
    s = Settings(falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.git_publish_enabled is False
    assert s.wiki.git_publish_mode == "incremental"
    assert s.wiki.export_default_view == "business_domain"
    assert s.wiki.export_min_tier == "standard"
    assert s.wiki.export_dir_naming == "original"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/test_config_wiki_tree.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Extend WikiConfig in config.py**

```python
class WikiConfig(BaseModel):
    """Application-level wiki feature flags."""

    cot_enabled: bool = False
    cot_analysis_model: str = ""
    cot_generation_model: str = ""
    auto_update_on_index: bool = False

    tree_enabled: bool = True
    dual_view_enabled: bool = True
    cross_reference_enabled: bool = True
    cross_reference_min_confidence: float = 0.5
    cross_repo_domain_enabled: bool = False
    knowledge_injection_enabled: bool = True

    git_publish_enabled: bool = False
    git_publish_mode: str = "incremental"
    git_publish_trigger: str = "manual"
    git_publish_schedule: str = "0 2 * * *"
    git_remote_url: str = ""
    git_branch: str = "main"
    git_author_name: str = "KBS Wiki Bot"
    git_author_email: str = "wiki-bot@company.com"
    git_token: str = ""
    export_default_view: str = "business_domain"
    export_min_tier: str = "standard"
    export_dir_naming: str = "original"

    coverage_report_enabled: bool = True
    stale_detection_enabled: bool = True
    suggested_questions_enabled: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/test_config_wiki_tree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config_wiki_tree.py
git commit -m "feat(config): add wiki tree, export, and quality config fields"
```

- [ ] **Step 6: Code Review**

Review checklist:
- 配置字段命名是否遵循项目 `WIKI__` 前缀约定
- 默认值是否安全合理（如 `git_publish_enabled` 默认 False）
- 敏感字段（如 `git_token`）是否有安全处理提示
- 与设计文档中的配置表一致性

---

### Task 4: WikiStore 树结构 CRUD 方法

**Files:**
- Modify: `store/wiki_store.py`
- Test: `tests/store/test_wiki_store_tree.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/store/test_wiki_store_tree.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from store.wiki_store import WikiStore

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[]))
    return WikiStore(store)

@pytest.mark.asyncio
async def test_upsert_wiki_space(mock_store):
    await mock_store.upsert_wiki_space("default", "Test Business", "desc")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "MERGE (ws:WikiSpace" in cypher
    assert "business_id" in cypher

@pytest.mark.asyncio
async def test_upsert_wiki_section(mock_store):
    await mock_store.upsert_wiki_section(
        uid="wsec:user-mgmt",
        title="用户管理",
        description="",
        section_type="business_domain",
        sort_order=1,
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "MERGE (ws:WikiSection" in cypher

@pytest.mark.asyncio
async def test_add_has_child_edge(mock_store):
    await mock_store.add_has_child_edge(
        parent_uid="ws:default",
        parent_label="WikiSpace",
        child_uid="wsec:user-mgmt",
        child_label="WikiSection",
        view_type="business_domain",
        sort_order=1,
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "HAS_CHILD" in cypher
    assert "view_type" in cypher

@pytest.mark.asyncio
async def test_add_wiki_reference_edge(mock_store):
    await mock_store.add_wiki_reference_edge(
        source_uid="WikiPage:repo:path1",
        target_uid="WikiPage:repo:path2",
        relation_type="calls",
        context="UserController calls UserService",
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "WIKI_REFERENCES" in cypher
    assert "relation_type" in cypher

@pytest.mark.asyncio
async def test_get_wiki_tree(mock_store):
    await mock_store.get_wiki_tree("default", "business_domain")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "HAS_CHILD" in cypher
    assert "view_type" in cypher

@pytest.mark.asyncio
async def test_get_wiki_page_references(mock_store):
    await mock_store.get_wiki_page_references("WikiPage:repo:path1")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "WIKI_REFERENCES" in cypher

@pytest.mark.asyncio
async def test_get_wiki_page_back_references(mock_store):
    await mock_store.get_wiki_page_back_references("WikiPage:repo:path1")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "WIKI_REFERENCES" in cypher
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_wiki_store_tree.py -v`
Expected: FAIL with `AttributeError` (methods don't exist)

- [ ] **Step 3: Add tree CRUD methods to WikiStore**

Add the following methods to `store/wiki_store.py`:

```python
    # --- Tree structure CRUD ---

    async def upsert_wiki_space(
        self, business_id: str, title: str, description: str
    ) -> QueryResultWrapper:
        uid = f"WikiSpace:{business_id}"
        q = (
            "MERGE (ws:WikiSpace {uid: $uid}) "
            "SET ws.business_id = $business_id, "
            "ws.title = $title, "
            "ws.description = $description, "
            "ws.updated_at = $ts "
            "ON CREATE SET ws.created_at = $ts "
            "RETURN ws.uid AS uid"
        )
        ts = datetime.now(timezone.utc).isoformat()
        return await self._store.execute_query(
            q, {"uid": uid, "business_id": business_id, "title": title,
                "description": description, "ts": ts},
        )

    async def upsert_wiki_section(
        self,
        uid: str,
        title: str,
        description: str,
        section_type: str,
        sort_order: int,
        icon: str | None = None,
        auto_generated: bool = True,
    ) -> QueryResultWrapper:
        q = (
            "MERGE (ws:WikiSection {uid: $uid}) "
            "SET ws.title = $title, "
            "ws.description = $description, "
            "ws.section_type = $section_type, "
            "ws.sort_order = $sort_order, "
            "ws.icon = $icon, "
            "ws.auto_generated = $auto_generated "
            "RETURN ws.uid AS uid"
        )
        return await self._store.execute_query(
            q, {"uid": uid, "title": title, "description": description,
                "section_type": section_type, "sort_order": sort_order,
                "icon": icon or "", "auto_generated": auto_generated},
        )

    async def add_has_child_edge(
        self,
        parent_uid: str,
        parent_label: str,
        child_uid: str,
        child_label: str,
        view_type: str,
        sort_order: int,
    ) -> QueryResultWrapper:
        q = (
            f"MATCH (p:{parent_label} {{uid: $parent_uid}}) "
            f"MATCH (c:{child_label} {{uid: $child_uid}}) "
            "MERGE (p)-[r:HAS_CHILD {view_type: $view_type}]->(c) "
            "SET r.sort_order = $sort_order "
            "RETURN type(r) AS rel"
        )
        return await self._store.execute_query(
            q, {"parent_uid": parent_uid, "child_uid": child_uid,
                "view_type": view_type, "sort_order": sort_order},
        )

    async def add_wiki_reference_edge(
        self,
        source_uid: str,
        target_uid: str,
        relation_type: str,
        context: str = "",
        auto_generated: bool = True,
        confidence: float = 1.0,
    ) -> QueryResultWrapper:
        q = (
            "MATCH (s:WikiPage {uid: $source_uid}) "
            "MATCH (t:WikiPage {uid: $target_uid}) "
            "MERGE (s)-[r:WIKI_REFERENCES {relation_type: $relation_type}]->(t) "
            "SET r.context = $context, "
            "r.auto_generated = $auto_generated, "
            "r.confidence = $confidence "
            "RETURN type(r) AS rel"
        )
        return await self._store.execute_query(
            q, {"source_uid": source_uid, "target_uid": target_uid,
                "relation_type": relation_type, "context": context,
                "auto_generated": auto_generated, "confidence": confidence},
        )

    async def get_wiki_tree(
        self, business_id: str, view_type: str, max_depth: int = 5
    ) -> QueryResultWrapper:
        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id}) "
            "OPTIONAL MATCH path = (ws)-[:HAS_CHILD*1..5]->(node) "
            "WHERE ALL(r IN relationships(path) WHERE r.view_type = $view_type) "
            "WITH node, length(path) AS depth "
            "WHERE node IS NOT NULL "
            "RETURN node.uid AS uid, node.title AS title, "
            "labels(node)[0] AS label, depth, "
            "node.sort_order AS sort_order, "
            "coalesce(node.path, '') AS path, "
            "coalesce(node.page_type, '') AS page_type "
            "ORDER BY depth, sort_order"
        )
        return await self._store.execute_query(
            q, {"business_id": business_id, "view_type": view_type},
        )

    async def get_wiki_page_references(self, page_uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (s:WikiPage {uid: $uid})-[r:WIKI_REFERENCES]->(t:WikiPage) "
            "RETURN t.uid AS target_uid, t.title AS title, t.path AS path, "
            "t.repository AS repository, "
            "r.relation_type AS relation_type, r.context AS context "
            "ORDER BY r.relation_type, t.title"
        )
        return await self._store.execute_query(q, {"uid": page_uid})

    async def get_wiki_page_back_references(self, page_uid: str) -> QueryResultWrapper:
        q = (
            "MATCH (s:WikiPage)-[r:WIKI_REFERENCES]->(t:WikiPage {uid: $uid}) "
            "RETURN s.uid AS source_uid, s.title AS title, s.path AS path, "
            "s.repository AS repository, "
            "r.relation_type AS relation_type, r.context AS context "
            "ORDER BY r.relation_type, s.title"
        )
        return await self._store.execute_query(q, {"uid": page_uid})
```

Add imports at top of `store/wiki_store.py`:
```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_wiki_store_tree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add store/wiki_store.py tests/store/test_wiki_store_tree.py
git commit -m "feat(wiki-store): add tree CRUD methods for WikiSpace, WikiSection, HAS_CHILD, WIKI_REFERENCES"
```

- [ ] **Step 6: Code Review**

Review checklist:
- Cypher 查询语法正确性（MERGE/MATCH/SET）
- 参数化查询防止注入（$variable 而非 f-string 拼接值）
- 方法签名是否与设计文档中的接口定义一致
- mock 测试是否覆盖正常和边界场景
- `datetime` 导入是否与项目其他文件一致

---

### Task 5: 扩展 persist_wiki_pages 支持新属性

**Files:**
- Modify: `store/falkordb_store.py:338-373`

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_falkordb_wiki_extended.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_persist_wiki_pages_includes_new_fields():
    """Verify the Cypher SET clause includes version, content_hash, importance_tier, repositories."""
    from store.falkordb_store import FalkorDBStore
    store = FalkorDBStore.__new__(FalkorDBStore)
    store._graph = MagicMock()

    mock_result = MagicMock()
    mock_result.result_set = [[1]]
    store._graph.query = MagicMock(return_value=mock_result)

    pages = [{
        "path": "/test/page",
        "title": "Test",
        "content": "content",
        "page_type": "class_detail",
        "generated_at": "2026-01-01T00:00:00Z",
        "version": 2,
        "content_hash": "abc123",
        "importance_tier": "core",
        "repositories": ["repo-a", "repo-b"],
    }]

    await store.persist_wiki_pages("test-repo", pages)

    call_args = store._graph.query.call_args
    cypher = call_args[0][0]
    assert "w.version" in cypher
    assert "w.content_hash" in cypher
    assert "w.importance_tier" in cypher
    assert "w.repositories" in cypher
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_falkordb_wiki_extended.py -v`
Expected: FAIL (new properties not in Cypher SET clause)

- [ ] **Step 3: Update persist_wiki_pages Cypher**

In `store/falkordb_store.py`, update the `persist_wiki_pages` method's Cypher to include new fields:

```python
    async def persist_wiki_pages(self, repository: str, pages: list[dict[str, Any]]) -> int:
        """MERGE WikiPage nodes from generated wiki output. Returns count of upserted nodes."""
        batch = []
        for p in pages:
            uid = f"WikiPage:{repository}:{p['path']}"
            batch.append({
                "uid": uid,
                "repository": repository,
                "path": p["path"],
                "title": p["title"],
                "content": p["content"],
                "page_type": p["page_type"],
                "generated_at": p["generated_at"],
                "version": p.get("version", 1),
                "content_hash": p.get("content_hash", ""),
                "importance_tier": p.get("importance_tier", ""),
                "repositories": p.get("repositories", [repository]),
            })

        cypher = (
            "UNWIND $batch AS page "
            "MERGE (w:WikiPage {uid: page.uid}) "
            "SET w.repository = page.repository, "
            "w.path = page.path, "
            "w.title = page.title, "
            "w.content = page.content, "
            "w.page_type = page.page_type, "
            "w.generated_at = page.generated_at, "
            "w.version = page.version, "
            "w.content_hash = page.content_hash, "
            "w.importance_tier = page.importance_tier, "
            "w.repositories = page.repositories "
            "RETURN count(*) AS cnt"
        )
        # ... rest of method unchanged ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/store/test_falkordb_wiki_extended.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add store/falkordb_store.py tests/store/test_falkordb_wiki_extended.py
git commit -m "feat(falkordb): extend persist_wiki_pages with version, content_hash, importance_tier, repositories"
```

- [ ] **Step 6: Code Review**

Review checklist:
- 新增 SET 字段的 Cypher 语法完整性
- `.get()` 默认值是否合理（version=1, content_hash="", repositories=[repository]）
- 与现有 `persist_wiki_pages` 逻辑的兼容性（已有 WikiPage 节点的无损更新）
- 测试 mock 是否准确模拟 FalkorDB 行为

---

### Task 6: WikiTreeBuilder 核心组件

**Files:**
- Create: `wiki/tree_builder.py`
- Test: `tests/wiki/test_tree_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_tree_builder.py
import pytest
from wiki.tree_builder import WikiTreeBuilder

def test_generate_page_path_simple():
    builder = WikiTreeBuilder()
    path = builder.generate_page_path(
        domain="用户管理",
        repository="user-service",
        entity_name="UserController",
    )
    assert path == "/用户管理/user-service/UserController"

def test_generate_page_path_domain_overview():
    builder = WikiTreeBuilder()
    path = builder.generate_page_path(
        domain="用户管理",
        repository=None,
        entity_name=None,
        is_overview=True,
    )
    assert path == "/用户管理/_overview"

def test_generate_page_path_flow():
    builder = WikiTreeBuilder()
    path = builder.generate_page_path(
        domain="用户管理",
        repository=None,
        entity_name="用户注册流程",
        is_flow=True,
    )
    assert path == "/用户管理/用户注册流程/_flow"

def test_generate_section_uid():
    builder = WikiTreeBuilder()
    uid = builder.generate_section_uid("default", "用户管理")
    assert uid == "WikiSection:default:用户管理"

def test_generate_space_uid():
    builder = WikiTreeBuilder()
    uid = builder.generate_space_uid("default")
    assert uid == "WikiSpace:default"

def test_detect_naming_conflict():
    builder = WikiTreeBuilder()
    pages = [
        {"repository": "user-service", "entity_name": "UserService"},
        {"repository": "auth-service", "entity_name": "UserService"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert "UserService" in conflicts
    assert set(conflicts["UserService"]) == {"user-service", "auth-service"}

def test_no_naming_conflict():
    builder = WikiTreeBuilder()
    pages = [
        {"repository": "user-service", "entity_name": "UserController"},
        {"repository": "auth-service", "entity_name": "AuthController"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert len(conflicts) == 0

def test_content_hash():
    builder = WikiTreeBuilder()
    h1 = builder.compute_content_hash("hello world")
    h2 = builder.compute_content_hash("hello world")
    h3 = builder.compute_content_hash("different content")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_tree_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement WikiTreeBuilder**

```python
# wiki/tree_builder.py
"""Builds and manages the wiki tree structure."""

from __future__ import annotations

import hashlib
from collections import defaultdict


class WikiTreeBuilder:
    """Utility for generating wiki tree paths, UIDs, and detecting naming conflicts."""

    def generate_page_path(
        self,
        domain: str | None = None,
        repository: str | None = None,
        entity_name: str | None = None,
        is_overview: bool = False,
        is_flow: bool = False,
    ) -> str:
        parts: list[str] = []
        if domain:
            parts.append(domain)
        if is_overview:
            parts.append("_overview")
            return "/" + "/".join(parts)
        if is_flow and entity_name:
            parts.append(entity_name)
            parts.append("_flow")
            return "/" + "/".join(parts)
        if repository:
            parts.append(repository)
        if entity_name:
            parts.append(entity_name)
        return "/" + "/".join(parts)

    def generate_section_uid(self, business_id: str, section_title: str) -> str:
        return f"WikiSection:{business_id}:{section_title}"

    def generate_space_uid(self, business_id: str) -> str:
        return f"WikiSpace:{business_id}"

    def detect_naming_conflicts(
        self, pages: list[dict[str, str]]
    ) -> dict[str, list[str]]:
        name_to_repos: dict[str, list[str]] = defaultdict(list)
        for page in pages:
            entity_name = page.get("entity_name", "")
            repo = page.get("repository", "")
            if entity_name and repo:
                name_to_repos[entity_name].append(repo)

        return {
            name: repos
            for name, repos in name_to_repos.items()
            if len(repos) > 1
        }

    def compute_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_tree_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/tree_builder.py tests/wiki/test_tree_builder.py
git commit -m "feat(wiki): implement WikiTreeBuilder with path generation, conflict detection, content hashing"
```

- [ ] **Step 6: Code Review**

Review checklist:
- `generate_page_path` 的路径拼接逻辑是否正确处理所有组合
- 命名冲突检测算法的正确性
- SHA-256 hash 的 UTF-8 编码处理
- 是否缺少 `generate_page_path` 的更多边界用例（如空 domain、特殊字符）

---

### Task 7: Wiki 树 API 端点

**Files:**
- Modify: `api/routes/wiki_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_wiki_tree_routes.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from main import app
    return TestClient(app)

def test_wiki_tree_endpoint_exists(client):
    """Verify the /api/v1/wiki/tree endpoint returns 200 or 422 (not 404)."""
    response = client.get(
        "/api/v1/wiki/tree",
        params={"business_id": "default", "view": "business_domain"},
    )
    assert response.status_code != 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/api/test_wiki_tree_routes.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Add tree API endpoint**

Add to `api/routes/wiki_routes.py`:

```python
@wiki_router.get("/tree")
async def wiki_get_tree(
    business_id: str = Query(default="default"),
    view: str = Query(default="business_domain"),
    request: Request = None,
):
    """Return the wiki tree structure for the given business and view type."""
    wiki_store: WikiStore | None = getattr(request.app.state, "wiki_store", None)
    if wiki_store is None:
        return {"tree": [], "view_type": view, "business_id": business_id}

    result = await wiki_store.get_wiki_tree(business_id, view)
    nodes = []
    if result and result.result_set:
        for row in result.result_set:
            nodes.append({
                "uid": row[0],
                "title": row[1],
                "label": row[2],
                "depth": row[3],
                "sort_order": row[4],
                "path": row[5],
                "page_type": row[6],
            })

    return {"tree": nodes, "view_type": view, "business_id": business_id}
```

Add `Query` import if not present:
```python
from fastapi import Query
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd knowledge-base-service && uv run pytest tests/api/test_wiki_tree_routes.py -v`
Expected: PASS (endpoint returns 200)

- [ ] **Step 5: Commit**

```bash
git add api/routes/wiki_routes.py tests/api/test_wiki_tree_routes.py
git commit -m "feat(api): add GET /api/v1/wiki/tree endpoint for tree structure navigation"
```

- [ ] **Step 6: Code Review**

Review checklist:
- API 路径和参数命名是否符合 RESTful 规范
- 默认值处理是否安全（`wiki_store is None` 的降级逻辑）
- 响应结构是否与前端约定一致
- Query 参数验证是否需要更严格的约束（如 view 的合法值枚举）

---

### Task 8: 集成验证与文档更新

**Files:**
- Modify: `wiki/__init__.py` (export new classes)

- [ ] **Step 1: Run all tests to verify no regressions**

Run: `cd knowledge-base-service && uv run pytest tests/ -v --tb=short -q`
Expected: All existing tests PASS, all new tests PASS

- [ ] **Step 2: Update wiki/__init__.py exports**

Add new exports to `wiki/__init__.py`:
```python
from wiki.tree_builder import WikiTreeBuilder
from wiki.models import WikiSpaceNode, WikiSectionNode
```

- [ ] **Step 3: Run full test suite again**

Run: `cd knowledge-base-service && uv run pytest tests/ -v --tb=short -q`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/__init__.py
git commit -m "feat(wiki): export tree builder and new models from wiki package"
```
