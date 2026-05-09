# 实施状态（代码为准）

**最后更新：** 2026-05-09

本文档是仓库内关于「**当前已实现能力**」与「**历史规划 / 已归档设计**」区分的**唯一权威快照**。详细 Wiki 生成管线与 Phase 0–6 扩展说明另见 [wiki-generation-architecture.md](wiki-generation-architecture.md)；架构演变与安全加固细节另见 [ARCHITECTURE.md](ARCHITECTURE.md)、[superpowers/specs/2026-05-02-architecture-refactor-design.md](superpowers/specs/2026-05-02-architecture-refactor-design.md)。代码审计与竞品缺口可参考 [superpowers/DEEP_ANALYSIS_20260502_101930_code_audit_and_competitor_gap.md](superpowers/DEEP_ANALYSIS_20260502_101930_code_audit_and_competitor_gap.md)。

---

## 1. 概述

### 1.1 文档用途

- **已实现**：以本仓库源码与测试为准；下文表格给出主要模块路径与 HTTP/MCP 触点。
- **规划中 / 历史**：旧版 Superpowers 规格（full-upgrade draft 的 SP1–SP6 与 v2 批准设计的 SP1–SP7）已完成并已从仓库移除（约 2026-04-30）；勿将历史 PR/ issue 中两套 **SP** 编号混为一谈。

### 1.2 历史 SP 编号说明（必读）

历史上并存过两套互不兼容的 **SP** 命名空间：

| 来源 | 范围 | 含义 |
|------|------|------|
| Full-upgrade 草案 | SP1–SP6 | 早期全面升级草稿 |
| LLM Wiki v2 批准设计 | SP1–SP7 | 另一套分段设计编号 |

两者**不得合并解读**。阅读旧讨论时请根据上下文判断对应的是哪一套 SP。

---

## 2. Wiki 子系统（权威快照）

下表覆盖 Wiki 相关已实现能力的主要代码入口与运行时行为。

