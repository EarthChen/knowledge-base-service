# Remaining Work (Unified Backlog)

**Created:** 2026-05-09  
**Last Updated:** 2026-05-24  
**Status:** Active — items checked off when merged

---

## 进行中

_(当前无进行中任务)_

---

## 积压项

### P2 — F4 Structured Output 剩余迁移

V10 已将 3 个 LLM provider 升级为 `json_schema + strict`，已迁移 P0/P1 调用方，以下 8 个灵活格式调用方仍降级为 `json_object`（功能正常，有 deprecation warning）。待各调用方输出格式稳定后逐步迁移：

| 文件 | 行 | 当前状态 | 备注 |
|------|-----|----------|------|
| `wiki/nodes/compose.py` | ~238 | `{}` fallback | wiki content 格式过于灵活 |
| `wiki/nodes/compose.py` | ~629 | `{}` fallback | 同上 |
| `wiki/targeted_healer.py` | ~98 | `{}` fallback | diagnosis 格式多变 |
| `wiki/cross_repo_domain_planner.py` | ~396, ~503, ~582, ~701, ~758 | `{}` fallback (5处) | 多种域映射格式，已有 robust parsing |
| `wiki/business_domain_planner.py` | ~228 | `{}` fallback | 灵活映射格式 |
| `wiki/rag/engine.py` | ~87 | `{}` fallback | reflection 格式任意 |
| `wiki/context.py` | ~46 | `{}` fallback | 上下文分析格式任意 |
| `wiki/nodes/aggregate.py` | ~202 | `{}` fallback | 内容聚合格式任意 |
| `wiki/reasoning.py` | ~188 | `{}` fallback | 推理计划格式任意 |


### P2 — Agent 框架渐进迁移

- [x] **Migrate 14 WikiPageAgent tools to `@function_tool`** — 全部 14 个工具已迁移完成 (2026-05-20)。手写 JSON Schema (`AGENT_TOOLS`) 已删除，工具通过 `@function_tool` 装饰器 + `collect_tools()` 自动注册。

### P2 — 代码拆分重构（审计发现）

- [ ] **WikiService god object** (1700+ lines) — `wiki/service.py` 混合了 generation、incremental updates、business wiki、enrichment、persistence、tree linking、streaming、graph writes。拆分为 `WikiGenerationOrchestrator`、`WikiIncrementalService`、`BusinessWikiPipeline` 等专职服务。
- [ ] **WikiPageAgent monolith** (1885 lines) — `wiki/page_agent.py` 集成了 agent loop、tool execution、sanitization、output shaping。提取 tool handlers、prompt assembly、output post-processing 为独立模块。
- [ ] **MCPHandler monolith** (1350 lines) — `api/mcp_server.py` 集成了 dispatch、validation、graph queries、file I/O、wiki tooling。拆分为独立 handler 按名称注册。
- [ ] **WikiShell god component** (724 lines) — `dashboard/src/components/wiki/WikiShell.tsx` 混合了 routing、dialogs、SSE、tree nav、mutations、layout。拆分为 layout shell、nav、page loader、dialog host、event handler hooks。
- [ ] **GraphExplorer monolith** (1100 lines) — `dashboard/src/pages/GraphExplorer.tsx` 混合了 graph layout、mutations、filters、blast radius、communities。提取 graph canvas、side panels、mutation hooks 为子模块。
- [ ] **FalkorDBStore SRP violation** — `store/falkordb_store.py` 通过 mixin 组合了 search、wiki、read、CRUD、schema、batch 操作。暴露窄端口 (`GraphReadStore`, `GraphWriteStore`, `VectorSearchStore`) 给上层。
- [ ] **kb_state.py 全局状态迁移** — 模块级 `reindex_sem`/`index_sem` 与 `AppContainer` 实例不是同一对象。统一通过 `AppContainer` + FastAPI `Depends` 注入。

### P3 — 前端代码质量

- [ ] **F-04: API 响应无运行时校验** — `api/client.ts` 的 `api<T>()` 将 JSON 直接 cast 为 `T`，运行时数据形态完全信任服务端。
- [x] **WikiSourceLocRow 死代码** — 组件已删除 (2026-05-20)。


