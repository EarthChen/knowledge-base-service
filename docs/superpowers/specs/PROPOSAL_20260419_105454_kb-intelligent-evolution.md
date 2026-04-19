# 知识库智能演进系统提案

| 元信息 | 值 |
|---------|------|
| **提案编号** | PROPOSAL_20260419_105454 |
| **状态** | `[Implementing] — Wave 1 执行中 (P5.A + P5.B + P1)` |
| **前置依赖** | PROPOSAL_20260418_195157 (搜索质量增强 — 已完成) |
| **灵感来源** | [Karpathy llm-wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) |
| **执行方法论** | TDD + Subagent 并行 |

---

## 1. 背景

### 1.1 参考项目分析

通过 Sequential-Thinking 对 Karpathy 的 LLM-Wiki 模式和 nashsu/llm_wiki 项目进行了 8 步深度分析，提炼出对 KBS 最有价值的借鉴点。

**Karpathy LLM-Wiki 核心洞察**：
- RAG 每次查询都从零发现知识，没有积累；Wiki 是一次性编译、持续维护的制品
- 三层架构：Raw Sources → Wiki → Schema
- 三个操作：Ingest（摄取）、Query（查询）、Lint（健康检查）
- 知识是持续复合增长的制品

**nashsu/llm_wiki 实践亮点**：
- 两步链式思考摄取（先分析 → 后生成）显著提升 Wiki 质量
- 4-信号知识图谱 + Louvain 社区发现 + 图洞察
- 异步审查系统（Human-in-the-Loop）
- Wiki Lint 定期健康检查

**批判性思考（吸收社区反馈）**：
- KBS 不依赖纯 index.md，有 FalkorDB 图 + 向量搜索，**已解决可扩展性问题**
- Wiki 基于结构化代码图，不是纯 LLM 生成，**幻觉风险已被降低**
- Lint 机制提供自动化质量检查，**解决"谁来维护"的问题**

### 1.2 现状与机会

| 能力 | 现状 | 机会 |
|------|------|------|
| Wiki 健康检查 | ❌ 无 | Lint 系统检测过期、孤立、失效内容 |
| 架构异常检测 | ❌ 仅手动审查 | 自动发现循环依赖、跨层调用、孤立实体 |
| Wiki 更新模式 | 全量重建 | 增量更新，仅重建受影响页面 |
| Wiki 生成质量 | 单步生成 | 两步链式思考提升准确性 |
| 文档索引质量 | 嵌入差 + 分块粗糙 + 引用不可靠 | 专用嵌入格式 + 智能分块 + FQN 精确匹配 |
| 文档-Wiki 关系 | 两个并行世界，无联动 | Document 作为 Wiki 输入源，搜索统一出口 |
| 仓库文档更新 | ❌ 手动维护 | Wiki Export 导出，diff 预览 + 选择性写入 |

---

## 2. 目标

1. **Wiki Lint 健康检查**：自动检测 Wiki 与代码实际状态的失步，提供可操作的健康报告
2. **图洞察与架构异常检测**：自动发现代码图中的架构异常模式
3. **增量 Wiki 更新**：新文件索引时局部更新 Wiki，而非重建
4. **两步链式思考摄取**：分析和生成解耦，提升 Wiki 生成质量
5. **文档索引质量优化**：修复 Document 嵌入/分块/引用匹配的质量问题，并将 Document 融合为 Wiki 生成的输入源
6. **Wiki Export**：将 Wiki 导出为仓库文档文件，支持 diff 预览和选择性写入

---

## 3. 设计方案

### 3.1 P1 — Wiki Lint 健康检查系统

#### 3.1.1 服务设计

新建 `wiki/lint.py`：

```python
@dataclass
class LintIssue:
    severity: Literal["error", "warning", "info"]
    category: str  # staleness | orphan | broken_link | coverage_gap | outdated
    message: str
    page_path: str | None = None
    entity_name: str | None = None
    suggestion: str | None = None

@dataclass
class LintReport:
    issues: list[LintIssue]
    stats: dict[str, int]  # {total, errors, warnings, info}
    checked_at: str
    scope: str

class WikiLintService:
    def __init__(self, store: FalkorDBStore, wiki_svc: WikiService):
        ...

    async def lint(self, *, scope: str = "all") -> LintReport:
        checks = await asyncio.gather(
            self._check_staleness(),
            self._check_orphans(),
            self._check_broken_links(),
            self._check_coverage_gaps(),
            self._check_outdated_content(),
        )
        issues = [issue for group in checks for issue in group]
        return LintReport(issues=issues, stats=self._compute_stats(issues), ...)
```

