# Knowledge Base Service — 开发指南

本文档面向在本仓库中进行功能开发、调试与扩展的贡献者，说明仓库布局、前后端工具链、测试策略与扩展路径（语言索引、MCP 工具等）。内容以仓库当前代码为准。

---

## 1. 概述

**Knowledge Base Service** 是一套基于 **FastAPI** 的后端服务：将代码与文档索引进 **FalkorDB** 图数据库与向量检索管线，提供混合检索、深度检索、图谱探索、Wiki 生成与问答、Webhook 同步以及 MCP（Model Context Protocol）工具暴露。**多租户**通过「业务（business）」维度隔离图空间。**Dashboard** 为独立的 **React 19 + Vite 8** SPA，构建产物输出到后端 `static/` 目录由同一进程托管。

核心技术栈概要：

| 层级 | 技术 |
|------|------|
| API | FastAPI、Uvicorn、Pydantic Settings、structlog |
| 存储 | FalkorDB（图 + 向量索引配置）、Redis（Wiki 任务等）、SQLite（LangGraph checkpoint / 会话等） |
| 索引 | Tree-sitter、可选 ONNX / Torch + transformers 嵌入 |
| Wiki / Agent | LangGraph、LangChain Core、迭代 RAG、SSE 事件 |
| 前端 | React 19、Vite 8、TypeScript 5.9、Tailwind 4、TanStack Query 5 |

---

## 2. 顶层目录与后端入口（完整结构）

以下为后端与共享资源的主体布局（含各文件职责说明）。若与磁盘个别新增文件不一致，以仓库实际为准。

