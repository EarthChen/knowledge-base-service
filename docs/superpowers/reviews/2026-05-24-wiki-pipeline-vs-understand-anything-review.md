# Wiki 管道深度审阅与 Understand-Anything 对比分析

**日期**: 2026-05-24
**范围**: Wiki 生成管道全链路（域分类、文档生成、质量保障、Agent 框架、前端）+ Understand-Anything 源码级对比
**分析方法**: code-explorer 深度源码分析
**产出**: 12 项优化建议，按优先级 × ROI 排序

---

## 一、项目定位对比

| 维度 | Knowledge Base Service | Understand-Anything |
|------|----------------------|---------------------|
| **架构模式** | 独立后端服务（FastAPI + FalkorDB） | Claude Code / Cursor Plugin（Markdown Agent 驱动） |
| **编排引擎** | LangGraph StateGraph（17 节点 + 条件路由） | SKILL.md Prompt（6 阶段，零编排代码） |
| **存储** | FalkorDB 图 + 向量索引 + Redis + SQLite | `knowledge-graph.json` 静态文件 |
| **域分类** | 图算法聚类 + 嵌入 + LLM 命名 + 全局审查 | 纯 LLM subagent |
| **文档生成** | 完整 LangGraph Wiki 管线（explore→write→heal 循环） | 无（仅节点级 1-2 句摘要） |
| **搜索** | 3-way RRF + rerank + 图扩展 | Fuse.js fuzzy（semantic 未接入） |
| **语言支持** | 8 种（Tree-sitter Query 声明式） | 40+（TS extractor 命令式 + 非代码 parser） |
| **Dashboard** | React + TanStack Query（Wiki 管理导向） | React + Zustand + ELK（图探索导向） |

---

## 二、当前管道自审发现（6 项）

### 2.1 域分类子域命名 LLM 串行瓶颈

**位置**: `wiki/nodes/graph_domain_decompose.py` → `_recursive_split()`

**问题**: 对每个子域顺序 `await namer.name_community()`。当大域有 5+ 子域且递归深度 >1 时，LLM 调用串行化成为瓶颈。

**当前代码逻辑**:
```
for sub_cluster in sub_clusters:
    sub_naming = await namer.name_community(sub_infos, used_names, business_id)
```

**建议**: 同级子域命名用 `asyncio.gather` 并行化，受 `PipelineConcurrency` semaphore 控制。

### 2.2 `_RELATED_KEYWORDS` 硬编码

**位置**: `wiki/nodes/graph_domain_decompose.py` 第 7-49 行

**问题**: 仅覆盖 6 组业务关键词（intimacy/auth/payment/order/notification/family），不同业务项目无法自适应。硬编码无法覆盖未知业务领域的同义词关系。

**建议**: 移除硬编码，改为 LLM 动态发现同义词组。具体方案：

1. 在 `_merge_domains_by_keyword` 之前，收集所有域的 slug + display_name + 模块名列表
2. 调用 LLM 一次性分析哪些域在业务语义上应该合并（prompt 示例）：
   ```
   给定以下域列表及其模块，识别哪些域在业务语义上是同一个概念的不同方面，应该合并：
   域A: {slug, display_name, modules[:5]}
   域B: ...
   输出: [{merge_group: [slugA, slugB], reason: "..."}, ...]
   ```
3. LLM 返回合并建议后，执行与当前 `_merge_domains_by_keyword` 相同的合并逻辑
4. 可保留 `_RELATED_KEYWORDS` 作为 LLM 不可用时的 fallback

**优势**: 自适应任何业务领域，无需人工维护关键词表；LLM 可识别更复杂的语义关联（如 "购物车" 和 "结算" 属于同一购买流程）。

**成本**: 增加 1 次 LLM 调用（输入量 = 域数 × ~50 tokens，通常 < 2K tokens），可接受。

### 2.3 Heal fallback 链过长且耦合

**位置**: `wiki/nodes/heal.py` → `_heal_one_page()`