#### 3.1.2 前置：Schema 扩展

**`WikiPageMetadata` 增加 `generated_at` 字段**（当前无时间戳，无法判断过时）：

```python
@dataclass
class WikiPageMetadata:
    node_count: int
    edge_count: int
    generation_mode: str = "structure"
    fallback_tier: int | None = None
    generated_at: str | None = None  # ISO 8601 timestamp
```

同时在 `WikiPage` 图节点上持久化 `generated_at` 属性，与 RepoRegistry 的 `last_indexed_at` 对比判断过时。

#### 3.1.3 检查维度

| 检查 | 严重度 | 逻辑 |
|------|--------|------|
| **Staleness** | error | Wiki 页面引用的实体在图中已不存在 |
| **Orphans** | warning | 无入向 wikilink 的 Wiki 页面（排除 README/overview 等根页面） |
| **Broken Links** | error | `[text](path.md)` 或 `[[wikilink]]` 指向不存在的页面（匹配规则见下方链接语法定义） |
| **Coverage Gaps** | warning | 图中 `'service' IN c.semantic_roles` 或 `'http_controller' IN c.semantic_roles` 或 `'repository' IN c.semantic_roles` 的 Class 节点未被 Wiki 覆盖 |
| **Outdated Content** | info | `WikiPage.generated_at` 早于 `RepoRegistry.last_indexed_at` |

**链接语法定义**：Lint 识别两种引用格式：
1. Markdown 链接 `[text](relative/path.md)` — 匹配 `WikiPage.path`
2. Wikilink `[[PageTitle]]` — 匹配 `WikiPage.title`，参考 `GraphQueryService._wiki_paths_by_titles` 的现有解析逻辑

#### 3.1.4 API 与 MCP

```python
# POST /api/v1/wiki/lint
@viewer_router.post("/wiki/lint")
async def wiki_lint(svc = Depends(_get_service)) -> LintReport: ...

# MCP tool: wiki_lint
```

#### 3.1.5 Dashboard

Wiki 页面增加 "Lint" tab，展示健康报告和问题列表。

#### 3.1.6 测试清单

- [ ] `tests/wiki/test_lint.py` — WikiLintService 单元测试
  - [ ] 空 Wiki 无问题
  - [ ] staleness 检测：引用不存在的实体
  - [ ] orphan 检测：孤立页面
  - [ ] broken_link 检测：失效链接
  - [ ] coverage_gap 检测：重要实体无 Wiki 页面
  - [ ] outdated 检测：过期内容
  - [ ] scope 过滤正确
- [ ] `tests/api/test_wiki_lint_api.py` — REST 端点测试
- [ ] `dashboard/src/components/wiki/__tests__/LintPanel.test.tsx`

---

### 3.2 P2 — 图洞察与架构异常检测

#### 3.2.1 服务设计

新建 `query/graph_insights.py`：

```python
@dataclass
class InsightItem:
    category: str  # isolated | circular_dep | cross_layer | low_cohesion | bridge
    severity: Literal["critical", "warning", "info"]
    title: str
    description: str
    entities: list[str]
    suggestion: str

@dataclass
class InsightsReport:
    insights: list[InsightItem]
    graph_stats: dict[str, int]
    analyzed_at: str

class GraphInsightsService:
    async def analyze(self) -> InsightsReport:
        checks = await asyncio.gather(
            self._find_isolated_entities(),
            self._find_circular_dependencies(),
            self._find_cross_layer_violations(),
            self._compute_module_cohesion(),
            self._find_bridge_nodes(),
        )
        ...
```

#### 3.2.2 检测维度

| 检测 | 严重度 | Cypher 逻辑 |
|------|--------|------------|
| **孤立实体** | warning | `MATCH (n:Class) WHERE NOT (n)-[:CALLS\|INHERITS\|IMPORTS\|CONTAINS]-() RETURN n` （使用无向匹配，schema 中无 `CALLED_BY`） |
| **循环依赖** | critical | `MATCH p = (a:Module)-[:IMPORTS*2..5]->(a) RETURN p` （模块级用 `IMPORTS`；`DEPENDS_ON` 仅表示 Spring DI bean 注入，不适用于模块依赖环检测） |
| **跨层调用** | warning | `MATCH (ctrl:Class)-[:CALLS]->(repo:Class) WHERE 'http_controller' IN ctrl.semantic_roles AND 'repository' IN repo.semantic_roles AND NOT EXISTS { MATCH (ctrl)-[:CALLS]->(:Class)-[:CALLS]->(repo) } RETURN ctrl, repo`（Controller 直接调用 Repository 跳过 Service 层） |
| **模块内聚度** | info | 给定 Module `m`，计算 `(m)-[:CONTAINS]->(c:Class)` 的所有子类之间 `CALLS` 边数 / 子类数*(子类数-1)（可能边数），阈值 < 0.15 |
| **桥接节点** | info | `MATCH (c:Class)-[:CALLS\|INHERITS]->(t:Class) WHERE c.architecture_layer <> t.architecture_layer WITH c, COLLECT(DISTINCT t.architecture_layer) AS layers WHERE SIZE(layers) >= 3 RETURN c`（连接 3+ 不同 `architecture_layer` 的类） |