```
knowledge-base-service/
├── main.py                 # FastAPI 应用工厂、create_app()、lifespan：
│                           #   生命周期分解为 _init_security / _init_core_services /
│                           #   _init_wiki_and_lint / _shutdown_all
├── config.py               # Pydantic Settings：FalkorDBConfig、EmbeddingConfig、LLMConfig（含 GatewayConfig）、
│                           #   HybridSearchConfig、RerankConfig、AppWikiFlags（约 50+ 开关）、GitConfig、Settings
├── auth.py                 # Token 注册（tokens.yaml / API_TOKENS / API_TOKEN）、Role 枚举（VIEWER=1, EDITOR=2, ADMIN=3）、
│                           #   require_role()、业务域鉴权、SSE/WebSocket 场景的 token 路径处理
├── log.py                  # structlog：LOG_FORMAT（console/json）、get_logger()
├── service.py              # 向后兼容：转发 services.kb_service
├── service_registry.py     # 向后兼容：转发 services.service_registry
├── scheduler.py            # 向后兼容：转发 services.scheduler
├── redis_startup.py        # 向后兼容：转发 services.redis_startup
├── core/
│   ├── __init__.py
│   └── container.py        # AppContainer：settings、registry、task_manager、repo_registry、scheduler、
│                           #   settings_store、信号量；以及约 18 个 Wiki 相关 Optional 字段；
│                           #   create_test() 测试工厂
├── api/
│   ├── mcp_server.py       # KnowledgeBaseMCPHandler：核心 MCP_TOOLS_MANIFEST（12 项）+
│                           #   wiki/mcp_tools 合并后共 22 项工具；@mcp_tool 装饰的处理函数；
│                           #   handle_tool_call 经 collect_tools() 派发表分发
│   ├── mcp_registry.py     # @mcp_tool(name, min_role=Role.VIEWER)、collect_tools(instance)、
│                           #   collect_elevated_tool_roles(*classes)
│   ├── mcp_wiki_server.py  # MCPWikiServer：6 个 TOOL_DEFINITIONS；由 WIKI__MCP_SERVER_ENABLED 控制是否启用
│   ├── pagination.py       # PaginationParams(offset, limit 1–100)、PaginatedResponse、slice_page()
│   ├── rate_limiter.py     # RateLimiterMiddleware：按 IP 令牌桶；跳过 /assets/、/favicon.ico、/health；
│                           #   install_rate_limiter()
│   ├── kb_state.py         # 过渡期兼容：_bind(container) 将 AppContainer 同步到模块全局变量
│   ├── error_handler.py    # register_exception_handlers
│   ├── exceptions.py       # 领域异常
│   ├── request_context.py  # 请求上下文辅助
│   ├── pr_fetch.py         # PR 文件拉取逻辑
│   ├── middleware/
│   │   └── request_logging.py  # RequestLoggingMiddleware
│   ├── models/
│   │   └── wiki_models.py  # Wiki HTTP 请求体的 Pydantic 模型
│   └── routes/
│       ├── kb_routers.py           # 路由聚合（viewer/editor/admin/public/wiki/settings/business/webhook/provider/mcp_wiki）
│       ├── public_health_routes.py # GET /health（含 FalkorDB ping）、GET /auth/me
│       ├── search_routes.py        # POST /hybrid、/deep-search、/deep-search/stream、GET /search/architecture
│       ├── repository_routes.py    # GET /repositories（分页）、DELETE /index/{repo}
│       ├── indexing_routes.py      # POST /index、/reindex/all、/enrich、/index/files
│       ├── admin_graph_mcp_routes.py  # 图探索/扩展/blast-radius/communities、MCP 工具 HTTP、管理操作
│       ├── business_routes.py      # 业务 CRUD、仓库绑定（分页）
│       ├── business_sync_routes.py # 同步调度、sync/repo、sync/all、sync/repo-update-wiki
│       ├── settings_routes.py      # 运行时设置 CRUD、test-connection
│       ├── wiki_routes.py          # 聚合 Wiki 子路由
│       ├── wiki_page_routes.py     # Wiki 页面 CRUD、搜索、树、导出、coverage、quality
│       ├── wiki_task_routes.py     # Wiki 生成任务、业务批量生成（202）、SSE 事件
│       ├── wiki_ask_routes.py      # Wiki 问答/stream、research、questions、crystallize
│       ├── wiki_feedback_routes.py # 反馈、review、regenerate、lint、ingest、changelog
│       ├── wiki_contradiction_routes.py  # 矛盾列表、确认、解决
│       ├── wiki_mcp_routes.py      # Wiki MCP HTTP：tools/list、tools/call
│       └── webhook_routes.py       # Webhook 配置、推送入库、托管方钩子（GitHub/GitLab/Gitea）
├── indexer/
│   ├── tree_sitter_parser.py   # 按语言的 AST 解析
│   ├── code_graph_builder.py   # AST → GraphNode / GraphEdge
│   ├── incremental_indexer.py  # 基于 Git diff 的增量索引
│   ├── doc_indexer.py          # 文档类文件索引
│   ├── smart_chunker.py        # 智能分块
│   ├── child_chunker.py        # 父子块拆分
│   ├── embedding_generator.py  # EmbeddingGenerator：ONNX/torch、shared()、查询缓存
│   ├── task_manager.py         # IndexTaskManager：进程内任务跟踪
│   ├── enrichment.py           # LLM enrichment
│   ├── graph_enricher.py       # 图级 enrichment
│   ├── concept_extractor.py    # 业务概念抽取
│   ├── business_flow_inferencer.py  # 业务流程推断
│   ├── cross_repo_enricher.py  # 跨仓库 enrichment
│   ├── config_indexer.py       # 配置文件（.yml/.yaml/.xml/.properties/.env/.toml/.conf）索引
│   └── index_report.py         # 索引报告生成
├── store/
│   ├── falkordb_store.py       # FalkorDB 基础操作、异步场景的 ThreadPoolExecutor
│   ├── schema.py               # NodeLabel、EdgeType、VECTOR_INDEX_CONFIGS
│   ├── search_store.py         # 向量 / 关键词 / BM25、检索facet 等搜索相关查询
│   ├── traversal_store.py      # 调用链、继承、依赖遍历
│   ├── analysis_store.py       # Blast radius、社区、洞察类查询
│   ├── graph_queries.py        # 仓库管理、文档查询
│   ├── wiki_store.py           # Wiki 图查询
│   ├── wiki_page_store.py      # Wiki 页面 CRUD、版本、新鲜度
│   ├── wiki_tree_store.py      # Wiki 树结构
│   ├── wiki_feedback_store.py  # 反馈持久化
│   ├── wiki_qa_store.py        # Q&A 记忆持久化
│   ├── wiki_claim_store.py     # Claim / supersession 跟踪
│   ├── wiki_contradiction_store.py  # 矛盾持久化
│   ├── wiki_memory_store.py    # 记忆分层持久化
│   ├── wiki_coverage_store.py  # Coverage 分析
│   ├── wiki_changelog.py       # Changelog 持久化
│   ├── wiki_store_common.py    # Wiki store 共用工具
│   ├── business_manager.py     # 多租户图命名
│   ├── settings_store.py       # 运行时设置持久化
│   ├── indexer_store.py        # 索引器元数据查询
│   ├── conversation_store.py   # SQLite 会话存储
│   └── fqn_utils.py            # FQN_RE、is_fqn()、parse_fqn()、extract_fqns()
├── query/
│   ├── hybrid_query.py         # HybridQueryService：三路 RRF 融合
│   ├── graph_query.py          # GraphQueryService
│   ├── semantic_query.py       # 语义检索
│   ├── nl_cypher.py            # NL→Cypher（Dashboard 等）；只读校验、扩展可变关键词黑名单
│   ├── deep_search.py          # DeepSearchEngine
│   ├── agent_workflow.py       # Agent 工作流
│   ├── context_assembler.py    # 上下文拼装
│   ├── reranker.py             # Cross-encoder 重排序
│   ├── analysis_service.py     # 分析服务门面
│   ├── blast_radius.py         # BlastRadiusAnalyzer
│   ├── community_detection.py  # CommunityDetector（标签传播等）
│   ├── endpoint_queries.py     # API 端点查询
│   ├── graph_insights.py       # 图洞察
│   └── query_router.py         # QueryRouter：按意图调节权重
├── search/
│   └── fusion.py               # RRF 融合实现细节
├── wiki/
│   ├── service.py              # WikiService：主生成管线；generate_business_wiki
│   ├── agents/                 # Agent 框架包（见 CODEMAPS/INDEX.md Agent 框架节）
│   │   ├── base_agent.py      # GenericAgent, ToolRegistry, ToolDef, RunConfig
│   │   ├── runner.py          # run_agent_loop(), LoopConfig, LoopHooks, AgentLoopResult
│   │   ├── agent_tool.py      # agent_tool() — 子 Agent 包装为 ToolDef
│   │   ├── tool_decorator.py  # @function_tool 装饰器
│   │   ├── context.py         # RunContext, WikiDeps（类型化 DI）
│   │   ├── guardrails.py      # Input/OutputGuardrail
│   │   ├── tracing.py         # AgentTracer, Span
│   │   ├── handoff.py         # execute_handoff()
│   │   ├── edit_agent.py      # WikiEditAgent
│   │   ├── doc_orchestrator.py # DocOrchestrator (Template Method)
│   │   ├── ask_orchestrator.py # AskOrchestrator
│   │   └── research_orchestrator.py # ResearchOrchestrator
│   ├── page_agent.py          # WikiPageAgent：14 个 @function_tool 方法
│   ├── composer.py             # WikiComposer
│   ├── search.py               # WikiSearchService：混合 Wiki 检索（图 2.0、向量 1.0、FTS 1.5 权重示例）
│   ├── ask.py                  # WikiAskService：ask_stream、crystallize；GraphEnhancedContextCollector
│   ├── deep_research.py        # DeepResearchService：拆解 + 多轮 RAG + 综合
│   ├── bootstrap.py            # bootstrap_wiki：将约 20 个服务挂到 app.state / container
│   ├── task_store.py           # WikiTaskStore：Redis Hash + UUID 锁 + Lua CAS 解锁
│   ├── task_registry.py        # 内存任务注册表兜底
│   ├── event_bus.py            # WikiEventBus：发布订阅、心跳（如 30s）
│   ├── lint.py                 # WikiLintService：质量 lint、置信度重算、schema 校验
│   ├── lint_scheduler.py       # LintScheduler：周期性 lint
│   ├── auto_healer.py          # AutoHealer：坏链清理、孤儿条目降级等
│   ├── confidence_scorer.py    # ConfidenceScorer：五信号加权
│   ├── contradiction_detector.py  # ContradictionDetector：向量相似度 + LLM 裁决
│   ├── memory_loop.py          # MemoryLoop：问答 → 可检索记忆
│   ├── memory_tiers.py         # MemoryTierManager：四层晋升规则
│   ├── incremental.py          # 增量 Wiki 生成
│   ├── change_detector.py      # ChangeDetector
│   ├── export_service.py       # WikiExportService：打包结果
│   ├── exporter.py             # WikiExporter：Markdown 导出
│   ├── disk_exporter.py        # 磁盘导出
│   ├── mkdocs_exporter.py      # MkDocs 格式导出
│   ├── obsidian_exporter.py    # Obsidian 格式导出
│   ├── git_publisher.py        # Git 发布
│   ├── business_wiki_exporter.py # 业务 Wiki 导出
│   ├── agents_md_generator.py  # AGENTS.md 生成
│   ├── protocols.py            # WikiGraphStorePort 等 Protocol
│   ├── mcp_tools.py            # WikiMCPHandler：WIKI_MCP_TOOLS_MANIFEST（10 项）+ 处理函数
│   ├── model_strategy.py       # ModelStrategy：按任务类型动态路由 LLM
│   ├── rag/
│   │   ├── engine.py           # IterativeRAGEngine（LangGraph StateGraph）
│   │   ├── protocol.py         # Chunk、Source、RetrievalScope、Retriever Protocol
│   │   ├── wiki_retriever.py   # WikiRetriever 适配器
│   │   ├── code_retriever.py   # CodeRetriever 适配器
│   │   ├── composite_retriever.py  # 组合检索器
│   │   └── events.py           # SSE 事件约定
│   ├── webhook/
│   │   ├── receiver.py、event_model.py、dispatcher.py、debounce.py
│   │   └── providers/          # github.py、gitlab.py、gitea.py、commits.py、timeutil.py
│   └── …                       # planners、composers、quality evaluator 等（见 wiki/ 目录）
├── llm/
│   ├── provider.py、openai_provider.py、azure_provider.py、custom_provider.py
│   ├── provider_factory.py、gateway_client.py（Gateway WebSocket + HTTP）、base_provider.py（LLMPortBridge）
├── services/
│   ├── service_registry.py     # ServiceRegistry：共享 FalkorDB、按业务的 KB 实例、就绪状态
│   ├── kb_service.py           # KnowledgeBaseService：索引、检索、MCP、Wiki 等门面
│   ├── repo_registry.py        # RepoRegistry：克隆路径目录
│   ├── git_manager.py          # GitManager：clone/pull
│   ├── scheduler.py            # SyncScheduler：定时 git 同步
│   ├── redis_startup.py        # Redis BusyLoadingError 等启动处理
│   ├── settings_service.py、settings_crypto.py  # 设置服务与字段加密
├── dashboard/                  # React SPA（见第 3 节）
├── tests/                      # 后端 pytest（当前约 2603 条用例，见第 5 节）
├── docs/                       # 项目文档（架构、已知问题、实施状态等）
├── pyproject.toml              # Python 3.12+、依赖、Ruff、pytest 配置、dependency-groups
├── Dockerfile
└── README.md
```

