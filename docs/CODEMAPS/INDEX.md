# 代码地图索引（Code Map）

**最后更新：** 2026-06-01  
**仓库：** `knowledge-base-service`（FastAPI + React/Vite + FalkorDB）

本页是后端与仪表盘的**结构性入口索引**：按分层列出启动点、目录树要点、Wiki 子系统、前端区域、阶段性能力模块与相关文档链接。实现细节仍以源码与专题文档为准。

---

## 架构要点（2026-05 重构）

- **`core/container.AppContainer`**：以依赖注入容器替代零散的全局可变单例，统一装配存储、Wiki、LLM、任务队列等依赖。
- **`api/mcp_registry.py`**：`@mcp_tool` 装饰器 + `collect_tools()`，将 MCP 处理方法自动汇入主服务分派表。
- **`main.py` 生命周期**：`lifespan` 拆分为 `_init_security`、`_init_core_services`、`_init_wiki_and_lint` 与 `_shutdown_all`，便于理解与扩展启动/关停顺序。
- **`api/kb_state.py`**：从全局模块侧面向 `AppContainer` 过渡的衔接层（测试与遗留导入仍可指向此处）。

---

## 入口一览（Entry Points）

| 分层 | 路径 | 说明 |
|------|------|------|
| **HTTP 应用** | `main.py` | FastAPI 应用构造、`lifespan`、静态资源与路由挂载；安全门禁日志、核心服务与 Wiki/Lint 初始化、关停收尾。 |
| **对外 HTTP API（按角色）** | `api/routes/kb_routers.py` → `api/routes/*_routes.py` | `viewer_router` / `editor_router` / `admin_router` / `public_router` 挂载仓库、索引、搜索、设置、Webhook、业务与 Wiki 等路由；具体处理器分布在各 `*_routes.py`。 |
| **Wiki HTTP 聚合面** | `api/routes/wiki_routes.py` | 前缀 `/api/v1/wiki`：聚合 `wiki_task_routes`、`wiki_contradiction_routes`、`wiki_page_routes`、`wiki_ask_routes`、`wiki_feedback_routes`；另挂载 **`wiki_mcp_tools_router`**，暴露可选 Wiki HTTP MCP 的 list/call 路径（见 `mcp_wiki_http_router`）。 |
| **主 MCP（随应用常驻）** | `api/mcp_server.py` | 主清单 **22** 个工具：**12** 个图谱/RAG 核心（`@mcp_tool` 挂在 `MCPServer`）+ **10** 个 Wiki 相关（定义于 `wiki/mcp_tools.py` 的 `WikiMCPHandler`，含 `unified_knowledge_query` 等；运行时另注册别名 `search_wiki` → `wiki_search`）。HTTP：`GET /api/v1/mcp/tools`、`POST /api/v1/mcp/tool`。 |
| **可选 Wiki HTTP MCP** | `api/mcp_wiki_server.py` | **6** 个工具（`wiki_search`、`wiki_explain`、`wiki_navigate`、`wiki_qa`、`wiki_impact`、`wiki_get_snapshot`）；需 `WIKI__MCP_SERVER_ENABLED` 等配置，由 `wiki_routes` 挂载 `/api/v1/mcp/tools/list` 与 `/api/v1/mcp/tools/call`（字段名为 `name`，与主 MCP 的 `tool_name` 不同）。 |
| **仪表盘 SPA** | `dashboard/src/main.tsx`、`dashboard/vite.config.ts` | React 入口与 Vite 构建配置；路由、Wiki UI、查询与设置页面等均自 `dashboard/src/` 展开。 |

---

## 后端区域（完整目录树要点）

下列树状说明覆盖主要 Python 包与文件职责，便于从「模块边界」而非单文件跳转理解仓库。