| 领域 | 主要代码 | HTTP / 运行时 | 说明 |
|------|-----------|----------------|------|
| **Wiki 路由（拆分路由器）** | `api/routes/wiki_routes.py` 聚合；`wiki_task_routes.py`、`wiki_page_routes.py`、`wiki_ask_routes.py`、`wiki_feedback_routes.py`、`wiki_contradiction_routes.py`、`wiki_mcp_routes.py` | 前缀 **`/api/v1/wiki`**；可选 **`/api/v1/mcp`**（Wiki HTTP MCP 子路由） | 任务 / 页面与搜索 / 问答流式 / 反馈与 ingest / 矛盾 / MCP 工具 HTTP 封装分文件维护，`wiki_routes.py` 统一 `include_router`。 |
| **业务 Wiki 异步任务** | `wiki/task_store.py`（Redis Hash + TTL）、`wiki/task_registry.py`、`api/routes/wiki_task_routes.py`、`wiki/bootstrap.py` | **`POST /api/v1/wiki/business/generate`** → **202**，体为 `{task_id, status: "pending"}`；**`GET /api/v1/wiki/business/tasks/{task_id}`** 轮询 | 任务状态持久化；**按 `business_id` 互斥**见「安全加固」中的任务锁。 |
| **Wiki 树** | `store/wiki_store.py` 等；`api/routes/wiki_page_routes.py` | **`GET /api/v1/wiki/tree`**，`business_id`、`view`（默认 `business_domain`）、可选 **`wiki_tier`** | `view` 支持 **`business_domain`** / **`code_structure`**；另有 **`GET …/domain-tree`** 供仪表盘域审核面板（含 `review_status`）。 |
| **矛盾检测与工作流** | `wiki/contradiction_detector.py`、`api/routes/wiki_contradiction_routes.py` | **列表**：`GET /api/v1/wiki/contradictions?page_uid=…`（query）；**`PATCH …/acknowledge`**、**`…/resolve`** | LLM 判定矛盾；路由层与存储联动。 |
| **Lint** | `wiki/lint.py`（`WikiLintService`）、`wiki/lint_scheduler.py` | 调度：`WIKI__LINT_SCHEDULER_ENABLED` 等配置；HTTP 见 Wiki Lint API 测试与路由绑定 | **`WikiLintService.run_lint`**：先 **`lint()`** 汇总 issue，再按需 **`AutoHealer.heal()`**，返回统一字典；**`LintScheduler`** 周期性对多仓库调用 **`run_lint`**（与手动/API 路径一致）。 |
| **AutoHealer** | `wiki/auto_healer.py` | 由 **`WikiLintService.run_lint`** 在 **`auto_heal_enabled`** 时调用 | **仅** **`remove_broken_references`**（清理悬空 `WIKI_REFERENCES`）与 **`deprecate_orphan_pages`**（无 `SOURCE_ENTITY` 的页面 deprecate）。**不包含**「陈旧页面自动标Stale」类逻辑。 |
| **置信度评分** | `wiki/confidence_scorer.py`（`ConfidenceInputs`、`WeightBundle`、`ConfidenceScorer`）、`wiki/confidence_inputs.py`（`gather_confidence_inputs`、批量重算） | 写入图节点属性；Lint 可在 **`confidence_scoring_enabled`** 时触发 **`recalculate_confidence_scores_for_repo`** | **W1–W5**：对应源码中的 **`w1`–`w5`**——来源实体覆盖、时效、反馈占比、入链 Wikilink、矛盾惩罚（默认权重见 **`DEFAULT_WEIGHTS`**）；可通过 **`AppWikiFlags.confidence_weight_w1`…`w5`** 覆盖。 |
| **主张 / 替代（supersession）** | `wiki/claim_extractor.py`、`wiki/claim_tracker.py`、`wiki/persistence.py`（`skip_claim_tracking`、`supersession_tracking`） | 生成持久化阶段 | 版本间 **`ClaimTracker.find_supersedions`**；图存储 **`find_or_create_wiki_claim`**、**`set_wiki_claim_superseded`** 等；受 **`supersession_tracking_enabled`**、**`claim_tracking_*`** 等配置约束。 |
| **记忆分层 + 遗忘** | `wiki/memory_loop.py`（`MemoryLoop`，tier 与 **`memory_tiers_enabled`**）、`wiki/memory_tiers.py`、`wiki/migrate_memory_tiers.py`、`wiki/forgetting.py`、`wiki/lint.py`（`_check_forgetting`、`_check_memory_promotions`） | Ask / 检索注入上下文 | **WikiQA** 节点分层（Episodic→巩固）；**遗忘曲线**（Ebbinghaus 风格 **`compute_retention`**）与 Lint 侧 **`memory_status`** 更新由配置 **`forgetting_enabled`**、**`forgetting_initial_stability`** 等控制。 |
| **Schema 校验** | `wiki/schema_validator.py`、`wiki/schema.yaml`、`wiki/lint.py` **`_check_schema`** | Lint **`schema_validation_enabled`** 时启用 | YAML 结构与图上 Wiki 页面对照产生 **`LintIssue`**（category **`schema`**）。 |
| **深度研究** | `wiki/deep_research.py`（**`DeepResearchService`**） | `wiki_ask_routes` / bootstrap 注入 | **拆解子问题**（LLM 或启发式）→ 每子问题走 **`IterativeRAGEngine`** → **综合答案**；支持 **`RetrievalScope`**（repository / business）。 |
| **反馈闭环** | `wiki/feedback_loop.py`（**`FeedbackDrivenRegeneration`**） | `wiki_feedback_routes` 提交反馈后钩子 | **差评阈值**、**冷却时间**、**critical 立即排队**；调用注入的 **`enqueue_regenerate`**。 |
| **事件总线** | `wiki/event_bus.py`（**`WikiEventBus`**） | **`publish`** / **`stream`**（SSE 心跳）；任务进度等 | 异步队列订阅；可按 **`business_id`** 过滤流式事件。 |
| **编译快照** | `wiki/compilation_snapshot.py`（**`WikiCompilationSnapshot`**） | MCP **`wiki_get_snapshot`**（主 MCP + Wiki HTTP MCP） | 从图查询重建「编译后的」Markdown 快照文本（非 diff merge）。 |
| **社区上下文** | `wiki/community_context.py`（**`CachedCommunityService`**）、`wiki/service.py` | 注入业务 Wiki / 组合上下文 | 缓存社区检测结果，格式化进 Markdown。 |
| **推理路径** | `wiki/reasoning_path.py`（**`ReasoningPath`**、`ReasoningStage`、`merge_reasoning_paths`）、`wiki/ask.py` | Ask / 深度搜索响应字段 | 结构化检索阶段溯源（vector / fts / graph / wiki_search 等）。 |
| **离线包** | `wiki/offline_pack.py`（**`WikiOfflinePack`**） | **`GET /api/v1/wiki/{repository}/offline-pack`**，可选 **`business_id`** query | JSON **`schema_version`**、页面列表、树、可选 **`wiki_snapshot.md`** 内容；大有 **`_MAX_OFFLINE_PAGES`** 截断。 |
| **Wiki 搜索（混合 + 全局）** | `wiki/search.py`（**`WikiSearchService`**，图 + 向量 + FTS，**RRF 融合**） | **`POST /api/v1/wiki/search`**；**`POST /api/v1/wiki/search/global`**（多仓库并行） | 权重常量 **`_WEIGHT_*`**；可选 **`expand_query_with_graph`**（实体邻居扩展）。 |
| **Ask / SSE 流式** | `wiki/ask.py`（**`WikiAskService`**）、`api/routes/wiki_ask_routes.py` | **`POST|GET /api/v1/wiki/ask/stream`**，`text/event-stream` | 事件类型 **`token` / `sources` / `done`**（JSON 单行 `data:`）；内部可挂 **`IterativeRAGEngine`**、**`MemoryLoop`**。 |
| **导出（五种格式）** | `wiki/business_wiki_exporter.py`、`wiki/obsidian_exporter.py`、`wiki/mkdocs_exporter.py`、`wiki/git_publisher.py`（git）；`api/routes/wiki_page_routes.py` **`/export`** | **`POST /api/v1/wiki/export`**，`body.format`：**`markdown`**、**`zip`**、**`git`**、**`obsidian`**、**`mkdocs`** | `git` 需 **`git_config`**；与 **Phase 5** 文档一致。生成管线的 **`WikiExportService`**（`wiki/export_service.py`）侧还有 **`json`** / 单页 **`markdown`** 完成包（与「五格式」HTTP 导出互补）。 |
| **Ingest + Changelog** | `api/routes/wiki_feedback_routes.py`（**`/ingest`**、**`/changelog`**）、`api/routes/webhook_routes.py`（**`/ingest/push`**） | **`POST /api/v1/wiki/ingest`**；**`GET /api/v1/wiki/changelog?repository=…`**；Webhook 增量 | 依赖 **`change_detector`** / **`wiki_changelog_store`** 等应用状态；未配置时返回不可用或空列表。 |
| **AGENTS.md 生成** | `wiki/agents_md_generator.py`（**`AgentsMdGenerator`**） | MCP / 内部调用 | 从图聚合页面元数据输出 **AGENTS.md** 风格指引（含 **`wiki_get_snapshot`** 提示）。 |
| **IterativeRAGEngine（unified_knowledge_query）** | `wiki/rag/engine.py`（**`IterativeRAGEngine`**）、`wiki/mcp_tools.py` **`handle_unified_knowledge_query`**、`services/kb_service.py`、`query/deep_search.py` | MCP **`unified_knowledge_query`**（主 `mcp_server.py` 清单） | LangGraph **StateGraph** 式迭代检索 + 作答；未装配 **`rag_engine`** 时工具返回 **`not_configured`**。 |

