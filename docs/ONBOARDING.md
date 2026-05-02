# Knowledge Base Service — 用户与入职指南

本文面向**首次接触本系统的使用者与运维人员**：说明系统定位、仪表盘各页面用途、HTTP API 能力一览、首次索引流程、检索技巧、MCP 集成方式与认证模型。实现细节与部署变量请参阅 [DEPLOYMENT.md](DEPLOYMENT.md)；Agent 工具契约请参阅 [MCP-INTEGRATION.md](MCP-INTEGRATION.md)；跨仓业务 Wiki 管线请参阅 [wiki-generation-architecture.md](wiki-generation-architecture.md)。

---

## 这个系统是什么？

**Knowledge Base Service** 是一套独立的**代码与文档知识库**：将代码仓库索引为 **FalkorDB 属性图**（实体与关系：函数、类、模块、调用、导入、文档节点等）以及 **稠密向量嵌入**（默认模型 **BAAI/bge-m3**，与其它检索组件协同），并在其上提供：

- **自然语言混合检索**：关键词、语义向量与 **BM25 全文**等多路召回，经 **RRF（倒数秩融合）** 等方法合并，可选图扩展与重排序；
- **关系与结构探索**：图谱浏览、变更影响（Blast Radius）、社区发现、架构分层与端点视图；
- **可选 LLM Wiki 流水线**：生成 / 增量更新 Markdown Wiki、问答（含 SSE）、深度研究、质量与矛盾检测、导出与多租户业务空间；
- **React Web 仪表盘**：无需写脚本即可完成搜索、看图谱、浏览文件与 Wiki、触发索引与配置。

界面为 **React + Vite** 单页应用：图谱与重型可视化**按需路由懒加载**，仅在打开对应页面时加载。

**本地默认入口**：启动后端（例如 `uv run uvicorn main:app …`）后访问根 URL，通常为 **http://localhost:8100**。前端也可在 `dashboard` 目录单独 `pnpm dev` 进行开发。

---

## 仪表盘导览（12 个核心页面）

下列路由与 README / 实现对齐；括号内为你在页面上能完成的典型任务。

| 路由 | 页面 | 你能做什么 |
|------|------|------------|
| **`/`** | **总览（Overview）** | 查看系统健康、图与向量相关全局统计、已索引仓库数量、快捷入口与入门提示 |
| **`/search`** | **搜索（Search）** | **混合搜索**（关键词 + 语义 + BM25，RRF 融合）、分页与排序、**跨仓库聚合**；按实体类型、仓库、语言等筛选 |
| **`/explorer`** | **图谱浏览器（Graph Explorer）** | **Dagre** 布局可视化；**双击节点**渐进展开邻居；支持撤销；侧栏 **Blast Radius**（变更影响分析）、**社区发现**（代码模块聚类） |
| **`/files`** | **文件浏览器（File Browser）** | 目录树 + **`prism-react-renderer`** 语法高亮源码；行旁 **实体徽章**（函数/类等），可跳转图谱、搜索或 Wiki；**须先选择已索引的仓库** |
| **`/architecture`** | **架构（Architecture）** | 按层次（presentation / application / domain / infrastructure 等）与 **端点类型**分类查看架构视图（依赖索引与丰富化管线） |
| **`/repositories`** | **仓库（Repositories）** | 列出已索引仓库及其统计与状态 |
| **`/documents`** | **文档（Documents）** | 浏览已索引的文档类实体 |
| **`/indexing`** | **索引（Indexing）** | 触发**全量 / 增量**索引任务；查看任务队列与进度 |
| **`/wiki`** | **Wiki** | 完整 Wiki 体验：**目录树**（如 business_domain / code_structure 等视图）、正文阅读、**问答（SSE 流式）**、导出、Lint、**质量 / 覆盖率**、**业务流（xyflow）**、知识图谱视图、深度研究、反馈、**版本历史**、编辑与批注等（具体子功能依赖 `WIKI__*`、`LLM__*` 开关） |
| **`/pr-impact`** | **PR 影响（PR Impact）** | 基于变更文件的 PR 分析与 Wiki 侧影响评估 |
| **`/settings`** | **设置（Settings）** | 系统级配置：LLM Provider、嵌入、存储、Wiki 生成策略与功能开关等（权限多为 Admin） |
| **`/businesses`** | **业务空间（Businesses）** | **业务实体 CRUD**、为 Wiki **多租户**绑定仓库 |

