# 开发指南

## 项目结构

```text
knowledge-base-service/
├── main.py                 # FastAPI 应用、路由注册、生命周期
├── config.py               # Pydantic 配置（env / .env）
├── auth.py                 # Token 注册、角色、依赖注入
├── service.py              # KnowledgeBaseService 组合
├── service_registry.py     # 多租户图服务
├── api/
│   ├── mcp_server.py       # MCP 清单 + KnowledgeBaseMCPHandler
│   ├── rate_limiter.py     # 令牌桶中间件
│   └── routes/             # Wiki、Webhook、Provider 辅助路由
├── indexer/                # Tree-sitter → 图、增量索引、嵌入、Import 解析
├── store/                  # FalkorDB 存储层（所有 Cypher 查询集中在此）
│   ├── falkordb_store.py   #   基础 CRUD、连接管理、Schema
│   ├── search_store.py     #   向量/关键词/BM25 全文搜索
│   ├── traversal_store.py  #   调用链、继承、依赖、实体解析
│   ├── analysis_store.py   #   Blast Radius、社区、洞察、影响分析
│   ├── wiki_store.py       #   Wiki 图查询
│   ├── indexer_store.py    #   索引器图查询（enrichment、跨仓库）
│   └── graph_queries.py    #   仓库管理、文档、架构层次
├── query/                  # 服务编排层（不含 Cypher，调用 store 层）
├── search/                 # RRF 融合辅助
├── wiki/                   # Wiki 管道、MCP Wiki 工具、Webhook、调度器
├── llm/                    # OpenAI 兼容提供者
├── dashboard/              # React + Vite SPA（构建 → ../static）
├── tests/
├── docs/
├── pyproject.toml
├── Dockerfile
└── README.md
```

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

1. 在 `api/mcp_server.py` 的 `MCP_TOOLS_MANIFEST` 中追加清单条目（Wiki 相关工具则在 `wiki/mcp_tools.py` 的 `WIKI_MCP_TOOLS_MANIFEST`）。
2. 若工具需要高于 Viewer 的权限，在 `MCP_TOOL_MIN_ROLE` 中添加（`Role.EDITOR` 或 `Role.ADMIN`）。
3. 在 `KnowledgeBaseMCPHandler` 上实现异步处理方法（或委托给 `WikiMCPHandler`）。
4. 在 `handle_tool_call` 内部的 `handlers` 字典中注册工具名。
5. HTTP `POST /api/v1/mcp/tool` 通过已有路由自动可用；工具列表通过 `get_tools_manifest` 暴露。
6. 在 `tests/test_mcp_*.py` 下添加测试。

## 代码规范

- **Python**：Ruff（`pyproject.toml` 中 `tool.ruff`），target 3.12，行宽 120。
- **类型注解**：公共 API 优先使用显式类型（`from __future__ import annotations`）。
- **日志**：使用 `log = get_logger(__name__)` 和结构化键（`log.info("event", key=value)`）。

运行 Ruff：

```bash
uv run ruff check .
uv run ruff format .
```