**补充（与 Wiki 强相关但上表未逐行展开）**

- **P6 写出到仓库 docs**：`wiki/wiki_docs_exporter.py`（**`WikiDocsExporter`**，`preview_export` / 选择性写入，带 **`AUTO_GENERATED`** 标记与人类文件跳过规则）。
- **域树 / LangGraph 产出持久化**：`wiki/pipeline_orchestrator.py` 桥接 **`build_wiki_pipeline`** 与 **`WikiService.generate_business_wiki`**；**`resolved_links`** → **`WIKI_REFERENCES`**（见 `WikiService` 相关方法）。

---

## 3. Phase 0–3 实施（2026-04-27）

以下为「LLM Wiki v2 / 仪表盘增强」分段交付的归纳（与 §2 快照互补）。

### Phase 0 — 自动化与健康检查底座

| 模块 / 能力 | 路径或触点 | 状态 |
|-------------|------------|------|
| Lint 统一路径 **`run_lint`** | `wiki/lint.py` | **已实现**：收集 issue → 可选 AutoHeal → 合并 changelog 记录 |
| **AutoHealer** 接入 | `wiki/auto_healer.py` | **已实现**（能力边界见 §2） |
| **LintScheduler** | `wiki/lint_scheduler.py`，`wiki/bootstrap.py`  Wiring | **已实现**：定时 **`run_lint(repo, scope="all")`** |

### Phase 1 — 可观测性、反馈基础设施、Agent 导出