> **Schema 约束说明**：`store/schema.py` 定义的边类型中，`CALLS` 是单向 (caller→callee)，无 `CALLED_BY` 逆向边。孤立实体检测使用无向匹配 `-[:CALLS]-` 而非 `-[:CALLED_BY]->`。`DEPENDS_ON` 仅表示 Spring DI 注入关系 (bean→injected bean)，模块循环依赖应使用 `IMPORTS`。

#### 3.2.3 API 与 Dashboard

```python
# GET /api/v1/graph/insights/{repository}
# 放在 graph/ 路由下而非 wiki/，因为图洞察是架构分析功能，与 /search/architecture 同层
# MCP tool: graph_insights
```

Dashboard: Architecture Explorer 增加 "Insights" tab（与现有 architecture_layers 展示同一入口）。

#### 3.2.4 精确定义

**模块边界**：`(m:Module)-[:CONTAINS]->(c:Class)` — 一个 Module 包含的所有 Class 节点构成该模块的范围。

**内聚度计算**：
```
给定模块 m，令 classes = {c : (m)-[:CONTAINS]->(c:Class)}
令 internal_calls = |{(a,b) : a,b ∈ classes, (a)-[:CALLS]->(b)}|
令 possible = |classes| * (|classes| - 1)
cohesion = internal_calls / possible  （possible=0 时 cohesion=1.0）
```

**桥接节点**：一个 Class 节点 `c`，其直接邻居（通过 `CALLS|INHERITS` 边，任意方向）跨越 3 个或更多不同的 `architecture_layer` 值（该属性已由 `GraphEnricher` 在索引时标注）。

#### 3.2.5 测试清单

- [ ] `tests/query/test_graph_insights.py`
  - [ ] 空图无洞察
  - [ ] 孤立实体检测
  - [ ] 循环依赖检测
  - [ ] 跨层调用检测
  - [ ] 模块内聚度计算
  - [ ] 桥接节点检测
  - [ ] 大图性能可接受 (< 5s)
- [ ] `tests/api/test_graph_insights_api.py`

---

### 3.3 P3 — 增量 Wiki 更新模式

> **重要**：代码库已有 `wiki/incremental.py` 中的 `WikiIncrementalUpdater`，提供基于 file diff 的选择性 Wiki 再生成（`update_from_diff`），包含邻居展开（`CALLS|INHERITS|IMPORTS`）、`graph_version` 管理、glossary 漂移检测、broken ref 修复等能力。**本阶段不新建模块**，而是扩展现有 `WikiIncrementalUpdater`。

#### 3.3.1 核心设计 — 扩展 `wiki/incremental.py`

在现有 `WikiIncrementalUpdater` 上增加以下能力：

```python
class WikiIncrementalUpdater:
    # ... 现有 update_from_diff 保持不变 ...

    async def update_from_index_event(
        self, repository: str, changed_files: list[tuple[str, str | None, str | None]],
        config: WikiConfig,
    ) -> IncrementalUpdateResult:
        """Hook for IncrementalIndexer: 索引完成后自动触发 Wiki 增量更新。
        复用 update_from_diff 的核心逻辑，增加:
        1. 自动获取 previous_glossary（从缓存）
        2. 运行 lint 验证更新后一致性（可选）
        3. 更新 index.md 和 overview.md（通过 WikiComposer）
        4. 记录更新日志
        """
        previous_glossary = self._cache.get_glossary(repository)
        result = await self.update_from_diff(
            repository, changed_files, config,
            previous_glossary=previous_glossary,
        )
        if result.affected_pages:
            await self._update_index_and_overview(repository, config)
            await self._append_update_log(repository, result)
        return result

    async def _update_index_and_overview(self, repository: str, config: WikiConfig) -> None:
        """Regenerate index.md and overview.md after incremental update."""
        ...

    async def _append_update_log(self, repository: str, result: IncrementalUpdateResult) -> None:
        """Append incremental update summary to log.md."""
        ...
```