**兼容跳转**：`/deep-search` → `/search`；`/graph` → `/explorer`。

---

## 功能速查：HTTP API 与权限角色

下列路径均以 **`/api/v1`** 为前缀（文中简写时已省略此前缀）。**角色含义**：部分路由标注 **Viewer / Editor / Admin / Open / Public**，与 RBAC 一致；精确行为以 OpenAPI / 路由装饰器为准。

### 索引（Indexing）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/index` | POST | **Editor** | 全量或增量索引；请求体支持 **`directory`** 或 **`git_url`**、`repository`、`mode`（`full` / `incremental`）等 |
| `/api/v1/reindex/all` | POST | **Editor** | 对已登记仓库批量重新索引 |
| `/api/v1/enrich` | POST | **Editor** | LLM / 管线层面的丰富化（与 Wiki、架构分类等能力联动） |
| `/api/v1/index/files` | POST | **Editor** | 针对指定文件的索引更新 |
| `/api/v1/index/tasks`、`/api/v1/index/tasks/{task_id}` | GET | **Viewer**（任务列表按实现为准） | 查询索引任务状态；首次索引后轮询直至 `completed` / `failed` |

### 搜索（Search）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/hybrid` | POST | **Viewer** | **混合搜索**主入口：语义 + 关键词 + BM25、RRF、分页、排序、跨仓参数等 |
| `/api/v1/deep-search` | POST | **Viewer** | 多步 **LLM 推理**式深度检索（需可用 LLM 配置） |
| `/api/v1/deep-search/stream` | POST | **Viewer** | 深度搜索 **SSE 流式**输出 |
| `/api/v1/search/architecture` | GET | **Viewer** | **架构检索**（分层、端点等问题优先使用） |

### 图谱（Graph）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/graph/explore` | POST | **Viewer** | 图谱节点探索（与仪表盘 Explorer 联动） |
| `/api/v1/graph/expand` | POST | **Viewer** | 展开节点邻居 |
| `/api/v1/graph/blast-radius` | POST | **Viewer** | **变更影响**分析 |
| `/api/v1/graph/communities` | GET | **Viewer** | **社区发现**结果 |

### 文件（Files）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/files/tree` | GET | **Viewer** | 目录树（通常需 **`repository`** 查询参数） |
| `/api/v1/files/content` | GET | **Viewer** | 文件正文 |
| `/api/v1/files/entities` | GET | **Viewer** | 文件内解析出的实体 |

### Wiki — 生成与任务

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/wiki/generate` | POST | **Viewer**（按部署策略） | 单仓库 Wiki 生成 |
| `/api/v1/wiki/business/generate` | POST | **Editor** | **跨仓业务 Wiki**；通常返回 **202** 与 **`task_id`** |
| `/api/v1/wiki/business/tasks/{task_id}` | GET | **Viewer** | 查询异步任务进度 |
| `/api/v1/wiki/generate-incremental` | POST | **Viewer**（按部署策略） | 增量 Wiki 生成 |

### Wiki — 浏览与检索

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/wiki/tree` | GET | **Viewer** | Wiki 目录树（参数含 `business_id`、`view`、`wiki_tier` 等） |
| `/api/v1/wiki/search` | POST | **Viewer** | Wiki 内搜索 |
| `/api/v1/wiki/search/global` | POST | **Viewer** | 全局 Wiki 搜索 |
| `/api/v1/wiki/pages/by-path` | GET | **Viewer** | 按路径解析页面 |
| `/api/v1/wiki/{repo}/pages/{path}` | GET | **Viewer** | 按仓库与路径读取页面内容 |
| `/api/v1/wiki/pages/{uid}/versions` | GET | **Viewer** | **版本历史** |
| `/api/v1/wiki/pages/{uid}/diff` | GET | **Viewer** | 版本 **diff** |
| `/api/v1/wiki/pages/{uid}/references` | GET | **Viewer** | **引用关系图** |

### Wiki — 问答与研究

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/wiki/ask/stream` | POST | **Viewer** | **SSE 流式**问答 |
| `/api/v1/wiki/research` | POST | **Viewer** | **深度研究**（通常需 **`WIKI__DEEP_RESEARCH_ENABLED`**） |
| `/api/v1/wiki/pages/{uid}/questions` | GET | **Viewer** | 页面关联的推荐问题 |

### Wiki — 质量与一致性

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/wiki/quality-score` | GET | **Viewer** | 质量评分 |
| `/api/v1/wiki/coverage-report` | GET | **Viewer** | 覆盖率报告 |
| `/api/v1/wiki/contradictions` | GET | **Viewer** | 矛盾列表（依赖矛盾检测相关开关） |
| `/api/v1/wiki/pages/claim-history` | GET | **Viewer** | 主张历史（依赖 **`WIKI__SUPERSESSION_TRACKING_ENABLED`** 等） |