### 2.1 `AppContainer` 与 Wiki 接线

`core/container.py` 中的 **`AppContainer`** 承载应用级单例：**核心字段**在 `main.py` 的 `_init_core_services` 中填充；**Wiki 相关可选字段**（如 `wiki_store`、`wiki_task_store`、`wiki_event_bus`、`wiki_memory_loop`、`mcp_wiki_server` 等）由 `wiki/bootstrap.py` 的 **`bootstrap_wiki`** 在 lifespan 中写入，并由 **`api/kb_state.py`** 的 `_bind(container)` 同步到旧代码路径使用的模块级变量，便于渐进迁移。

### 2.2 MCP 工具数量说明（便于对照）

- **`api/mcp_server.py`**：`MCP_TOOLS_MANIFEST` = **12** 个核心工具条目 **`+`** **`wiki/mcp_tools.py`** 中的 **`WIKI_MCP_TOOLS_MANIFEST`（10 项）** ⇒ **合计 22** 项在主 MCP Handler 清单中。
- **`api/mcp_wiki_server.py`**：可选 Wiki 专用 HTTP 服务 **6** 个工具定义；启用标志见配置 **`WIKI__MCP_SERVER_ENABLED`**；路由见 **`api/routes/wiki_mcp_routes.py`**（如 `tools/list`、`tools/call`）。