**受影响页面查找**：复用现有 `_expand_neighbors`（1-hop via `CALLS|INHERITS|IMPORTS`）和 `_resolve_page_paths` 方法，以及 `GraphQueryService.find_impact_scope` / `analyze_pr_impact` 的现有影响分析逻辑。

#### 3.3.2 触发机制

```
当前流程:
  git push → IncrementalIndexer → 图更新 → (无 Wiki 更新)

增量流程:
  git push → IncrementalIndexer → 图更新
    → WikiIncrementalUpdater.update_from_index_event(changed_files)
      → 复用 update_from_diff（邻居展开 + 选择性重生成）
      → 更新 index.md + overview.md
      → [可选] lint 验证
      → 追加 log.md
```

可通过配置项 `wiki.auto_update_on_index: bool = False` 控制（默认关闭，需手动启用）。

#### 3.3.3 测试清单

- [ ] `tests/wiki/test_incremental_index_hook.py`（扩展现有 `tests/wiki/unit/test_incremental.py`）
  - [ ] `update_from_index_event` 正确调用 `update_from_diff`
  - [ ] 自动获取 previous_glossary 从缓存
  - [ ] index.md 和 overview.md 被更新
  - [ ] log.md 记录更新摘要
  - [ ] 无受影响页面时不更新 index/log
  - [ ] 配置关闭时不触发
- [ ] `tests/wiki/test_incremental_index_integration.py`

---

### 3.4 P4 — 两步链式思考摄取 (CoT Ingest)

#### 3.4.1 核心设计

新建 `wiki/cot_generator.py`：

```python
@dataclass
class CoTAnalysis:
    core_responsibilities: list[str]
    key_interactions: list[dict[str, str]]
    contradictions: list[dict[str, str]]
    structure_suggestions: list[str]
    review_items: list[dict[str, str]]

@dataclass
class CoTGenerationResult:
    analysis: CoTAnalysis
    pages: list[WikiPage]
    contradictions: list[dict[str, str]]
    review_items: list[dict[str, str]]

class CoTWikiGenerator:
    async def generate_with_cot(
        self, scope: WikiScope, existing_wiki: dict[str, str]
    ) -> CoTGenerationResult:
        # Step 1: 分析
        analysis = await self._analyze(scope, existing_wiki)
        # Step 2: 生成
        pages = await self._generate(analysis, scope)
        return CoTGenerationResult(
            analysis=analysis, pages=pages,
            contradictions=analysis.contradictions,
            review_items=analysis.review_items,
        )
```

#### 3.4.2 Step 1 分析 Prompt 框架

```
你是一个代码架构分析师。基于以下代码图上下文，分析：

1. **核心职责**: 这个模块/类的主要职责是什么？
2. **关键交互**: 它与哪些其他实体有重要交互？
3. **与现有 Wiki 的矛盾**: 现有 Wiki 描述与代码实际状态有哪些不一致？
4. **结构建议**: 哪些 Wiki 页面需要更新/创建/删除？
5. **待审查项**: 哪些内容你不确定，需要人工确认？

输出结构化 JSON。
```

#### 3.4.3 Step 2 生成 Prompt 框架

```
基于以下分析结果和代码上下文，生成/更新 Wiki 页面：

分析结果: {analysis_json}
代码上下文: {smart_context}

要求：
1. 更新交叉引用 [[wikilinks]]
2. 标注矛盾项（如有）
3. 标记待审查内容为 `[REVIEW_NEEDED]`
4. 保持与现有 Wiki 风格一致
```

#### 3.4.4 Human-in-the-Loop 审查（范围说明）

P4 生成的 `review_items` 和 `[REVIEW_NEEDED]` 标记仅作为 **内容标注**，嵌入 Wiki 页面文本中。**本提案不包含**独立的审查工作流存储、状态机或 triage API。原因：
- KBS 定位为代码知识库服务，不是审批系统
- `[REVIEW_NEEDED]` 标记可被 Wiki Lint（P1）检测为 info 级别 issue，实现闭环
- 如未来需要完整审查工作流，可作为独立提案设计

#### 3.4.5 成本控制

- Step 1 使用较小/较快的模型（如 gpt-4o-mini / claude-3-haiku）
- Step 2 使用完整模型（如 gpt-4o / claude-3-sonnet）
- 可通过配置项 `wiki.cot_analysis_model` 和 `wiki.cot_generation_model` 分别配置

#### 3.4.6 测试清单