### P2 — Product Feature Gaps (from DEEP_ANALYSIS)

- [ ] **B-19: Generic document ingest** — Support PDF, Office (docx/xlsx), HTML as indexable knowledge sources beyond code.
- [ ] **B-20: Multi-modal analysis** — Support images, design files, and non-text content in the knowledge graph.
- [ ] **B-21: Automated quality benchmark** — End-to-end benchmark infrastructure for regression tracking.
- [ ] **B-22: Docker Compose one-click deploy** — Lower deployment barrier; compose file + env template + health probes.

### P2 — 死代码清理

- [ ] **N3: CCB / unified_prompt_templates / 旧 Composer 分支** — ⚠️ 经代码审计确认：`content_context_builder.py`、`unified_prompt_templates.py` 仍被 LangGraph 管线活跃引用（`wiki/nodes/compose.py`、`wiki/topic_page_composer.py`、`wiki/domain_overview_composer.py`），**非死代码**。需先完成 Agent 管线对 compose 阶段的完整替代后才能删除。降级为长期目标。

### P3 — 数据质量

- [ ] **source_locations 行号 0-0** — 图节点的 `start_line`/`end_line` 属性在部分节点（如 Java Module 级别）上为 0，导致 `source_locations` 中的行号信息无效。前端已移除源码位置渲染，但 exporter 导出 Markdown 时仍会输出 `file:0–0` 格式的无效链接。根因在代码索引器层面。

---

## 已完成归档

以下工作已全部完成，保留作为审计记录：