**问题**: TargetedHealer → WikiPageAgent.enrich → raw LLM generate 三条路径在单函数内串联，职责不清晰。

**建议**: 抽象为 `HealStrategy` 接口，每条路径独立可测试、可配置优先级。

### 2.4 Agent Runner 仅检测连续重复

**位置**: `wiki/agents/runner.py` 第 221-231 行

**问题**: 仅捕获 A→A→A 模式，无法检测 A→B→A→B 交替重复。

**建议**: 滑动窗口内 unique call ratio 检测（窗口 6 次调用，unique < 3 则视为重复）。

### 2.5 Quality Gate L3 触发条件过严

**位置**: `wiki/pipeline_graph.py` → `quality_gate_node()`

**问题**: L3 LLM Judge 仅对 `tier==CORE AND L1≥0.7` 触发。heal 后质量提升的页面不会获得 L3 评估。

**建议**: heal 后的 CORE 页若 L1 从 <0.7 升至 ≥0.7，应强制触发 L3。

### 2.6 WikiKnowledgeGraph 网格布局

**位置**: `dashboard/src/components/wiki/WikiKnowledgeGraph.tsx` 第 62-78 行

**问题**: `sqrt(n)` 列网格排列，无法反映域间关系。

**建议**: 引入 dagre/ELK 力导向布局（项目已依赖 `@xyflow/react`）。

---

## 三、Understand-Anything 可借鉴点（6 项）

### 3.1 Guided Tour 学习路径

**UA 实现**: `tour-generator.ts` → Kahn 拓扑排序 + 架构层分组

```
算法伪代码:
  build inDegree + adjacency from edges
  queue = nodes with inDegree == 0
  while queue: pop → topoOrder; decrement neighbors
  group by layer → TourStep[]
  assign order = 1..N
```

**输出结构**: `TourStep { order, title, description, nodeIds[], languageLesson? }`

**我们可以做**: 在 `create_links` 后增加 `generate_tour_node`，利用 `module_call_edges` 做 Kahn 拓扑排序，生成推荐阅读序列存为特殊 WikiPage。

### 3.2 架构层自动标注

**UA 实现**: `layer-detector.ts` 基于路径段匹配 8 种层

```
LAYER_PATTERNS (first-match-wins):
  routes/controller/handler/api → API Layer
  service/usecase/business → Service Layer
  model/entity/schema/repository → Data Layer
  component/view/page/ui → UI Layer
  middleware/interceptor/guard → Middleware Layer
  test/spec/__tests__ → Test Layer
  config/setting/env → Configuration Layer
  (default) → Core
```

**我们可以做**: 在 `EntityRoleClassifier` 之外增加 `ArchitecturalLayerClassifier`，结合路径模式 + 调用图入度/出度分析（我们已有的图信息）做更精准的层标注。

### 3.3 非代码文件覆盖

**UA 实现**: 40+ `LanguageConfig` 含 Dockerfile/Kubernetes/Terraform/OpenAPI/SQL 等

```typescript
interface LanguageConfig {
  extensions: string[];
  concepts: string[];          // LLM prompt 语义概念注入
  filePatterns: {
    entryPoints: string[];     // 入口文件模式
    tests: string[];           // 测试文件模式
    config: string[];          // 配置文件模式
  };
}
```

**我们可以做**: `indexer/languages/` 新增 Dockerfile/K8s YAML/Protobuf 轻量 parser。先支持结构提取（service 名、端口、依赖），不需要完整 Tree-sitter AST。

### 3.4 增量更新三级变更分类

**UA 实现**: `fingerprint.ts` + `change-classifier.ts`

```
FileFingerprint = { contentHash, functions[], classes[], imports[], exports[] }

compareFingerprints:
  contentHash 相同 → NONE
  签名不变 → COSMETIC（纯注释/格式改动，跳过重分析）
  签名变化 → STRUCTURAL（重分析）

classifyUpdate:
  全部 NONE/COSMETIC → SKIP
  少量 STRUCTURAL → PARTIAL_UPDATE
  目录结构变化或 >10 structural → ARCHITECTURE_UPDATE
  >30 structural 或 >50% → FULL_UPDATE
```