```
core/                         # 应用容器：依赖装配与生命周期协作对象（container.py → AppContainer）
api/
  routes/                     # HTTP 路由器
                              # repository / indexing / search / settings / webhooks
                              # wiki_*（page / task / ask / feedback / contradiction / mcp）
                              # business、business_sync、provider、public_health、admin_graph_mcp、kb_dependencies 等
  mcp_server.py               # 主 MCP：Manifest 拼装 + MCPServer 分派（核心 12 + Wiki 清单接入）
  mcp_registry.py             # @mcp_tool、collect_tools、elevated 角色收集
  mcp_wiki_server.py          # 可选 Wiki HTTP MCP（6 工具）
  pagination.py               # 通用游标/偏移分页辅助
  kb_state.py                 # AppContainer 过渡/兼容层
  middleware/                 # 请求日志等
  models/                     # 含 wiki_models 等请求/响应模型
store/
  falkordb_store.py           # 图库连接与通用 Cypher 执行、向量相关能力
  search_store.py             # 面向搜索场景的专用查询
  traversal_store.py          # 调用链、依赖遍历等图遍历封装
  graph_queries.py            # Blast radius、最短路径、社区/结构查询等高层图运算
  wiki_page_store.py          # WikiPage CRUD、版本、diff、仓库级 Wiki 新鲜度等
  wiki_tree_store.py          # Wiki 树（章节、空间、tier 等）
  wiki_qa_store.py            # Wiki Q&A 持久化
  wiki_memory_store.py        # 记忆分层持久化
  wiki_changelog.py           # Wiki 变更日志
  wiki_contradiction_store.py # 矛盾检测结果持久化
  wiki_claim_store.py         # 主张/ supersession 等
  wiki_feedback_store.py      # 用户反馈存储（与路由 wiki_feedback 对应）
  business_manager.py         # 业务实体与图谱侧协作（Business 维度）
  settings_store.py           # 运行时设置持久化
  schema.py                   # 节点标签等 schema 常量
  fqn_utils.py                # FQN 正则与解析共用工具
wiki/
  service.py                  # WikiService：编排生成、增量、业务 Wiki、树链接等对外主门面
  protocols.py                # WikiGraphStorePort、LLM 相关 Protocol
  export_service.py           # 抽取后的导出逻辑（与 MCP/HTTP export 对齐）
  composer.py / repo_composer.py   # 页面合成与仓库级 compose（含 incremental、progress_callback）
  structure_planner.py        # 结构规划
  data_collector.py           # 生成前数据收集
  diagram_gen.py              # Mermaid 等图示生成
  business_domain_planner.py       # 业务域划分（子批次等）
  cross_repo_domain_planner.py     # 跨仓库域归并（并行、超时、缓存、轻量合并 prompt）
  search.py                   # Wiki 侧混合检索
  ask.py                      # Wiki Ask（SSE 流式应答）
  deep_research.py            # 深度研究管线
  confidence_scorer.py / confidence_inputs.py  # 置信度打分与因子
  contradiction_detector.py   # 矛盾检测
  memory_loop.py / memory_tiers.py   # Q&A 记忆闭环与分层管理
  lint.py / lint_scheduler.py # WikiLint 与周期调度
  auto_healer.py              # 自动修复建议/执行（与 lint 流水线配合）
  task_store.py / task_registry.py   # Wiki 异步任务（Redis）与任务类型注册
  bootstrap.py / event_bus.py # 应用内 Wiki 启动装配与事件总线
  compilation_snapshot.py     # 编译/合成快照（MCP wiki_get_snapshot 等）
  feedback_loop.py            # 反馈驱动的再生成
  community_context.py        # 社区上下文注入生成
  reasoning_path.py           # 推理路径展示数据
  offline_pack.py             # 离线包导出
  incremental.py / change_detector.py   # 增量生成与变更检测
  deferred_enrichment.py      # 延后 LLM 富化
  agents_md_generator.py      # AGENTS.md 生成
  entity_role_classifier.py   # 实体角色/噪声分层（抑制过细页面）
  pipeline_graph.py / pipeline_nodes.py   # LangGraph 编排与各节点实现
  topic_page_composer.py      # 主题页合成策略（体量分流）
  tree_builder.py / tree_linker.py        # 树构建与页面挂载（含按 repository 直查 WikiPage 修复循环依赖）
  mcp_tools.py                # Wiki MCP 工具实现与 WIKI_MCP_TOOLS_MANIFEST
  models.py / context.py      # Wiki 领域模型与上下文对象
  model_strategy.py           # 模型路由与默认模型注入（LLMPortBridge 封装）
  rag/                        # RAG 子包：engine.py（迭代 StateGraph）、retriever、composite 等
  dependency_graph.py         # ModuleGraph、HierarchicalDecomposer（批次分解与超时）
  （其余）exporter、persistence、webhook、scheduler、quality_*、business_flow_* 等支撑模块见仓库内同名文件
indexer/                      # Tree-sitter 解析、嵌入、增量索引、代码图构建、chunk、报表等
query/
  hybrid_query.py             # RRF 混合检索引擎（服务端查询编排）
  nl_cypher.py                # 自然语言 → Cypher（含校验/约束思路，供 UI/Agent 路径使用）
  blast_radius.py             # 爆炸半径分析
  graph_query.py / graph_insights.py / community_detection.py / reranker.py 等
llm/
  base_provider.py            # Gateway 适配、LLMPortBridge（complete / generate / generate_stream·收集流）
  provider_factory.py         # LLM Provider 构造
config.py                     # Settings、WikiConfig、Wiki 功能开关等
auth.py                       # Token、Role、依赖注入式鉴权
rate_limiter.py               # 限流中间件安装
log.py                        # structlog 配置
services/                     # Git、调度、RepoRegistry、KB 业务门面等与 HTTP/MCP 协作
utils/                        # 通用工具（含 git 等）
```