- [x] Agent-Driven Business Wiki Phase 0-4 ✅
- [x] Incremental Wiki Update ✅
- [x] Wiki pipeline hardening (2026-05-11) ✅
- [x] Issue #008 Agent 管线质量修复 ✅ (2026-05-12)
- [x] Wiki LLM P0 fix (`_enrich_leaf_context`) — 已通过新 Agent 管线绕过
- [x] Explore/Write 分离 ✅ (2026-05-12) — 固化至 `page_agent.py` + `domain_doc_agent.py`
- [x] Domain Agent 弹性超时 + Wiki⟷Code 深度关联 ✅ (2026-05-12)
- [x] Code Linking 合并 Bug (`_attach_domain_sources`) ✅ (2026-05-12)
- [x] 域分类 v2 slug 全链路传播 ✅ (2026-05-12)
- [x] 质量门改进 ✅ (2026-05-12)
- [x] Agent Compose 默认管线 ✅ (2026-05-12)
- [x] source_locations 覆盖 topic 页面 ✅ (2026-05-12)
- [x] 统一提案 A-D 路径/质量门/内容/Robustness ✅
- [x] 统一提案 F 核心 Explore/Write 分离 ✅
- [x] 统一提案 G 域分类 v2 核心（slug全链路+锚点+信号+持久化+质量） ✅
- [x] 统一提案 T2 存储层 10/10 方法 ✅ (list_domain_anchors, upsert_domain_anchor, delete_domain_anchor, pin_module_to_domain, unpin_module, list_pinned_modules, save_domain_classification, get_checkpoint_info, delete_checkpoint, list_domain_modules, rename_domain)
- [x] 统一提案 T10 Dashboard API 10/11 端点 ✅ (域 CRUD + pin/unpin + checkpoint + list_domain_modules + rename_domain)
- [x] 统一提案 T11 Dashboard UI 核心 ✅ (DomainManagement.tsx + CheckpointPanel.tsx + hooks + 域详情面板 + 重命名对话框)
- [x] 统一提案 T12 触发脚本 8/8 命令 ✅ (list-domains, move-module, unpin-module, reset-anchors, checkpoint-info, checkpoint-delete, resume, regenerate-domain)
- [x] S1: repo_path 传入激活文件读取工具 ✅ (2026-05-13)
- [x] S2: 预注入图索引代码片段到 WorkingMemory ✅ (2026-05-13)
- [x] S3: 工具动态解锁 (T1/T2/T3 三级) ✅ (2026-05-13)
- [x] WorkingMemory 质量改进 ✅ (2026-05-13) — error-aware incorporate + 代码片段去重 + 相关性淘汰
- [x] 前端移除源码位置渲染 ✅ (2026-05-13) — WikiSourceLocRow 从 WikiContent + WikiTopicContent 中移除
- [x] 统一 Agent 抽象 Phase 1 ✅ (2026-05-13) — GenericAgent + ToolRegistry + ToolDef + Memory + WikiPageAgent 继承 + DocOrchestrator
- [x] 统一 Agent 抽象 Phase 2-5 ✅ (2026-05-13) — DomainDocAgent 重构 + ResearchOrchestrator + AskOrchestrator + TopicDocAgent + FlowDocAgent (3396 tests)
- [x] 代码块真实性保障 ✅ (2026-05-13) — 混合验证：CODE_REF 注入 + 后验证替换，DocOrchestrator 自动集成 (3429 tests)
- [x] Agent Framework Enhancement Layer 0-3 ✅ (2026-05-19~20) — RunContext DI、Guardrails、output_type、@function_tool、Span Tracing (JsonlTraceProcessor)、Handoff 形式化、delegate_submodule 迁移、PromptLengthGuardrail 集成 (3730 tests)
- [x] Migrate 14 WikiPageAgent tools to @function_tool ✅ (2026-05-20) — 消除 AGENT_TOOLS 手写 JSON Schema，改用 @function_tool 装饰器 + collect_tools 自动注册 (3764 tests)
- [x] Infrastructure Resilience & Optimization ✅ (2026-05-20) — Embedding 并发度分离、Redis 重试装饰器、LLM retry 统一、跨文件内存优化 (SymbolEntry)、TanStack staleTime 分层
- [x] Code Quality Quick Fixes ✅ (2026-05-20) — WikiShell Rules of Hooks 修复、business_manager @with_redis_retry 补全、WikiSourceLocRow 死代码删除、event bus 并发安全 (copy-on-iterate)、search_entities 并行查询 (asyncio.gather)、search_all 单次 embedding (3766 tests)
- [x] Agent Runner Extraction ✅ (2026-05-20) — run_agent_loop() 独立函数 + LoopHooks + 重复调用检测 + enrich() 迁移 + agent_tool() 子代理组合 (3775 tests, 83.65% coverage)
- [x] Batch 1: Wiki Pipeline Quick Wins ✅ (2026-05-24) — 并行 LLM 命名、动态关键词发现、语言特定概念注入、交替重复检测、L3 质量门
- [x] Batch 2: Architecture Layer + dagre + Incremental ✅ (2026-05-24) — 架构层分类 (`classify_architecture_layers`)、WikiKnowledgeGraph dagre 布局、三级增量更新
- [x] Batch 3: Tour + Heal Strategy + Flow Model ✅ (2026-05-24) — Guided Tour (`generate_tour`)、Heal Fallback Strategy、业务流三级模型 (`compose_flow_agents` + `merge_flow_pages`)
- [x] Pipeline Graph Refactor ✅ (2026-05-24) — `quality_gate_node`/`finalize_node` 提取至 `wiki/nodes/`、L3 并行评估 (`asyncio.gather` + semaphore)、`heal_loop_max_total_attempts` 配置化至 `AppWikiFlags`、`pages_to_heal` L1 排序 fallback、`import time` 模块级化 (2900 tests)
- [x] Wiki-Driven Domain Reassembly ✅ (2026-05-22) — `reassemble_domains_node` 基于 embedding 相似度 + LLM 审核的域重组、孤儿匹配、回滚保护
- [x] Heal Redesign + Unified LLM Rate Control ✅ (2026-05-24) — heal 并发 (PipelineConcurrency.semaphore("heal"))、Tier 分层 (CORE 3轮/STANDARD 1轮/SKELETON skip)、全部 6 节点统一频控迁移 (compose, wiki_shared, enrichment_coordinator, bootstrap, domain_compose, graph_nodes, repo_composer)
- [x] Batch A: Domain Clustering Accuracy + Infra ✅ (2026-05-24) — 嵌入文本 key_methods 字段修复 + deps/callers 注入 (P0)、全局 LLM 审查代表性排序 + 方法签名 (P1)、discount 死代码修复 (P1)、PipelineConcurrency 信号量缓存 (P2)、Reassembly 阈值微调 0.78/0.65 (P2)
- [x] Batch C+D: classify LLM enriched_signals + TF-IDF 复用 + 前缀正则扩展 + Token 预算协调 + Cypher 复合键 + Quality/Heal 结构检查去重 ✅ (2026-05-24)
- [x] Batch E: Correctness Fixes ✅ (2026-05-24) — heal_cycles 外循环计数分离、agent_error 页面排除质量评估、L2 bench 阈值影响 heal 决策 (`heal_l2_threshold`)、SUPPORTING 角色精细路由 (`classify_include_supporting`)
- [x] Batch F: Graph Path + Performance ✅ (2026-05-24) — 增量域分解语义 (`affected_modules` + `existing_domain_mapping`)、锚定/钉住模块 (`pinned_modules`)、模块复合键索引 (`repo|name`)、父页面并行化 (`asyncio.gather`)、DomainDocAgent early exit (`domain_agent_early_exit_quality`) (2945 tests)
- [x] Batch G: Frontend A11y + Component Split ✅ (2026-05-24) — Toast accessibility (`role/aria-live/aria-atomic`)、WikiShell 拆分 727→384 行 (`useWikiShellState` + `WikiDomainDialogs` + `WikiToolbar`)、GraphExplorer 拆分 1087→331 行（6 个子模块）(328 frontend tests)
- [x] Batch H: Classification Signal + Quality Alignment ✅ (2026-05-24) — module_summaries 复合键 + summary_text 注入分类提示、quality_gate/heal tier 默认值对齐（共享 `resolve_tier`）、agent_error 页面参与 heal（限 1 次）、DomainDocAgent 代码块验证 (2956 tests)
- [x] Batch I: Incremental Fixes + Executive Summary ✅ (2026-05-24) — 增量 tree 重建修正、增量裸名修复 `(repo,name)` 复合键、增量仅摘要受影响模块、agent 页面 executive_summary 元数据 (2964 tests)
- [x] Batch J: Cross-repo Compound Key Completion ✅ (2026-05-24) — WikiPipelineState 6 字段补全、detect_reorg 指标修正 (affected vs tree)、前缀合并复合键、GraphSemanticCorrector 复合键、全局审查摘要复合键、affected_modules 仓库消歧 `repo|name` (2987 tests)
- [x] Batch K: Topic-split Quality Iteration ✅ (2026-05-24) — topic_split_quality_check 开关 + per-page evaluate_quality + focused re-explore (2987 tests)
- [x] Batch L: Frontend A11y P1 ✅ (2026-05-24) — 5 dialog FocusTrap+ARIA、mobile sidebar FocusTrap、WikiTreeNav 键盘导航 (roving tabIndex)、TopicTreeNav focus-visible actions、ConfirmDialog 替代 window.confirm (349 frontend + 2987 backend tests)
- [x] WikiService God Object Refactoring ✅ (2026-05-24) — 1872→919 行 (-51%)：提取 `BusinessPipelineRunner`(741) + `IncrementalWikiGenerator`(323) + `StreamGenerator`(288)；公共 API 不变，2991 tests pass
- [x] Batch M: Backend Correctness P1 ✅ (2026-05-24) — 增量边匹配 repo-aware (`_assign_changed_modules_incremental`)、死节点 `compose_leaf_pages_node`/`plan_topic_structure_node` 标记 DEPRECATED + DeprecationWarning (2997 tests)
- [x] Batch N: Backend Performance P1 ✅ (2026-05-24) — 嵌入 hash-cache (`embedding_cache` in pipeline state, SHA-256 key)、DomainDocAgent tier-based max_iterations (core=20/standard=8/skeleton=3) (3007 tests)
- [x] Batch O: Frontend P1 ✅ (2026-05-24) — WikiEditor/KnowledgeGraph `React.lazy()`、skip-to-content link、GraphExplorer `aria-label`、clearWikiMutation `onError`、wiki cache invalidation 扩展、FocusTrap unit tests (361 tests)
- [x] LLM Classification Path Removal ✅ (2026-05-24) — 移除 `classify_domains_node` + `decompose_hierarchy_node` (-250 行)；管线纯 Graph 驱动 `compose_leaf_modules → graph_domain_decompose → persist_classification`；前端 phase key 同步更新 (2981 tests)
- [x] Global LLM Rate Limiter ✅ (2026-05-24) — `GlobalLLMRateLimiter` 滑动窗口 RPM/TPM，6 节点接入 `acquire_llm_quota()`，`llm_global_rpm_limit`/`tpm_limit` 配置项，默认禁用 (2990 tests)
- [x] Frontend Coverage 59.1% → 70.03% ✅ (2026-05-24) — 新增 9 页面 + 5 hook + 5 组件测试文件 (480 frontend tests)
- [x] Batch P: Backend Quick P2 Fixes ✅ (2026-05-24) — compose gap-fill 跳过复合键、heal_cycles 仅未治愈页递增、module_compose_concurrency stage 修正、incremental_enabled 配置生效、timeout 对齐、domain_compose 默认类型修正、citation 验证复合键、sanitize known_entities 修正 (2997 tests)
- [x] Batch Q: Backend Classification P2 ✅ (2026-05-24) — corrector 语言感知 prompt、module_call_edges 保留仓库标识、_is_data_model() DRY 提取至 domain_filters.py、冗余 LLM merge 跳过 (3005 tests)
- [x] Batch S: Frontend A11y + Quality P2 ✅ (2026-05-24) — Businesses.tsx ConfirmDialog 迁移、Dialog useId()、label/input 关联、AskPanel ARIA、DeleteDialog fieldset/legend、Documents a11y、Layout 单 h1、QueryClient gcTime + mutation onError (490 frontend tests)
- [x] Batch T: domain_tree 复合键根因修复 P1 ✅ (2026-05-25) — _sub_to_tree_node/build_domain_tree 存 repo|name、domain_tree_to_mapping 解析复合键、module_index 按 repo|name 独立摘要 + Cypher repo 过滤 (3010 tests)
- [x] Batch U: 增量管线短路 P1 ✅ (2026-05-25) — existing_summaries 从 checkpoint/graph 预加载、no_content_changes 跳过全量 LangGraph + 返回缓存结果、force_full_run opt-out (3015 tests)
- [x] Batch V: 前端 window.confirm 迁移 P1 ✅ (2026-05-25) — Repositories.tsx + SyncSettingsPanel.tsx → ConfirmDialog (492 frontend tests)
- [x] Batch W: 后端增量/复合键 P2 ✅ (2026-05-25) — _prune_deleted_modules 复合键比较、architecture_layers repo|name 键、fetch_module_call_edges 延迟到 skip check 后 (3018 tests)
- [x] Batch X: 前端 A11y + 质量 P2 ✅ (2026-05-25) — WikiTopicTreeNav 键盘导航、FileExplorer tree ARIA、SearchPage tab 语义 + 空结果、AskPanel 流式性能、Repositories i18n (508 frontend tests)
- [x] Batch Y: 后端管线质量 P2 ✅ (2026-05-25) — Round-2 gap-fill 同步复合键、reorg_type=="none" 跳过分类、父页面增量过滤、DomainDocAgent pre_fill repo 过滤 (验证已有实现)
- [x] Batch Z: 前端 A11y 键盘 + 质量 P2 ✅ (2026-05-25) — DomainContextMenu FocusTrap+键盘、Businesses form label、Layout 菜单 i18n、SettingsPage tab 键盘、AskPanel history aria-expanded、DeepSearchSection trace aria-expanded (520 frontend tests)
- [x] Hotfix: heal 无限循环修复 ✅ (2026-05-25) — compact_formatter ModuleNotFoundError 修复 + heal_cycles 对所有 heal 页面递增防止外循环安全阀失效 (4301 tests)
- [x] Batch AA: 管线质量 P2-1 ✅ (2026-05-25) — flow_compose 增量过滤、heal_l2_threshold 默认 0.5、graph_nodes 增量门控、persist_classification repo+name 验证 (4313 tests)
- [x] Batch AB: 管线质量 P2-2 ✅ (2026-05-25) — 混合搜索分支限制 (limit+offset)*3、语义搜索 repo 后过滤、模块覆盖率词边界 regex、explore 上限 max_rounds=8/max_tool_calls=30 (4313 tests)
- [x] Batch AC: 管线质量 P2-3 ✅ (2026-05-25) — 递归 split asyncio.gather、L3 失败触发 heal、early exit 最小 500 chars、agent 路径 Mermaid 注入、budget resolver 覆盖扩展、DocOrchestrator 迁移路径 use_orchestrator_template (4322 tests)
- [x] Batch AD: §二 域分类清零 ✅ (2026-05-25) — _classify_remaining enriched signals、并行社区命名 used_names 协调、embedding_merge_threshold 可配、pinned_modules 复合键 (4342 tests)
- [x] Batch AE: §三 管线 P3 清零 ✅ (2026-05-25) — wikilink 域路径前缀、detect_reorg medium 分层、tour 增量门控、死字段移除、Mermaid 去重、死节点导出移除、jieba 模块级导入、generate_titles_node budget 接入 (4342 tests)
- [x] Batch AF: §四 前端 P2 清零 ✅ (2026-05-25) — TopicTreeNav rename a11y、Indexing 拆分 (816→350行)、shared TreeView、apiStream/apiDownload 提取、列表 memoization、全局 mutation toast、OfflinePackDownloadButton 友好错误 (533 frontend tests)
- [x] Batch AG: §五 架构 P2/P3 清零 ✅ (2026-05-25) — _reconcile_tree_with_mapping 复合键、死管线节点导出移除、Pipeline state 类型修正、heal 计数器语义文档 (4348 tests)
- [x] Batch AH: 架构层分类性能优化 ✅ (2026-05-25) — classify_architecture_layers 移至 compose_leaf_modules 之后、批量 Cypher 查询 5600→3 次、_compute_topology_vote 静态方法提取、compound key 去重映射修复 (4361 tests)
- [x] Batch AI: P2 非阻塞改进 ✅ (2026-05-25) — 前端: 每路由 ErrorBoundary 覆盖 (13 lazy pages)；后端: wiki_shared wrong-tenant fallback 修复 (ValueError→404, RuntimeError→503)、page_agent repair/search_label 日志补全、pipeline runner freshness 日志级别提升、persist_classification 日志级别提升 (4361+533 tests)
- [x] Batch AJ: Dashboard 管线配置 + 细粒度进度 ✅ (2026-05-25) — Dashboard: PipelineConcurrencySection (compose/heal/domain/module/flow 并发、heal 轮次、LLM RPM)；后端: heal_pages_node + compose_domain_agents_node 细粒度 progress_callback (4365+535 tests)
- [x] Batch AK: P1 架构持久化修复 ✅ (2026-05-25) — _ALLOWED_PROPERTIES 增加 wiki_architecture_layer/confidence、persist_classification compound-key 查找 (repo|name fallback bare name)、Settings dirty 状态保护 (refetch 不覆盖未保存编辑)、数字字段 min/max 校验 (4368+536 tests)
- [x] Batch AL: P2 安全+性能+前端 ✅ (2026-05-25) — LLM rate limiter 释放锁后 sleep (消除串行化)、/wiki/quick 增加 EDITOR 角色检查、domain 路由 business 绑定校验、pipeline ainvoke 顶层错误边界、前端 useWikiEditSession pageUid 切换重置、test_domain_agent_tier_cap 并发顺序断言修复 (4375+536 tests)
- [x] Batch AM: 管线性能优化 ✅ (2026-05-25) — 探索轮次 tier-aware (SKELETON 8→2, STANDARD 8→5)、module_compose_concurrency 3→6、FalkorDB thread_pool_size 4→8 并暴露配置 (4379 tests)
- [x] Batch AN: 管线质量优化 ✅ (2026-05-25) — Mermaid 图基于 module_call_edges 真实调用关系替代线性链、quality_gate → heal_hints 传递至 heal 策略 (4389 tests)

---

*Items here are non-blocking for the current sprint. Prioritise based on user impact and deployment timeline.*