**我们可以做**: `incremental_indexer.py` 增加函数签名指纹比较。Tree-sitter 已提取函数/类签名，只需缓存并比对。COSMETIC 变更跳过重索引和域重分类。

### 3.5 语言概念注入 Agent Prompt

**UA 实现**: `LanguageConfig.concepts[]` 注入到 `file-analyzer` prompt

```typescript
// python.ts
concepts: ["decorators", "list comprehensions", "generators and iterators",
           "context managers", "type hints and annotations"]
```

**我们可以做**: `LanguagePlugin` 增加 `concepts: list[str]` 字段，`WikiPageAgent` explore 阶段根据目标模块语言注入对应概念提示，提高 LLM 摘要精准度。

### 3.6 Business Flow 三级域模型

**UA 实现**: `domain-analyzer.md` → domain → flow → step 三层

```
Business Domain (domain:order-management)
  └─ Business Flow (flow:create-order)       [contains_flow 边]
       └─ Business Step (step:validate-input) [flow_step 边, weight=顺序]
```

**我们可以做**: 扩展 `domain_tree` 支持 domain→flow→step 三级。用调用链分析（`CallChainBuilder`）提取 entry_point→service→repository 调用路径作为 flow，路径中每个节点为 step。

---

## 四、优化建议 ROI 排序

### 评估维度

- **Impact**: 对用户体验/文档质量/性能的直接提升（H/M/L）
- **Effort**: 实现工作量（S=1-2h, M=4-8h, L=8-16h, XL=16h+）
- **ROI**: Impact ÷ Effort，综合排名
- **Risk**: 引入回归风险（H/M/L）

### 排序表

| # | 建议 | Impact | Effort | ROI | Risk | 来源 |
|---|------|--------|--------|-----|------|------|
| 1 | 子域命名 LLM 并行化 | M | S(1h) | ★★★★★ | L | 自审 §2.1 |
| 2 | `_RELATED_KEYWORDS` 改为 LLM 动态发现 | M | S(2h) | ★★★★★ | L | 自审 §2.2 |
| 3 | WikiKnowledgeGraph 引入 dagre 布局 | H | M(4h) | ★★★★☆ | L | UA §3.6 + 自审 §2.6 |
| 4 | 架构层自动标注 | H | M(6h) | ★★★★☆ | L | UA §3.2 |
| 5 | 增量更新三级变更分类 | H | M(6h) | ★★★★☆ | M | UA §3.4 |
| 6 | Guided Tour 学习路径生成 | H | M(8h) | ★★★☆☆ | L | UA §3.1 |
| 7 | 语言概念注入 Agent Prompt | M | S(2h) | ★★★☆☆ | L | UA §3.5 |
| 8 | Agent Runner 交替重复检测 | M | S(2h) | ★★★☆☆ | L | 自审 §2.4 |
| 9 | Heal fallback 策略模式重构 | M | M(4h) | ★★★☆☆ | M | 自审 §2.3 |
| 10 | Business Flow 三级域模型 | H | L(12h) | ★★☆☆☆ | M | UA §3.6 |
| 11 | 非代码文件轻量解析 | M | L(12h) | ★★☆☆☆ | L | UA §3.3 |
| 12 | Quality Gate L3 heal 后触发 | L | S(1h) | ★★☆☆☆ | L | 自审 §2.5 |

### 推荐实施批次

**Batch 1（1-2 天，快速见效）**: #1 + #2 + #7 + #8 + #12
- 全部 S 级工作量，总计 ~7h
- 域分类性能提升 + Agent 鲁棒性提升

**Batch 2（3-5 天，核心提升）**: #3 + #4 + #5
- 前端可视化质的飞跃 + 架构理解能力增强 + 索引效率提升
- 总计 ~16h

**Batch 3（1-2 周，功能扩展）**: #6 + #9 + #10
- Guided Tour 新功能 + heal 代码质量 + 域模型深度
- 总计 ~24h