### Wiki — 导出与其它管线能力

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/wiki/export` | POST | **Editor** | 导出 Markdown / ZIP / Git / Obsidian / MkDocs 等 |
| `/api/v1/wiki/ingest` | POST | **Viewer** | **增量摄取**：按变更文件触发受影响 Wiki 页再生（请求体含 `repository`、`files` 或 `git_ref`） |
| `/api/v1/wiki/changelog` | GET | **Viewer** | **变更审计**：查询参数 `repository`、`limit` |
| `/api/v1/hooks/ingest/push` | POST | **Editor** | Push 风格载荷驱动 Wiki 增量（正文含 `repository` + `payload`）；另有 `/api/v1/hooks/{provider}` 等 Webhook，见 [DEPLOYMENT.md](DEPLOYMENT.md) |
| `/api/v1/wiki/flows` | GET | **Viewer** | 业务流数据（仪表盘 xyflow；参数含 `business_id`） |
| `/api/v1/wiki/pages/{page_uid}/feedback` 等 | POST/GET | 见 OpenAPI | **用户反馈**汇总与提交 |
| `/api/v1/wiki/merge-candidates` | GET | **Viewer** | 概念合并候选（需 **`WIKI__CONCEPT_MERGING_ENABLED`**） |

### 业务空间（Business）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/businesses` | GET | **Open**（按部署） | 列出业务空间 |
| `/api/v1/businesses` | POST | **Editor** | 创建业务 |
| `/api/v1/businesses/{id}/repositories` | PUT | **Editor** | **绑定仓库**（多租户 Wiki） |

### MCP（HTTP 兼容层）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/mcp/tools` | GET | **Viewer** | **22** 个主工具清单（**12** 核心图谱/检索 + **10** Wiki 管线） |
| `/api/v1/mcp/tool` | POST | **Viewer** | 调用单个工具：`{"tool_name":"...","arguments":{...}}` |
| `/api/v1/mcp/tools/list` | GET | **Viewer** | **可选**：Wiki 专用 **6** 工具清单（需 **`WIKI__MCP_SERVER_ENABLED`**） |
| `/api/v1/mcp/tools/call` | POST | **Viewer** | 调用 Wiki HTTP 工具：`{"name":"<tool>","arguments":{...}}`（字段名与主路由不同） |

### 运维与健康（Admin / Public）

| 端点 | 方法 | 典型角色 | 说明 |
|------|------|----------|------|
| `/api/v1/health` | GET | **Public** | 健康检查（含 FalkorDB 等依赖状态） |
| `/api/v1/auth/me` | GET | **Public**（携带令牌时返回角色） | 当前认证信息 |
| `/api/v1/settings` | GET/PUT | **Admin** | 系统设置读写 |
| 同步计划、`sync/repo`、清理、`backfill-fqn` 等 | - | **Admin** | 详见 OpenAPI 与管理路由文档 |

---

## 索引你的第一个仓库

有三种常见方式：**本地目录**、**Git URL**、**仪表盘「索引」页面**（底层同样调用索引 API）。

### 方式 A：本地目录（HTTP API）

使用具备 **Editor** 权限的 Token，调用：

**`POST /api/v1/index`**

```json
{
  "directory": "/absolute/path/to/repo",
  "repository": "my-repo",
  "mode": "full"
}
```

响应通常包含 **`task_id`**。轮询 **`GET /api/v1/index/tasks/{task_id}`**，直到状态为 `completed` 或 `failed`。

### 方式 B：Git URL（HTTP API）

配置 **`GIT__GITLAB_URL`** / **`GIT__GITLAB_TOKEN`**（或 GitHub Token、SSH 等，见 [DEPLOYMENT.md](DEPLOYMENT.md)），请求体示例：

```json
{
  "git_url": "https://gitlab.example.com/group/myproject.git",
  "branch": "main",
  "repository": "myproject",
  "mode": "full"
}
```

服务会在 **`GIT__CLONE_BASE_PATH`** 下克隆（或更新）并索引检出内容。

### 方式 C：通过仪表盘