- [ ] `tests/wiki/test_cot_generator.py`
  - [ ] Step 1 分析产出结构化 JSON
  - [ ] Step 2 生成合法 Wiki 页面
  - [ ] 矛盾检测标记正确
  - [ ] review_items 被正确提取
  - [ ] 配置不同模型正常工作
- [ ] `tests/wiki/test_cot_integration.py`

---

### 3.5 P5 — 文档索引质量优化与 Document-Wiki 融合

> **背景分析**：当前系统存在"两个世界"问题 —— 仓库文档（Document 节点）和 Wiki（WikiPage）是两套并行、无联动的知识表达层。Document 节点参与语义搜索但质量低，Wiki 生成完全不参考仓库文档，导致人工撰写的设计决策、部署指南等高价值信息被浪费。

#### 3.5.1 问题诊断

| # | 问题 | 影响 | 根因 |
|---|------|------|------|
| 1 | 嵌入质量差 | 语义搜索不精准 | `_format_code_text()` 复用代码格式化函数处理文档内容（文档无 signature/docstring） |
| 2 | 截断策略粗糙 | section 内容在不合适位置被截断 | 硬截断 2000 字符，未使用已有的 `smart_chunker` |
| 3 | REFERENCES 不可靠 | 误关联 | 仅按简单名称匹配 `Function/Class`，同名实体全部匹配 |
| 4 | 搜索体验不一致 | 用户困惑 | Document 不参与关键字搜索，仅参与向量搜索 |
| 5 | Wiki 生成不参考仓库文档 | 高价值信息浪费 | WikiComposer 仅使用 Module/Class/Function 上下文 |

#### 3.5.2 Phase A — 嵌入与分块修复

**新增 `_format_doc_text()` 专用函数**（`indexer/embedding_generator.py`）：

```python
def _format_doc_text(title: str, section: str, content: str) -> str:
    """Format document content for embedding generation.
    Unlike code, documents have no signature/docstring structure.
    """
    parts = [f"Document: {title}"]
    if section:
        parts.append(f"Section: {section}")
    parts.append(content)
    return "\n".join(parts)
```

**使用 `smart_chunk_markdown` 替换硬截断**（`indexer/doc_indexer.py`）：

```python
from indexer.smart_chunker import smart_chunk_markdown

class DocumentIndexer:
    def build_graph(self, doc: ParsedDocument) -> tuple[list[GraphNode], list[GraphEdge]]:
        # 对每个 section 的 content 使用 smart_chunk_markdown
        # 而非 section.content[:2000]
        chunks = smart_chunk_markdown(section.content, target_size=2000)
        for chunk in chunks:
            section_node = GraphNode(
                label=NodeLabel.DOCUMENT,
                properties={
                    "content": chunk.text,
                    "heading_context": chunk.heading_context,
                    ...
                },
            )
```

#### 3.5.3 Phase B — REFERENCES 匹配增强

改进 `resolve_cross_file_edges` 中的 REFERENCES 匹配策略：

```python
# 当前：仅按简单名称匹配
"OPTIONAL MATCH (f:Function {name: ref})"

# 改进：优先 FQN 精确匹配，回退到 name + file 路径消歧
"OPTIONAL MATCH (f:Function) WHERE f.fqn = ref OR "
"(f.name = ref AND f.file CONTAINS doc.file_dir)"
```

同时在 `doc_indexer._extract_code_references` 中保留完整的 `Foo.bar` 格式（当前仅取最后一段）。

#### 3.5.4 Phase C — Document-Wiki 融合

**核心设计**：Document 节点不再直接参与用户可见的搜索结果，而是作为 Wiki 生成的输入源。

```
融合后数据流：
  仓库文档 → DocumentIndexer → Document 节点（保留，作为源材料）
     │
     ├── REFERENCES 边 → code entities（增强后的匹配）
     └── 新增 SOURCE_DOC 边 → WikiPage（Wiki 页面引用了哪些仓库文档）
         │
  代码图 + Document 上下文 → WikiComposer (CoT Step 1) → WikiPage
         │
  搜索统一出口 → WikiPage（Document 不再直接返回给用户）
```

**新增 `EdgeType.SOURCE_DOC`**（`store/schema.py`）：

```python
class EdgeType(StrEnum):
    ...
    SOURCE_DOC = "SOURCE_DOC"  # WikiPage → Document（Wiki 页面参考的仓库文档）
```

**SOURCE_DOC 边创建时机**：在 WikiComposer 生成页面后，由 P5.C 的融合逻辑基于 CoT Step 1 发现的相关 Document 创建。具体流程：
1. CoT Step 1 分析时调用 `_find_related_docs()` 获取相关 Document 列表
2. WikiPage 生成完成后，为每个被参考的 Document 创建 `SOURCE_DOC` 边
3. 边创建在 `WikiService.generate()` 的后处理步骤中执行