说明：**迭代 RAG** 的主实现在 `wiki/rag/engine.py`（LangGraph `StateGraph`），而非顶层单一文件 `rag_engine.py`。

---

## Agent 框架（`wiki/agents/` 包）

Agent 框架采用 **OpenAI Agents SDK 启发** 的分层设计：Agent 身份（工具、提示词）与执行控制（LoopConfig、Hooks）分离。2026-05 下旬起新增上下文压缩（L0–L4）、委托执行、ReviewAgent 质量门与记忆 tier 提升等模块。

### 核心组件

| 文件 | 类/函数 | 职责 |
|------|---------|------|
| **`base_agent.py`** | `GenericAgent`、`ToolRegistry`、`ToolDef`、`RunConfig` | Agent 基类：LLM + 工具注册表 + 内存；`remember()` 写入工作记忆；`restrict_tools()` 限制子轮次可用工具 |
| **`runner.py`** | `run_agent_loop()`、`LoopConfig`、`LoopHooks`、`AgentLoopResult` | **统一执行引擎**：含 `_apply_context_compression()` 渐进压缩管线（L0–L4）；`LoopConfig` 扩展 compaction/trim 等字段 |
| **`token_budget.py`** | `TokenBudgetManager`、`BudgetSnapshot` | 五档压缩阈值评估，驱动 L1–L4 压缩级别选择 |
| **`context_compactor.py`** | `ExploreCompactor`、`micro_compact`、`snip_compact` | L1 micro-compact、L2 snip-compact、L3 九段 LLM 摘要压缩 |
| **`delegation.py`** | `DelegationMode`、`DelegationConfig`、`DelegationResult`、`execute_delegation()` | 子 Agent 委托执行（深度/工具限制；替代 handoff/agent_tool） |
| **`review_agent.py`** | `ReviewAgent`、`QualityVerdict`、`QualityIssue` | 生成内容结构质量检查 |
| **`citation_verifier.py`** | `CitationVerifier` | `source://` 引用溯源校验 |
| **`memory_promotion.py`** | `TierPromoter` | 工作记忆实时 tier 提升（部分接入流水线） |
| **`doc_orchestrator.py`** | `DocOrchestrator`、`QualityResult` | Template Method 文档编排：集成 `ReviewAgent`、可选 CRAG 覆盖率门、`enable_context_trim=True` 默认探索配置 |
| **`tool_decorator.py`** | `@function_tool` | 从函数签名自动生成 ToolDef 并注册 |
| **`agent_tool.py`** | `agent_tool()` | **已弃用**：转发至 `delegation.execute_delegation`（原 Agent-as-Tool 包装） |
| **`context.py`** | `RunContext`、`WikiDeps` | 每次运行的类型化 DI 上下文 |
| **`guardrails.py`** | `InputGuardrail`、`OutputGuardrail`、`PromptLengthGuardrail` | LLM 调用前后的护栏检查 |
| **`tracing.py`** | `AgentTracer`、`Span`、`JsonlTraceProcessor` | 可观测性 Span 记录 |
| **`handoff.py`** | `HandoffConfig`、`execute_handoff()` | **已弃用**：转发至 `delegation.execute_delegation` |
| **`memory.py`** | `AgentMemory`、`MemoryBackend` | Agent 工作内存抽象（ABC + Protocol），替代旧 `Memory` 基类 |
| **`events.py`** | `ToolCallEvent`、`ContentEvent`、`DoneEvent` 等 | SSE/流式事件类型 |

### Agent 类继承关系

```
GenericAgent (ABC)
├── WikiPageAgent      — 14 个 @function_tool 方法, explore/enrich 核心逻辑
└── WikiEditAgent      — 分段编辑 + 流式事件

DocOrchestrator (ABC, Template Method)
├── DomainDocAgent     — 业务域文档
├── TopicDocAgent      — 深度主题页
└── FlowDocAgent       — 业务流程文档

组合式编排器（持有 agent 引用）:
├── AskOrchestrator        — 工具探索 → 生成回答
└── ResearchOrchestrator   — 分解 → N×探索 → 综合
```