**Batch 4（视需求）**: #11
- 非代码文件覆盖，ROI 受项目类型影响

---

## 五、Understand-Anything 劣势总结（我们的护城河）

以下 6 项是我们相对 UA 的**代码级核心优势**，不应在借鉴中弱化：

| 优势 | 代码位置 | UA 缺失原因 |
|------|----------|------------|
| **持久化图数据库** | `store/falkordb_store.py` | UA 用 JSON 文件，无 Cypher 查询/向量检索 |
| **完整 Wiki 生成管线** | `wiki/pipeline_graph.py` 17 节点 | UA 仅生成节点摘要，无文档 |
| **图算法域分类** | `graph_domain_decompose.py` HAC+调用图+LLM | UA 纯 LLM 不可复现 |
| **3-way RRF 混合搜索** | `query/hybrid_query.py` | UA 仅 Fuse.js fuzzy |
| **Agent 框架** | `wiki/agents/runner.py` ReAct 引擎 | UA 无代码级 agent loop |
| **质量保障体系** | `wiki/quality_evaluator.py` L1/L2/L3 | UA 无质量门/heal |

---

## 六、关键代码路径速查

| 模块 | 核心文件 | 关键函数/类 |
|------|---------|------------|
| 管线编排 | `wiki/pipeline_graph.py` | `build_wiki_pipeline()`, `should_heal()` |
| 实体角色 | `wiki/entity_role_classifier.py` | `EntityRoleClassifier.classify()`, `compute_score()` |
| 图分解 | `wiki/graph_module_decomposer.py` | `GraphModuleDecomposer.decompose_from_graph()` |
| 域分类 | `wiki/nodes/graph_domain_decompose.py` | `graph_driven_domain_decompose_node()` |
| 域文档 | `wiki/domain_doc_agent.py` | `DomainDocAgent.generate_with_iterations()` |
| 页面 Agent | `wiki/page_agent.py` | `WikiPageAgent` 15 个 `@function_tool` |
| Agent 引擎 | `wiki/agents/runner.py` | `run_agent_loop()` |
| 质量评估 | `wiki/quality_evaluator.py` | `WikiQualityEvaluator.structural_check()` |
| Heal | `wiki/nodes/heal.py` | `heal_pages_node()`, `_heal_one_page()` |
| 并发控制 | `wiki/pipeline_concurrency.py` | `PipelineConcurrency.semaphore()` |
| 知识图谱 | `dashboard/src/components/wiki/WikiKnowledgeGraph.tsx` | `useMemo` 布局计算 |

---

## 附录：Understand-Anything 核心模块索引

| 模块 | 路径 | 职责 |
|------|------|------|
| 编排入口 | `skills/understand/SKILL.md` | 6 阶段 Prompt 编排 |
| 项目扫描 | `agents/project-scanner.md` | 文件发现 + import map |
| 文件分析 | `agents/file-analyzer.md` + `packages/core/src/plugins/` | Tree-sitter + LLM hybrid |
| 域分析 | `agents/domain-analyzer.md` | 纯 LLM 三层域模型 |
| 架构层 | `packages/core/src/analyzer/layer-detector.ts` | 路径模式匹配 + LLM |
| Tour | `packages/core/src/services/tour-generator.ts` | Kahn 拓扑排序 |
| 增量指纹 | `packages/core/src/analyzer/fingerprint.ts` | SHA-256 + 签名级比对 |
| Schema | `packages/core/src/schema.ts` | 4 层 Zod 校验 + 50+ alias |
| Dashboard 状态 | `packages/dashboard/src/store.ts` | Zustand 27KB |
| 图可视化 | `packages/dashboard/src/components/GraphView.tsx` | ELK 两阶段布局 |
| 社区检测 | `packages/dashboard/src/utils/louvain.ts` | graphology-communities-louvain |
| 搜索 | `packages/dashboard/src/utils/search.ts` | Fuse.js weighted keys |