**WikiComposer 集成 Document 上下文**（与 P4 CoT 协同）：

在 CoT Step 1 分析阶段，查找与当前 scope 相关的 Document 节点作为额外上下文：

```python
async def _find_related_docs(self, scope_entities: list[str]) -> list[str]:
    """Find repository documents that REFERENCE the entities in scope."""
    query = (
        "MATCH (d:Document)-[:REFERENCES]->(e) "
        "WHERE e.name IN $entities OR e.fqn IN $entities "
        "RETURN DISTINCT d.file AS file, d.content AS content "
        "LIMIT 5"
    )
    ...
```

**搜索层调整**：`semantic_query.search_all()` 中 Document 节点的结果降权或从用户可见结果中过滤（通过配置项控制）：

```python
# config.py
class SearchConfig:
    include_raw_docs_in_results: bool = False  # 默认不展示原始 Document 结果
```

#### 3.5.5 测试清单

- [ ] `tests/embedding/test_format_doc_text.py`
  - [ ] 文档嵌入文本包含 title/section/content
  - [ ] 与 _format_code_text 格式不同
- [ ] `tests/indexer/test_doc_indexer_chunking.py`
  - [ ] 使用 smart_chunker 替代硬截断
  - [ ] 代码块不被分割
  - [ ] chunk 间有 overlap
- [ ] `tests/indexer/test_references_enhanced.py`
  - [ ] FQN 精确匹配优先
  - [ ] 同名实体通过路径消歧
  - [ ] 保留完整 `Foo.bar` 格式
- [ ] `tests/wiki/test_doc_wiki_fusion.py`
  - [ ] WikiComposer 查找相关 Document 节点
  - [ ] SOURCE_DOC 边正确创建
  - [ ] 搜索结果不直接包含 Document（配置控制）

---

### 3.6 P6 — Wiki Export（仓库文档反向更新）

> **设计原则**：KBS 是读取服务，不应自动写入仓库。Wiki Export 必须是**用户主动触发**的操作，通过 diff 预览或 PR 机制让用户控制写入。

#### 3.6.1 核心设计

新建 `wiki/exporter.py`：

```python
@dataclass
class ExportDiff:
    file_path: str  # 仓库中的目标文件路径
    action: Literal["create", "update", "skip"]
    wiki_content: str  # Wiki 生成的内容
    repo_content: str | None  # 仓库中现有内容（如有）
    diff_summary: str  # 人类可读的变更摘要

@dataclass
class ExportResult:
    diffs: list[ExportDiff]
    total_files: int
    created: int
    updated: int
    skipped: int

class WikiExporter:
    async def preview_export(
        self, repository: str, target_dir: str,
        *, include_auto_generated_marker: bool = True,
    ) -> ExportResult:
        """Generate diff preview without writing files.
        1. 获取所有 WikiPage
        2. 匹配仓库中的现有文档文件（通过 SOURCE_DOC 边或路径推断）
        3. 生成 diff 预览
        4. 标记自动生成的内容（<!-- AUTO-GENERATED BY KBS -->）
        """
        ...

    async def execute_export(
        self, repository: str, target_dir: str,
        *, selected_files: list[str] | None = None,
    ) -> ExportResult:
        """Write selected files to target directory.
        Only writes files explicitly selected by user.
        """
        ...
```

#### 3.6.2 安全机制

1. **禁止自动回写**：无自动触发路径，必须通过 API/MCP 手动调用
2. **diff 预览**：`preview_export` 返回完整 diff，不写文件
3. **选择性写入**：`execute_export` 仅写入用户明确选择的文件
4. **自动生成标记**：所有导出内容包含 `<!-- AUTO-GENERATED BY KBS -->` 标记
5. **人工内容保护**：如果仓库文件不包含自动生成标记，视为纯人工内容，`action=skip`
6. **循环依赖阻断**：导出的文件在 Document 索引时可通过标记识别跳过

#### 3.6.3 API 与 MCP

```python
# POST /api/v1/wiki/{repository}/export/preview
# POST /api/v1/wiki/{repository}/export/execute
# MCP tool: wiki_export_preview, wiki_export_execute
```

#### 3.6.4 测试清单

- [ ] `tests/wiki/test_exporter.py`
  - [ ] preview_export 不写文件
  - [ ] execute_export 仅写选中文件
  - [ ] 自动生成标记正确添加
  - [ ] 纯人工内容文件被 skip
  - [ ] diff_summary 准确描述变更
  - [ ] 无 WikiPage 时返回空结果