### 关联 Wiki Agent 模块（`wiki/` 根目录）

| 文件 | 要点 |
|------|------|
| **`page_agent.py`** | `WikiPageAgent`：`WorkingMemory` 实现 `AgentMemory`；`delegate_submodule` 经 `execute_delegation` 委托子模块探索 |
| **`domain_doc_agent.py`** | `DomainDocAgent`：`is_acceptable` 阈值 0.7；`TopicPlan` / `TopicPlanItem` Pydantic 模型 |
| **`context_manager.py`** | 对话历史裁剪：`_find_recent_boundary` 按 assistant 轮次计数保留近期消息 |
| **`memory_loop.py`** | Q&A 记忆闭环：调用 `increment_wiki_qa_access` 跟踪访问以驱动 tier 提升 |

### 执行流程

```
任何 Agent.run_tool_loop()
  └─ 转换 RunConfig → LoopConfig
     └─ run_agent_loop(agent, system, user, memory, config)
        ├─ Input guardrails
        ├─ Multi-round loop:
        │   ├─ LLM.complete_with_tools()
        │   ├─ Repeated call detection (hash-based)
        │   ├─ Tool dispatch + incorporate
        │   ├─ Early stop check
        │   ├─ _apply_context_compression() (L0–L4, if enable_compaction)
        │   └─ Context trim (if enable_context_trim)
        ├─ LoopHooks.on_loop_complete()
        └─ Output guardrails

DocOrchestrator.generate()
  └─ explore (run_tool_loop + compaction/trim) → write → ReviewAgent → CRAG gate (optional) → evaluate
```

### 工具层级激活

| Tier | 可用轮次 | 典型工具 |
|------|----------|---------|
| 1 | 始终 | query_module_detail, query_call_chain, read_code |
| 2 | ≥ Round 3 | search_entities, read_file, query_implementations |
| 3 | ≥ Round 5 | delegate_submodule, semantic_search, grep_code |

---

## Wiki 子系统（聚焦表）

| 关注点 | 模块（代表性路径） |
|--------|-------------------|
| **编排门面** | `wiki/service.py`（生成、业务 Wiki、挂载树、导出入口） |
| **LangGraph 管线** | `wiki/pipeline_graph.py`、`wiki/pipeline_nodes.py`、`wiki/pipeline_orchestrator.py` |
| **实体粒度 / 主题聚合** | `wiki/entity_role_classifier.py`、`wiki/topic_page_composer.py`、`wiki/topic_structure_planner.py` |
| **跨仓库域与性能** | `wiki/cross_repo_domain_planner.py`、`wiki/business_domain_planner.py`、`wiki/dependency_graph.py`（`HierarchicalDecomposer`） |
| **合成与模板** | `wiki/composer.py`、`wiki/repo_composer.py`、`wiki/page_composer_service.py`、`wiki/page_templates.py` |
| **质量与矛盾** | `wiki/confidence_scorer.py`、`wiki/contradiction_detector.py`、`wiki/lint.py`、`wiki/quality_evaluator.py`、`wiki/quality_score.py` |
| **记忆与遗忘** | `wiki/memory_loop.py`、`wiki/memory_tiers.py`、`wiki/forgetting.py`、`store/wiki_memory_store.py`、`store/wiki_qa_store.py` |
| **检索与问答** | `wiki/search.py`、`wiki/ask.py`、`wiki/deep_research.py`、`wiki/chunk_retriever.py`、`wiki/rag/*` |
| **异步任务与仪表盘进度** | `wiki/task_store.py`、`wiki/task_registry.py`、`api/routes/wiki_task_routes.py`、`store/wiki_page_store.py`（`get_repo_wiki_freshness` 等） |
| **树与导航** | `wiki/tree_builder.py`、`wiki/tree_linker.py`、`store/wiki_tree_store.py` |
| **可观测 / 快照 / 反馈** | `wiki/compilation_snapshot.py`、`wiki/feedback_loop.py`、`store/wiki_feedback_store.py` |
| **MCP 暴露** | `wiki/mcp_tools.py`（主清单 Wiki 工具）、`api/mcp_server.py`（汇总分派） |
| **导出与静态产物** | `wiki/export_service.py`、`wiki/exporter.py`、`wiki/disk_exporter.py`、`wiki/mkdocs_exporter.py`、`wiki/obsidian_exporter.py` 等 |