---

## 3. Dashboard 前端结构

Dashboard 与后端仓库同根目录，开发时使用 Vite 代理将 **`/api`** 转发到后端 **`http://localhost:8100`**；生产构建输出到 **`../static`**。

```
dashboard/
├── package.json                # React 19、Vite 8、TypeScript ~5.9、Tailwind 4、TanStack Query 5
├── vite.config.ts              # 端口 5173；proxy /api → localhost:8100；manualChunks；outDir: ../static
├── vitest.config.ts            # jsdom、globals、setupFiles、coverage v8、行覆盖率阈值 70%
├── playwright.config.ts        # E2E baseURL http://localhost:8100（webServer 默认未内置，需自备后端）
├── tsconfig.json               # 解决方案风格 references
├── e2e/                        # Playwright E2E（如 smoke.spec.ts）
└── src/
    ├── main.tsx                # QueryClient（如 retry:1、staleTime:30s）、Provider 链
    ├── App.tsx                 # ToastProvider → ErrorBoundary → Routes（12 个懒加载页面 + 重定向）
    ├── index.css               # Tailwind 4、@custom-variant dark、自定义 slate 色板
    ├── theme.ts                # 深色模式（如 kb_theme localStorage）
    ├── currentBusiness.ts      # kb_business_id localStorage
    ├── api/
    │   ├── client.ts           # API_BASE="/api/v1"、authHeaders（Bearer + X-Business-Id）、ApiError
    │   ├── types.ts            # API 响应类型
    │   └── hooks.ts            # 大量 TanStack Query hooks（与各 REST 端点对齐）
    ├── contexts/
    │   ├── AuthContext.tsx      # /auth/me、基于角色的 UI 开关
    │   └── BusinessContext.tsx  # 多租户业务选择、绑定模式
    ├── i18n/
    │   ├── context.tsx         # I18nProvider、detectLocale
    │   ├── en.ts / zh.ts       # 文案
    │   └── types.ts
    ├── hooks/                  # 自定义 hooks（wiki、settings、search、streaming 等）
    ├── pages/                  # 页面组件 + settings/panels/ 等子面板
    ├── components/
    │   ├── Layout.tsx          # 侧边栏、移动端遮罩（可访问性）、主题切换、业务选择器
    │   ├── ErrorBoundary.tsx、Toast.tsx、CommandPalette.tsx（Cmd+K、FocusTrap、防抖混合搜索）
    │   ├── wiki/               # 大量 Wiki UI（约 60+ 组件量级）
    │   └── settings/
    ├── utils/
    │   ├── wikiPath.ts         # encodeWikiPath() 统一 Wiki 路径编码
    │   ├── highlightTerms.ts、errorUtils.ts
    └── test/
        ├── setup.ts            # localStorage mock、MSW Server
        ├── renderWithI18n.tsx
        └── mocks/              # MSW handlers（onUnhandledRequest: "error" 建议在 setup 中启用以避免静默漏网）
```

