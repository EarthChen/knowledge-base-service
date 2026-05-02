# 开发指南

## 项目结构

```text
knowledge-base-service/
├── main.py                 # FastAPI 应用、路由注册、生命周期（分解为 _init_* 函数）
├── config.py               # Pydantic 配置（env / .env）
├── auth.py                 # Token 注册、角色、依赖注入
├── service.py              # KnowledgeBaseService 组合
├── service_registry.py     # 多租户图服务
├── core/
│   └── container.py        # AppContainer 服务容器（替代全局可变单例）
├── api/
│   ├── mcp_server.py       # 主 MCP 清单 + KnowledgeBaseMCPHandler
│   ├── mcp_registry.py     # @mcp_tool 装饰器 + collect_tools 自动注册
│   ├── mcp_wiki_server.py  # 可选：Wiki 专用 HTTP 六工具（与主清单分路由）
│   ├── pagination.py       # 通用分页工具（PaginationParams / PaginatedResponse）
│   ├── rate_limiter.py     # 令牌桶中间件
│   └── routes/             # wiki_*（ingest、feedback、contradiction、mcp tools）、webhook 等
├── indexer/                # Tree-sitter → 图、增量索引、嵌入、Import 解析、配置文件解析（config_indexer.py）
├── store/                  # FalkorDB 存储层（所有 Cypher 查询集中在此）
│   ├── falkordb_store.py   #   基础 CRUD、连接管理、Schema
│   ├── search_store.py     #   向量/关键词/BM25 全文搜索
│   ├── traversal_store.py  #   调用链、继承、依赖、实体解析
│   ├── analysis_store.py   #   Blast Radius、社区、洞察、影响分析
│   ├── wiki_store.py       #   Wiki 图查询
│   ├── indexer_store.py    #   索引器图查询（enrichment、跨仓库）
│   └── graph_queries.py    #   仓库管理、文档、架构层次
├── query/                  # 服务编排层（不含 Cypher，调用 store 层）；含 nl_cypher.py（NL→Cypher）
├── search/                 # RRF 融合辅助
├── wiki/                   # 生成/检索/问答应、Ingest、lint、质量与记忆（见下）
├── llm/                    # OpenAI 兼容提供者
├── dashboard/              # React + Vite SPA（构建 → ../static）；含 pages/FileExplorer.tsx（文件树 + 源码查看）
├── tests/
├── docs/
├── pyproject.toml
├── Dockerfile
└── README.md
```

**`wiki/` 模块补充**：核心管线 `service.py`、`composer.py`、`search.py`、`ask.py`；业务 Wiki 后台任务与 Redis 状态 `task_store.py`、`task_registry.py`（由 `bootstrap` 接线）；增量与自动化 `incremental.py`、`change_detector.py`；v2 能力 `deep_research.py`、`memory_loop.py`、`memory_tiers.py`；质量 `confidence_scorer.py`、`confidence_inputs.py`、`lint.py`、`lint_scheduler.py`、`auto_healer.py`（自愈**类**；与 `WIKI__AUTO_HEAL_ENABLED` 的运行时接线见 [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md)）；Agent 文档 `agents_md_generator.py`；主 MCP 合并清单见 `mcp_tools.py`。图侧扩展含 `store/wiki_changelog.py`、`store/wiki_feedback_store.py`、`store/wiki_memory_store.py`、`store/wiki_qa_store.py` 等（以 `store/` 实际文件为准）。

## 开发环境搭建

### 后端

```bash
uv sync
uv sync --extra dev    # pytest, ruff 等开发依赖
```

`pyproject.toml` 中的可选扩展：

```bash
uv sync --extra torch    # 不仅使用 ONNX 时的 GPU sentence-transformers 路径
```

运行 API：

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8100
```

### 前端

```bash
cd dashboard
pnpm install
pnpm dev          # 本地开发服务器
pnpm build        # 生产构建 → static/
```

项目约定使用 **`pnpm`**，禁止使用 npm。

## 测试

```bash
uv run python -m pytest
```

异步测试使用 `pytest-asyncio`（`pyproject.toml` 中 `asyncio_mode = auto`）。

前端：**`pnpm build`** 验证 TypeScript 和 Vite 生产构建（CI 风格）；若需收紧质量门禁可添加 `pnpm lint`（ESLint）。

## 新增编程语言支持

1. **配置** — 在 `config.py` 中扩展 `supported_languages` 和 `file_extensions`（或通过环境变量覆盖，如部署支持列表序列化）。
2. **解析器** — 在 `indexer/tree_sitter_parser.py` 中添加或扩展 Tree-sitter 查询（及相关语言辅助）。
3. **图构建** — 在 `indexer/code_graph_builder.py` 中将 AST 构造映射到 `NodeLabel` / `EdgeType`。
4. **向量** — 确保生成的节点使用 `store/schema.py` 中 `VECTOR_INDEX_CONFIGS` 覆盖的标签（如需嵌入）。
5. **测试** — 在 `tests/indexer/` 下添加测试夹具代码片段并运行 pytest。

## 新增 MCP 工具

**主服务清单**（`GET /api/v1/mcp/tools` / `POST /api/v1/mcp/tool`）：

1. 在 `api/mcp_server.py` 的 `MCP_TOOLS_MANIFEST` 中追加条目；Wiki 管线工具在 `wiki/mcp_tools.py` 的 `WIKI_MCP_TOOLS_MANIFEST` 末尾合并。
2. 在 `KnowledgeBaseMCPHandler` 或 `WikiMCPHandler` 上实现处理函数，使用 `@mcp_tool("tool_name", min_role=Role.VIEWER)` 装饰器声明工具名和最低角色（装饰器定义在 `api/mcp_registry.py`）。
3. 工具会在 `__init__` 中通过 `collect_tools()` 自动发现并注册到分派表，无需手动维护字典。
4. 在 `tests/test_mcp_*.py` 中覆盖。

**Wiki 专用 HTTP 六工具**（`WIKI__MCP_SERVER_ENABLED`）：清单与路由在 `api/mcp_wiki_server.py`、`api/routes/wiki_mcp_routes.py`（`POST /api/v1/mcp/tools/call` 的请求体使用 `name` + `arguments`）；测试见 `tests/api/test_mcp_wiki_server.py`。

## 代码规范

- **Python**：Ruff（`pyproject.toml` 中 `tool.ruff`），target 3.12，行宽 120。
- **类型注解**：公共 API 优先使用显式类型（`from __future__ import annotations`）。
- **日志**：使用 `log = get_logger(__name__)` 和结构化键（`log.info("event", key=value)`）。

运行 Ruff：

```bash
uv run ruff check .
uv run ruff format .
```