| 模块 / 能力 | 路径或触点 | 状态 |
|-------------|------------|------|
| **WikiCompilationSnapshot** | `wiki/compilation_snapshot.py` | **已实现** |
| **FeedbackDrivenRegeneration** | `wiki/feedback_loop.py` | **已实现** |
| **WikiEventBus** | `wiki/event_bus.py` | **已实现** |
| **MCP `wiki_get_snapshot`** | `wiki/mcp_tools.py`、`api/mcp_server.py`、`api/mcp_wiki_server.py` | **已实现**（主 MCP + Wiki HTTP MCP） |
| **AGENTS.md** | `wiki/agents_md_generator.py` | **已实现** |

### Phase 2 — 社区上下文、图路径、页面编辑

| 模块 / 能力 | 路径或触点 | 状态 |
|-------------|------------|------|
| **CachedCommunityService** | `wiki/community_context.py` | **已实现** |
| **最短路径查询** | `store/graph_queries.py` **`shortest_path_between_names`**；`store/wiki_page_store.py` **`ask_query_shortest_path_between`** | **已实现** |
| **页面内容编辑 / 版本 / diff** | `store/wiki_page_store.py`；`api/routes/wiki_page_routes.py`（**`PATCH …/content`**、**`GET …/versions`**、**`GET …/diff`**） | **已实现** |

### Phase 3 — 推理溯源、离线包、树过滤

| 模块 / 能力 | 路径或触点 | 状态 |
|-------------|------------|------|
| **ReasoningPath** | `wiki/reasoning_path.py`、`wiki/ask.py` | **已实现** |
| **WikiOfflinePack** | `wiki/offline_pack.py` | **已实现**（后端打包 JSON） |
| **`wiki_tier` 树过滤** | **`GET /api/v1/wiki/tree`** query **`wiki_tier`** → `WikiStore.get_wiki_tree` | **已实现** |

前端与其它栈（仪表盘 Wiki、混合搜索 UI）是否在特定环境启用，以部署配置为准；**后端 API 与核心逻辑已在仓库内落地**。

---

## 4. 架构重构（2026-05-02）

| 主题 | 实现位置 | 说明 |
|------|-----------|------|
| **AppContainer（DI）** | `core/container.py`、`wiki/bootstrap.py` 填充、`api/kb_state.py` 过渡 shim | 集中存放 wiki / 索引 / 调度器等长生命周期依赖 |
| **Lifespan 分解** | `main.py`（如 **`_init_security`**、**`_init_core_services`**、**`_init_wiki_and_lint`**、**`_shutdown_all`**） | 启动 / 关闭阶段清晰拆分 |
| **MCP 自动注册** | `api/mcp_registry.py`（**`@mcp_tool`** + **`collect_tools`**） | 减少手写注册遗漏 |
| **FQN 去重** | `store/fqn_utils.py` | 图 / Wiki 路径slug collision 处理 |
| **WikiService 类型收窄** | `wiki/protocols.py`（**`WikiGraphStorePort`** 等 Protocol） | 图持久化端口等与实现解耦，便于测试与替换 |
| **前端 `wikiPath`** | `dashboard/src/utils/wikiPath.ts` | Wiki 链接与路由参数统一 |
| **页面烟测** | `dashboard/src/pages/__tests__/` | Vitest 级页面冒烟 |
| **移动端侧栏 a11y** | `dashboard/src/components/Layout.tsx`（**`role="dialog"`**、**`aria-modal`**、**ESC** 关闭） | 小屏导航可访问性 |

设计论述见 **`docs/superpowers/specs/2026-05-02-architecture-refactor-design.md`** 与计划 **`docs/superpowers/plans/2026-05-02-architecture-refactor.md`**。

---

## 4.1 Language Plugin Phase 2 — 客户端平台语言扩展（2026-05-02）

| 组件 | 实现位置 | 说明 |
|------|-----------|------|
| **KotlinPlugin** | `indexer/languages/kotlin_lang.py` | JVM interop group，共享 `_jvm_common`；支持 `.kt`/`.kts` |
| **SwiftPlugin** | `indexer/languages/swift_lang.py` | Apple interop group；支持 `.swift` |
| **ObjectiveCPlugin** | `indexer/languages/objc_lang.py` | Apple interop group；支持 `.m`/`.h`；含 ObjC message_expression 解析 |
| **DartPlugin** | `indexer/languages/dart_lang.py` | Flutter 跨平台；支持 `.dart`；含 `package:` 导入解析 |
| **Protocol 扩展** | `indexer/languages/__init__.py` | 新增 `accept_class_query_capture` / `extract_function_name_from_node` / `extract_call_name_from_node` 钩子 |
| **配置默认值** | `core/config.py` | `supported_languages` 与 `file_extensions` 扩展至 9 语言 |
| **CodeGraphBuilder** | `indexer/code_graph_builder.py` | `compute_fqn` 增加通用后缀查找路径 |
| **回归测试** | 2655 测试全通过（+19 新插件测试） | 覆盖率 82% |