**约定：** 前端包管理使用 **`pnpm`**（勿混用 npm），与 CI / 团队协作保持一致。

---

## 4. 开发环境搭建

### 4.1 前置条件

- **Python ≥ 3.12**（见 `pyproject.toml`）
- **[uv](https://docs.astral.sh/uv/)**（推荐）用于虚拟环境与依赖锁定
- **Node.js + pnpm**（Dashboard）
- 本地或可达的 **FalkorDB**、**Redis**（以及按需配置的 LLM / 嵌入服务端点）

### 4.2 后端

```bash
uv sync                          # 安装运行时依赖（写入/使用 .venv）
uv sync --extra dev              # 额外：pytest、pytest-asyncio、pytest-cov、ruff
uv sync --group dev              # dependency-groups：pytest-timeout（长时间测试防护）
# 一次性开发环境常见写法：
uv sync --extra dev --group dev

uv sync --extra torch            # 可选：torch + sentence-transformers（GPU/非 ONNX 嵌入路径）
```

启动 API（默认端口 **8100**）：

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8100
```

说明：

- **`main.py`** 在 lifespan 内依次执行安全校验、核心服务、`bootstrap_wiki`、关闭清理；详见源码中的 **`_init_security`**、**`_init_core_services`**、**`_init_wiki_and_lint`**、**`_shutdown_all`**。
- 生产环境可通过 **`KB_ENV=production`** 与 **`require_auth`**、Token 配置联动做强制校验（详见 `main.py` 内 **`_enforce_production_security`**）。

### 4.3 前端（Dashboard）

```bash
cd dashboard
pnpm install
pnpm dev          # http://localhost:5173 ，开发时将 /api 代理到后端 8100
pnpm build        # tsc -b && vite build → 输出 ../static/
pnpm lint         # ESLint（建议在提交前运行）
```

本地完整体验 typical 流程：**终端 A** 启动 `uvicorn`，**终端 B** `pnpm dev`，浏览器访问 Vite 地址即可通过代理调用后端。

### 4.4 日志格式

环境变量 **`LOG_FORMAT`**：`console`（人类可读）或 **`json`**（结构化，便于采集）。

代码中使用 **`from log import get_logger`**，`log = get_logger(__name__)`，并以键值对传递上下文字段。

---

## 5. 测试

### 5.1 后端（pytest）

当前仓库收集规模约为 **3775** 条用例（以 `pytest --collect-only` 为准）。

```bash
uv run pytest                              # 全量并行执行（默认 -n auto，约 60s）
uv run pytest tests/ -x --timeout=30 -q    # 快速失败 + 超时（需已安装 pytest-timeout）
uv run pytest --cov=. --cov-report=html    # HTML 覆盖率报告
uv run pytest tests/wiki/agents/ -x        # 仅 agent 框架测试
```

要点：

- **`asyncio_mode = auto`**（`pyproject.toml` → `[tool.pytest.ini_options]`）
- **`pythonpath = ["."]`**：保证顶层包（如 `search/`、`wiki/`）在收集 `tests/query/` 等路径时被解析
- **`pytest-xdist`**：默认 **`-n auto`** 并行执行，充分利用多核 CPU（约 4-6x 加速）
- **`pytest-timeout`**：声明在 **`[dependency-groups] dev`**，建议使用 **`uv sync --group dev`** 安装
- 目录大致包含：`tests/` 根、`tests/api/`、`tests/store/`、`tests/wiki/`（多层子目录，含 `agents/`、`rag/`、`integration/`、`mcp/`）、`tests/query/`、`tests/llm/`、`tests/embedding/` 等

### 5.2 前端（Vitest + Playwright）

当前约为 **306** 条测试、**84** 个测试文件（以 Vitest 汇总为准）。

```bash
cd dashboard
pnpm test              # Vitest 单次运行
pnpm test:watch        # 监听模式
pnpm test:coverage     # v8 覆盖率；vitest.config.ts 中行覆盖率阈值 **≥ 70%**
pnpm test:e2e          # Playwright（需后端已在 baseURL 可访问，见 playwright.config.ts）
```

要点：

- **MSW v2** 模拟 HTTP；建议在全局 setup 中对 **`onUnhandledRequest: "error"`** 保持严格，避免未 mock 请求悄悄通过。
- **Testing Library** + **user-event**；部分 **`*.a11y.test.tsx`** 侧重可访问性。

---

## 6. 扩展指南

### 6.1 新增编程语言索引支持

1. **配置**：在 **`config.py`** 扩展 **`supported_languages`** 与 **`file_extensions`**（或通过 Settings 对应 env 覆盖）。
2. **解析**：在 **`indexer/tree_sitter_parser.py`** 增加或扩展 Tree-sitter queries。
3. **构图**：在 **`indexer/code_graph_builder.py`** 将 AST 映射到 **`NodeLabel` / `EdgeType`**（`store/schema.py`）。
4. **向量**：确认涉及节点标签落在 **`VECTOR_INDEX_CONFIGS`** 内（若需要嵌入）。
5. **测试**：在 **`tests/indexer/`** 增加最小复现实例与断言。

### 6.2 新增 MCP 工具（主清单）

1. 在 **`api/mcp_server.py`** 的 **`MCP_TOOLS_MANIFEST`** 增加条目；或与 Wiki 相关时在 **`wiki/mcp_tools.py`** 的 **`WIKI_MCP_TOOLS_MANIFEST`** 追加（会自动拼入主清单）。
2. 在 **`KnowledgeBaseMCPHandler`** / **`WikiMCPHandler`** 上实现处理函数，并使用 **`api/mcp_registry.py`** 的 **`@mcp_tool("tool_name", min_role=Role.VIEWER)`**（按需提高 **`EDITOR`/`ADMIN`**）。
3. **`collect_tools()`** 在实例初始化时自动发现装饰器方法并注册派发表，无需手写巨大字典。
4. 测试： **`tests/test_mcp_*.py`** 或 **`tests/api/test_mcp_*.py`**。

**Wiki 专用 HTTP MCP（六工具）**：实现与路由分别在 **`api/mcp_wiki_server.py`**、**`api/routes/wiki_mcp_routes.py`**；请求体常为 **`name` + `arguments`**；配套测试可参考 **`tests/api/test_mcp_wiki_server.py`**。

### 6.3 Dashboard 新增 API 消费端

1. 在 **`src/api/types.ts`** 对齐后端响应类型。
2. 在 **`src/api/client.ts`** 如需扩展通用错误或 header 逻辑。
3. 在 **`src/api/hooks.ts`**（或拆分的 hooks 模块）新增 **`useQuery`/`useMutation`**，与 **`API_BASE="/api/v1"`** 路径一致。
4. 页面与 **`AuthContext` / `BusinessContext`** 保持一致：**Bearer Token** + **`X-Business-Id`**（见 `client.ts`）。

---

## 7. 代码规范（Python）

- **格式化与 Lint**：**Ruff**，target **py312**，行宽 **120**，规则 **`E,F,I,N,W,UP`**（见 `pyproject.toml`）。
- **类型**：模块级推荐 **`from __future__ import annotations`**；公共 API 显式注解。
- **日志**：统一 **`structlog`** + **`get_logger(__name__)`**，结构化字段而非拼接长字符串。

```bash
uv run ruff check .
uv run ruff format .
```

---

## 8. 依赖说明（`pyproject.toml` 摘要）

**运行时（节选）：** `fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`、`structlog`、`falkordb`（**< 2**）、`redis`、`tree-sitter`、`tree-sitter-language-pack`、`python-dotenv`、`numpy`、`onnxruntime`、`transformers`、`huggingface-hub`、`pyyaml`、`httpx`、`tenacity`、`json-repair`、`jieba`、`cryptography`、`aiosqlite`、`langgraph`、`langchain-core`、`langgraph-checkpoint-sqlite`、`mermaid-syntax-parser`。

**可选 `torch` extra：** `torch`、`sentence-transformers`。

**开发 `dev` extra：** `pytest`、`pytest-asyncio`、`pytest-cov`、`pytest-xdist`、`ruff`。

**dependency-groups `dev`：** `pytest-timeout`。

---

## 9. 相关文档

- **[README.md](../README.md)**：面向使用的快速开始与环境变量索引。
- **[ARCHITECTURE.md](ARCHITECTURE.md)**：系统架构与数据流。
- **[REMAINING-WORK.md](REMAINING-WORK.md)**：剩余工作积压项。

若在文档与代码之间发现不一致，**以代码与测试为准**，并欢迎提交文档修正。

---

## 10. AI Agent 常见任务

### 10.1 Adding a new agent tool

1. Define the method on `WikiPageAgent` (or relevant agent) with `@function_tool` decorator
2. Specify `tier=` parameter (1-3) for activation round
3. The tool is auto-registered by `collect_tools()` — no manual schema needed
4. Add tests in `tests/wiki/agents/`

### 10.2 Adding a new MCP tool

1. Add to `MCP_TOOLS_MANIFEST` in `api/mcp_server.py` (or `WIKI_MCP_TOOLS_MANIFEST` in `wiki/mcp_tools.py`)
2. Implement handler with `@mcp_tool("name", min_role=Role.VIEWER)` decorator
3. Test in `tests/api/`

### 10.3 Adding a new API route

1. Choose router by role: `public_router`, `viewer_router`, `editor_router`, `admin_router`
2. Add route in appropriate `api/routes/*_routes.py`
3. Use `Depends(require_role(...))` for auth
4. Add response type to `api/models/`

### 10.4 Modifying the wiki generation pipeline

1. Pipeline definition: `wiki/pipeline_graph.py`
2. Node implementations: `wiki/nodes/` (17 node files)
3. State: `wiki/pipeline_state.py`
4. Concurrency: `wiki/pipeline_concurrency.py` (PipelineConcurrency)
5. Test: `tests/wiki/integration/` + `tests/wiki/nodes/`