打开 **`/indexing`**，按界面指引填写仓库标识与路径或远程地址，提交任务后与方式 A/B 相同关注任务进度。

### 与 MCP 的关系（重要）

服务端内部存在与索引相关的处理器，但 **`rag_index` 并未列入对外 MCP 工具清单**（主清单面向查询与 Wiki 操作为主）。**Agent 若仅通过 MCP，无法用名为 `rag_index` 的工具触发索引**；请使用 **`POST /api/v1/index`**（Editor）或其它索引 HTTP API。

---

## 搜索技巧

- **写明具体标识符**：查询中包含精确的类名、函数名或路径片段时，有利于关键词通道与 **BM25** 排序，RRF 会放大高质量字面匹配。
- **收窄仓库与语言**：使用 `repository`、`language`（以及实体类型过滤）降低跨仓噪声。
- **大文件场景**：对照部署变量 **`HYBRID_SEARCH__USE_CHILD_CHUNKS`**，或在 MCP **`rag_query`** 中使用 **`use_child_chunks`**，以获取更细粒度分块命中。
- **架构类问题**：优先使用 **`GET /api/v1/search/architecture`** 或 MCP 中的 **`search_architecture`**（如 `mode: layers` / `endpoints`）。
- **废弃说明**：早期全局搜索端点已移除；统一使用 **`POST /api/v1/hybrid`**，并可借助 **`entity_type`** 检索 **`flow`、`concept`** 等业务实体。

---

## 与 AI Agent 集成（MCP）

推荐流程：

1. **准备 Token**  
   在 **`tokens.yaml`**（可参考仓库内 **`tokens.yaml.example`**）或环境变量 **`API_TOKEN` / `API_TOKENS`** 中创建 **`viewer`** 或 **`editor`** 令牌；请求头 **`Authorization: Bearer <token>`**。

2. **拉取主工具清单**  
   **`GET /api/v1/mcp/tools`** — 共 **22** 个工具（**12** 图谱与检索类 + **10** Wiki 管线类）。

3. **调用主工具**  
   **`POST /api/v1/mcp/tool`**，JSON：`{"tool_name":"<name>","arguments":{...}}`。  
   常用示例：**`rag_query`**（混合检索）、**`rag_graph`**（含 `call_chain`、`raw_cypher`、`blast_radius` 等 **`query_type`**）、**`get_file_content`**（读完整文件或行范围以避免片段长度限制）。

4. **可选：Wiki HTTP MCP（6 工具）**  
   设置 **`WIKI__MCP_SERVER_ENABLED=true`** 且 Wiki 已完成 bootstrap 后：**`GET /api/v1/mcp/tools/list`**，调用 **`POST /api/v1/mcp/tools/call`**，体为 **`{"name":"...","arguments":{...}}`**（字段名与主 MCP 路由不一致，详见 [MCP-INTEGRATION.md](MCP-INTEGRATION.md)）。

5. **多租户**  
   使用图或 Wiki 的租户语义时，在兼容接口上附加 **`X-Business-Id: <tenant>`**（须与令牌权限一致）。

完整工具说明、参数 Schema 与示例：[MCP-INTEGRATION.md](MCP-INTEGRATION.md)。

---

## 认证与安全快速参考

| 模式 | 行为 |
|------|------|
| **未配置 Token** | **开放访问**（开发便捷，**不适合生产**） |
| **`tokens.yaml` / 环境变量 Token** | 受保护路由需 **Bearer**；**Viewer / Editor / Admin** 分级访问 HTTP 与 MCP |
| **`REQUIRE_AUTH=true`** | **启动时若无可验证 Token 配置则失败**；未认证访问受保护路由返回拒绝 |
| **`KB_ENV=production`** | 触发 **`main.py`** 中的生产安全校验：强制 **`require_auth`** 且必须配置至少一种 API Token，否则拒绝启动 |

自检当前身份：**`GET /api/v1/auth/me`**。

---

## 延伸阅读

| 文档 | 内容 |
|------|------|
| [DEPLOYMENT.md](DEPLOYMENT.md) | 环境变量、FalkorDB、Git、Wiki 开关、生产 checklist |
| [MCP-INTEGRATION.md](MCP-INTEGRATION.md) | 22 + 6 工具详解、请求体示例、角色矩阵 |
| [wiki-generation-architecture.md](wiki-generation-architecture.md) | 跨仓业务 Wiki、`task_id`、增量语义 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 本地开发、测试命令、目录结构 |