- [ ] `tests/api/test_wiki_export_api.py`

---

## 4. 实施计划

### 4.1 Phase 分解与依赖

```
P1 Wiki Lint         ── 无依赖，可先行启动
P2 图洞察            ── 无依赖，可与 P1 并行
P3 增量 Wiki 更新    ── 软依赖 P1 (lint 作为可选验证步骤)
P4 CoT Ingest        ── 软依赖 P3 (CoT 可独立运行，两步生成策略不依赖 Document 上下文)
P5 文档索引优化      ── P5.A/B 无依赖，可与 P1/P2 并行；P5.C 依赖 P4
P6 Wiki Export       ── 依赖 P5.C (需要 SOURCE_DOC 边)
```

> **依赖说明**：
> - P5 分为 3 个子阶段：P5.A（嵌入修复）和 P5.B（REFERENCES 增强）无依赖，可与 P1/P2 并行启动
> - P5.C（Document-Wiki 融合）依赖 P4（CoT 作为集成点）。**P4 不依赖 P5.C**，P4 的核心是两步生成策略，可独立实现；P5.C 在 P4 基础上增加 Document 上下文注入
> - P6（Wiki Export）依赖 P5.C（需要 SOURCE_DOC 边来匹配 Wiki 和仓库文档）
> - P4 的核心是替换 `WikiComposer` 的生成策略（单步→两步），不需要增量更新或 Document 融合能力

### 4.2 Subagent 编排

| Phase | Subagent 数量 | 步骤 |
|-------|:------------:|------|
| **P1** | 3 | P1-A (Service+Tests) ∥ P1-B (API+MCP) → P1-C (Frontend) → Review |
| **P2** | 3 | P2-A (Service+Tests) ∥ P2-B (API+MCP) → P2-C (Frontend) → Review |
| **P3** | 2 | P3-A (Core+Tests) → P3-B (Integration) → Review |
| **P4** | 3 | P4-A (Analysis Step) → P4-B (Generation Step) → P4-C (Integration) → Review |
| **P5** | 3 | P5-A (嵌入+分块修复+Tests) ∥ P5-B (REFERENCES增强+Tests) → P5-C (融合+Tests) → Review |
| **P6** | 2 | P6-A (Exporter+Tests) → P6-B (API+MCP+Frontend) → Review |

### 4.3 文件变更预估

| Phase | 新增文件 | 修改文件 |
|-------|---------|---------|
| P1 | `wiki/lint.py`, `tests/wiki/test_lint.py`, `tests/api/test_wiki_lint_api.py`, `dashboard/src/components/wiki/LintPanel.tsx` | `wiki/models.py`（增加 `generated_at`）, `main.py`, `api/mcp_server.py`, `service.py` |
| P2 | `query/graph_insights.py`, `tests/query/test_graph_insights.py`, `tests/api/test_graph_insights_api.py`, `dashboard/src/components/InsightsPanel.tsx` | `main.py`, `api/mcp_server.py`, `service.py` |
| P3 | `tests/wiki/test_incremental_index_hook.py` | `wiki/incremental.py`（扩展 `WikiIncrementalUpdater`）, `wiki/service.py`, `indexer/incremental_indexer.py`, `config.py` |
| P4 | `wiki/cot_generator.py`, `tests/wiki/test_cot_generator.py` | `wiki/composer.py`（集成 CoT 策略）, `wiki/service.py`, `config.py` |
| P5.A | `tests/embedding/test_format_doc_text.py`, `tests/indexer/test_doc_indexer_chunking.py` | `indexer/embedding_generator.py`（新增 `_format_doc_text`）, `indexer/doc_indexer.py`（集成 `smart_chunker`）, `service.py` |
| P5.B | `tests/indexer/test_references_enhanced.py` | `store/falkordb_store.py`（增强 REFERENCES 匹配）, `indexer/doc_indexer.py`（保留完整 FQN） |
| P5.C | `tests/wiki/test_doc_wiki_fusion.py` | `store/schema.py`（新增 `SOURCE_DOC`）, `wiki/composer.py`, `query/semantic_query.py`, `config.py` |
| P6 | `wiki/exporter.py`, `tests/wiki/test_exporter.py`, `tests/api/test_wiki_export_api.py` | `main.py`, `api/mcp_server.py` |

> **注意**：`wiki/generator.py` 不存在。Wiki 生成由 `WikiComposer`（`wiki/composer.py`）和 `WikiService`（`wiki/service.py`）协作完成。P4 的 CoT 策略直接集成到 `WikiComposer` 中。