---

## 5. 安全加固（2026-05-02）

| 项 | 代码位置 | 状态 |
|----|-----------|------|
| **SPA 静态路径穿越** | `main.py`（静态文件解析与回退） | **已修复** |
| **Webhook 鉴权** | `api/routes/webhook_routes.py` | **已加固** |
| **Git SSL 默认校验** | `config.py` **`GitConfig.ssl_verify=True`** | **默认安全** |
| **Cypher 变更检测** | `query/nl_cypher.py`（变异关键词扩展） | **已加固** |
| **Wiki 任务锁** | `wiki/task_store.py`：**`try_lock`**（**`SET NX`** + **`UNLOCK_SCRIPT`** Lua 比对 token）、`wiki_task_routes` **`_check_business_lock`** | **每 business 互斥** |

---

## 6. LangGraph 管道增强

| 主题 | 实现 | 说明 |
|------|------|------|
| **EntityRoleClassifier** | `wiki/entity_role_classifier.py`，`wiki/pipeline_nodes.py` **`classify_entities_node`** | 实体角色分类，供给后续域与写作 |
| **LangGraph StateGraph（图驱动管线）** | `wiki/pipeline_graph.py` **`build_wiki_pipeline`** | `classify_entity_roles` → `detect_reorg` →（条件）`graph_decompose` → `assign_canonical_keys` → `generate_titles` → `set_review_status` → `compose_leaf_modules` → `compose_bottomup` → **`quality_gate`** ⇄ **`heal_pages`** → `create_links` → `finalize`。质量门支持 L1 结构 + `verify_citations` 引用校验 / L2 静态 benchmark / L3 LLM judge（4×1-5 via `WikiPageEvaluator`）。Checkpoint 可选 **`MemorySaver`** / 持久化 saver。 |
| **TopicPageComposer** | `wiki/topic_page_composer.py`，pipeline 合成节点调用 | Topic / Guided 页面正文组合 |
| **Business 管理 API** | `store/business_manager.py`；`api/routes/business_sync_routes.py`（viewer/admin）；另 **`business_routes.py`**（图谱侧 CRUD / 绑定仓库） | 多租户 **`business_id`** 与独立图 **`kb_{business_id}`** |
| **Dashboard 组件** | `dashboard/src/components/wiki/WikiToolPanel.tsx`、`WikiLandingPage`、域审核面板、`Businesses.tsx`、`BusinessContext.tsx` | **`business_domain` / `code_structure`** 视图、域树图、覆盖率与健康等 Tab |

编排入口：**`wiki/pipeline_orchestrator.py`**；状态：**`wiki/pipeline_state.py`**；日志桥：**`wiki/structlog_callback.py`**。

---

## 7. 缺失的独立 Spec 文件

下列文件名曾出现在早期架构叙述中，**仓库 `docs/` 下不以独立 Markdown 文件提供**：

- `2026-04-24-wiki-enhancement-design.md`
- `2026-04-26-wiki-tree-architecture-design.md`
- `2026-04-26-wiki-frontend-redesign.md`

请以 **本文档 §2–3**、**[wiki-generation-architecture.md](wiki-generation-architecture.md)**、**[ARCHITECTURE.md](ARCHITECTURE.md)** 作为设计与实现对照的首选来源。

---

## 8. 验证

### 8.1 Python 版本

- 根目录 **`pyproject.toml`**：**`requires-python >= 3.12`**（**`tool.ruff.target-version = "py312"`**）。

### 8.2 测试命令

| 层级 | 命令 | 说明 |
|------|------|------|
| 后端单元 / 集成 | `uv run pytest` | 默认 **`tests/`**，带 coverage（见 **`pyproject.toml`** **`pytest`** 配置） |
| 前端单元 | `pnpm test`（在 **`dashboard/`** 目录） | Vitest：`vitest run` |
| 前端 E2E（可选） | `pnpm test:e2e` | Playwright |

按需收窄范围示例：**`uv run pytest tests/wiki/test_lint_scheduler.py`**、**`uv run pytest tests/api/test_webhook_routes.py`**。