---

## 前端（仪表盘）区域表

| 区域 | 位置 | 说明 |
|------|------|------|
| **入口与路由** | `dashboard/src/main.tsx`、路由配置相关文件 | SPA 引导与页面路由 |
| **Wiki 页面与组件** | `dashboard/src/pages/`、`dashboard/src/components/wiki/` | 含 `WikiShell`、`WikiTopicTreeNav`、`WikiTopicContent`、`WikiDomainReviewPanel`、`WikiPageReviewBar`、`WikiKnowledgeGraph`、`ReasoningPathPanel`、`OfflinePackDownloadButton`、编辑/diff 相关 UI |
| **业务 Wiki 异步任务** | `dashboard/src/hooks/useWikiRegenerate.ts` | 轮询 `businessWikiTaskStatus`（配合后端 **202** 异步生成） |
| **路径与编码** | `dashboard/src/utils/wikiPath.ts` | Wiki 路径统一编码/解码 |
| **代码块展示** | `dashboard/src/components/wiki/CodeBlock.tsx` | 按需加载语法高亮，控制首屏体积 |
| **全局错误** | `dashboard/src/components/ErrorBoundary.tsx` | 应用级错误边界 |
| **设置** | `dashboard/src/components/settings/` | 令牌、索引与功能开关等 |
| **API 客户端** | `dashboard/src/api/client.ts` | 与后端 `/api/v1` 交互 |
| **测试** | `dashboard/src/pages/__tests__/`、`dashboard/src/components/__tests__/` | 页面冒烟与布局/无障碍（如侧边栏） |

---

## Phase 0–3 与关键横向能力（对照实现）

下列表格将「规划阶段」与**代表性代码锚点**对齐。

| 轨道 | 代表性代码 | 说明 |
|------|------------|------|
| **Phase 0（质量闭环基础）** | `wiki/lint.py`、`wiki/lint_scheduler.py`、`wiki/auto_healer.py` | 定时/按需 Lint、与 AutoHealer 的衔接方式以实现状态文档为准 |
| **Phase 1（快照 / 反馈 / 总线）** | `wiki/compilation_snapshot.py`、`wiki/feedback_loop.py`、`wiki/event_bus.py`、`wiki/agents_md_generator.py` | 快照 MCP/HTTP、`WikiEventBus` SSE 类能力、AGENTS.md 生成 |
| **Phase 2（社区 / 图 / 版本化内容）** | `wiki/community_context.py`、`store/graph_queries.py`（如 `shortest_path_between_names`）、`store/wiki_page_store.py`（`update_wiki_page_content`、版本与 diff） | HTTP：`PATCH …/content`、`GET …/versions`、`GET …/diff` |
| **Phase 3（推理路径 / 离线包 / 树 tier）** | `wiki/reasoning_path.py`、`wiki/offline_pack.py`、`store/wiki_tree_store.py`（`wiki_tier`） | HTTP：`GET …/offline-pack`；树上展示 tier |
| **异步业务 Wiki（2026-04-27 线）** | `wiki/task_store.py`、`api/routes/wiki_task_routes.py`、`store/wiki_page_store.py`、`dashboard/src/hooks/useWikiRegenerate.ts` | **HTTP 202** + 任务轮询；设计与架构见 [`wiki-generation-architecture.md`](../wiki-generation-architecture.md) |
| **架构重构（2026-05）** | `core/container.py`、`api/mcp_registry.py`、`main.py`（lifespan 拆分） | 设计/计划见 `docs/superpowers/specs/` 与 `docs/superpowers/plans/` |

---

## 相关文档链接

| 文档 | 用途 |
|------|------|
| [`ARCHITECTURE.md`](../ARCHITECTURE.md) | 端到端架构、索引与检索、Wiki 与 MCP 概览 |
| [`MCP-INTEGRATION.md`](../MCP-INTEGRATION.md) | 22+6 工具清单、认证与字段差异 |
| [`wiki-generation-architecture.md`](../wiki-generation-architecture.md) | Wiki 管道与 LLM Wiki v2 |
| [`REMAINING-WORK.md`](../REMAINING-WORK.md) | 剩余工作积压项 |
| [`README-DOCS.md`](../README-DOCS.md) | 文档总索引 |
| [`DEVELOPMENT.md`](../DEVELOPMENT.md)、[`DEPLOYMENT.md`](../DEPLOYMENT.md)、[`ONBOARDING.md`](../ONBOARDING.md) | 本地开发、部署与上手 |