---

## 5. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| Wiki Lint Cypher 查询性能 | 中 | 批量查询而非逐个，缓存结果 |
| 图洞察循环依赖检测复杂度 | 中 | 限制深度 (5 跳)，超时保护（FalkorDB query timeout） |
| 增量 Wiki 更新可能遗漏受影响页面 | 中 | 提供全量重生成兼容选项 + lint 验证 |
| CoT 增加 LLM 调用成本 | 中偏高 | Step 1 用较小模型；双调用成本约为单步的 1.3-1.8 倍（Step 1 token 少）；可配置是否启用 |
| 跨层调用检测依赖 architecture_layer 标注质量 | 低 | architecture_layer 由 GraphEnricher 自动标注，已验证 |
| **Lint/Insights 误报** | 中 | 孤立实体排除已知根节点（README/overview）；coverage gap 仅检查有 `semantic_roles` 标注的实体 |
| **CoT Step 2 非确定性 & Prompt Injection** | 中 | Step 1 输出经过 JSON Schema 校验；Wiki 内容作为 Step 2 输入前进行 sanitize；非确定性通过 temperature=0 + 结果校验缓解 |
| **并发安全：增量 Wiki 更新 vs 并发索引** | 中 | 复用现有 `WikiIncrementalUpdater._version_lock` (asyncio.Lock)；`graph_version` 乐观锁已有保护 |
| **Document 嵌入格式变更导致搜索回归** | 低 | P5.A 修改 `_format_doc_text` 后需重建 Document 嵌入；提供 `--rebuild-doc-embeddings` 迁移命令 |
| **REFERENCES 匹配增强可能引入新误匹配** | 低 | FQN 精确匹配优先，name+path 回退有明确消歧规则；测试覆盖 edge case |
| **Wiki Export 循环依赖风险** | 中 | 导出内容包含 `<!-- AUTO-GENERATED BY KBS -->` 标记；索引时识别该标记可跳过或标记为 auto-generated source |
| **Document 从搜索结果移除影响用户体验** | 低 | 通过 `include_raw_docs_in_results` 配置项控制，默认关闭但可开启兼容旧行为 |

---

## 6. 补充测试要求

以下补充测试点适用于所有 Phase：

- **Golden/Snapshot 测试**：`LintReport` 和 `InsightsReport` 的 JSON 输出格式必须稳定（供 Dashboard 和 MCP 消费），使用 snapshot test 固化字段名
- **MCP/REST 一致性**：MCP tool 返回结构与 REST API 响应结构必须一致，参考现有 `WikiMCPHandler` / `wiki_routes` 的对称模式
- **FalkorDB 边界**：变长路径查询（循环依赖检测）的 timeout 保护测试；全文索引存在性验证
- **并发安全**：增量 Wiki 更新与并行索引的 `graph_version` / 缓存失效竞态测试
- **P5 嵌入回归**：新 `_format_doc_text` 格式下 Document 语义搜索精度应不低于旧格式（提供 `--rebuild-doc-embeddings` 迁移命令后需验证）

---

## 7. 验收标准

- [ ] **P1**: `POST /wiki/lint` 返回健康报告，覆盖 5 类检查，Dashboard 展示
- [ ] **P2**: `GET /graph/insights/{repository}` 返回架构异常报告，覆盖 5 类检测，Dashboard 展示
- [ ] **P3**: 增量索引后仅受影响的 Wiki 页面被重新生成，lint 通过
- [ ] **P4**: Wiki 生成采用两步流程，分析结果可审查，矛盾被标记
- [ ] **P5.A**: Document 嵌入使用专用 `_format_doc_text()`，分块使用 `smart_chunker`，搜索精准度提升
- [ ] **P5.B**: REFERENCES 匹配优先 FQN 精确匹配，同名实体通过路径消歧
- [ ] **P5.C**: WikiComposer 在 CoT 分析阶段参考相关 Document 节点，`SOURCE_DOC` 边正确建立
- [ ] **P6**: Wiki Export 功能可用，`preview_export` 不写文件，`execute_export` 仅写选中文件，纯人工内容不被覆盖

---

*提案由 Karpathy llm-wiki 模式 + nashsu/llm_wiki 项目分析驱动，并融合了对现有文档索引体系的深度审视。核心思路：将文档知识库的"增量编译 + 持续维护 + 健康检查"理念适配到代码知识库场景，消除 Document 与 Wiki 的"两个世界"问题，利用 KBS 已有的图基础设施实现差异化竞争优势。*
