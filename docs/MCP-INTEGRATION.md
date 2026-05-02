# MCP 集成参考（Knowledge Base Service）

本文档描述知识库服务暴露的 **模型上下文协议（MCP）风格 HTTP 契约**：**主服务 MCP**（图谱 + RAG + Wiki 合并清单）与 **可选的 Wiki 专用 HTTP MCP**（六工具、独立路径与请求体字段名）。内容与下列源码保持一致并保持可追溯：

- 主清单与核心处理器：`api/mcp_server.py`（`MCP_TOOLS_MANIFEST` + `WIKI_MCP_TOOLS_MANIFEST`）
- Wiki 清单与处理器：`wiki/mcp_tools.py`（`WIKI_MCP_TOOLS_MANIFEST`、`WikiMCPHandler`）
- 工具注册与最低角色：`api/mcp_registry.py`（`@mcp_tool`、`collect_tools`）
- Wiki HTTP 六工具：`api/mcp_wiki_server.py`（`TOOL_DEFINITIONS`、`MCPWikiServer`）

---

## 目录

1. [两种 MCP 表面](#两种-mcp-表面)
2. [认证与多租户](#认证与多租户)
3. [角色模型与工具权限](#角色模型与工具权限)
4. [响应与错误格式](#响应与错误格式)
5. [A. 主 MCP — 22 个工具（完整参数）](#a-主-mcp--22-个工具完整参数)
6. [B. Wiki HTTP MCP — 6 个工具（可选）](#b-wiki-http-mcp--6-个工具可选)
7. [Agent 集成建议](#agent-集成建议)

---

## 两种 MCP 表面

| 表面 | 列出工具 | 调用工具 | 工具数量 | 说明 |
|------|----------|----------|----------|------|
| **主 MCP** | `GET /api/v1/mcp/tools` | `POST /api/v1/mcp/tool`，请求体：`{"tool_name":"<名称>","arguments":{...}}` | **22**（核心 **12** + Wiki 清单 **10**） | 随主应用始终挂载（处理器依赖存储/Wiki/RAG 等运行时配置；部分工具在未配置时会返回 `service_unavailable` / `not_configured`） |
| **Wiki HTTP MCP** | `GET /api/v1/mcp/tools/list` | `POST /api/v1/mcp/tools/call`，请求体：`{"name":"<名称>","arguments":{...}}` | **6** | 需环境变量 **`WIKI__MCP_SERVER_ENABLED=true`**，且应用启动时已装配 `app.state.mcp_wiki_server`；未配置时路由返回 **503**（`MCP server not configured`） |

**字段名差异（重要）：** 主 MCP 使用 **`tool_name`**；Wiki HTTP MCP 使用 **`name`**。二者 **不是** 同一请求体的别名。

**与完整 Wiki REST 的关系：** Wiki HTTP MCP 将请求委托给 `WikiSearchService` / `WikiStore` / `WikiAskService` / `ChangeDetector` / `WikiCompilationSnapshot` 等；与 `/api/v1/wiki/*` 能力互补，工具集合与主清单 **不重复计数**。

---

## 认证与多租户

| 项目 | 说明 |
|------|------|
| **Authorization** | `Authorization: Bearer <token>`（若部署启用 `require_auth` / 配置了令牌） |
| **业务隔离** | 请求头 **`X-Business-Id`**：多租户下图谱/Wiki 等业务范围解析（内部经 `auth.resolve_business_id`）；省略时通常为默认业务 |
| **索引** | **全量/增量索引仅通过 HTTP API**（例如 `POST /api/v1/index` 及 Dashboard），**不作为 MCP 工具暴露**（代码中存在内部索引方法，但不在对外 MCP 清单中） |

---

## 角色模型与工具权限

`Role` 为整型枚举（见 `auth.py`）：**VIEWER = 1**，**EDITOR = 2**，**ADMIN = 3**。

| 角色 | HTTP 典型能力 | MCP |
|------|----------------|-----|
| **VIEWER** | 只读查询类路由 | 可使用除 **`wiki_export`** 外的全部主清单工具；Wiki HTTP 六工具在启用时默认亦按 Viewer 可用 |
| **EDITOR** | 索引、写入类操作 | 额外允许 **`wiki_export`**（`@mcp_tool(..., min_role=Role.EDITOR)`） |
| **ADMIN** | 业务管理、同步计划、破坏性运维 | **无**单独「仅 Admin」的 MCP 工具；Admin 令牌用于 HTTP 管理面 |

** elevated 工具汇总：** 仅 **`wiki_export`** 要求不低于 **EDITOR**；其余主清单工具默认 **VIEWER**。`collect_tools()` 将 `@mcp_tool` 装饰的方法汇入分派表；`wiki_search` 在运行时分派表中额外注册别名 **`search_wiki`**（见下方工具表）。

---

## 响应与错误格式

### 主 MCP（`POST /api/v1/mcp/tool`）

- **成功：** 返回 **业务 JSON 对象**（工具各异，无统一 envelope）。
- **失败：** 常见形如：

```json
{
  "error": {
    "code": "forbidden | unknown_tool | invalid_params | not_found | internal_error | ...",
    "message": "人类可读说明"
  }
}
```

若启用认证且令牌角色不足，将对 elevated 工具返回 **`forbidden`**。未认证且配置要求认证时，对需高于 Viewer 的工具同样可能返回 **`forbidden`**。

### Wiki HTTP MCP（`POST /api/v1/mcp/tools/call`）

- **HTTP 200** 时 body 通常为 MCP 风格内容块：**成功负载序列化在 `content[0].text` 的 JSON 字符串中**：

```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"answer\":\"...\",\"conversation_id\":\"...\"}"
    }
  ]
}
```

- 服务端内部错误可能返回带 `error` 键的对象（部分处理器返回字符串 `error` 字段）；客户端应对 **`text` 内 JSON** 与 **顶层错误** 两种形态都做解析。

### `GET …/tools` / `GET …/tools/list`

- 主 MCP：`GET /api/v1/mcp/tools` → **JSON 数组**，每项含 MCP 工具的 `name`、`description`、`inputSchema`（JSON Schema 子集）。
- Wiki HTTP：`GET /api/v1/mcp/tools/list` → `{"tools": [ ... ]}`，元素结构同上。

---

## A. 主 MCP — 22 个工具（完整参数）

下列顺序与 **`MCP_TOOLS_MANIFEST`** 合并 **`WIKI_MCP_TOOLS_MANIFEST`** 后的清单顺序一致（核心 12 → Wiki 10）。

**表列说明：**「必填」指运行时校验或业务上必须提供；「默认」取自清单 `default` 或服务端代码在未传参时的行为；约束列出自 `handle_*` 与下游服务。

---

### 1. `rag_query`（Viewer）

**说明：** 自然语言混合检索（语义 + 图扩展等）；可选 BM25、查询路由、查询扩展、子块向量等。开启重排序可通过环境变量 `RERANK__ENABLED=true`（见清单描述）。

| 参数 | 类型 | 必填 | 默认 | 约束 / 说明 |
|------|------|------|------|-------------|
| `query` | string | **是** | — | 自然语言问题 |
| `k` | integer | 否 | `5` | 服务端 clamp：**1–50** |
| `expand_depth` | integer | 否 | `2` | **0–5** |
| `entity_type` | string | 否 | — | **`function`** \| **`class`** \| **`module`** \| **`document`** \| **`flow`** \| **`concept`**；`flow`/`concept` 走业务实体搜索分支 |
| `repository` | string | 否 | — | 单仓过滤；与 `repositories` 二选一语义：见下 |
| `repositories` | string[] | 否 | — | **跨仓**检索，最多 **10** 个非空字符串；若长度 ≥2 则启用多仓融合；长度为 1 时退化为单仓名 |
| `language` | string | 否 | — | 如 `python`、`java`、`go`、`javascript`、`typescript` |
| `use_child_chunks` | boolean | 否 | 清单默认 `false` | **若请求体省略该键**，服务端不传覆盖，底层默认遵循配置 **`HYBRID_SEARCH__USE_CHILD_CHUNKS`**（常为 **true**）；若显式传入则按布尔值生效 |
| `use_query_router` | boolean | 否 | `true` | 意图感知关键词/语义权重路由 |
| `use_query_expansion` | boolean | 否 | `true` | 基于图邻居的查询扩展 |
| `per_file_cap` | integer | 否 | `3` | **仅当键存在时**参与 hybrid：服务端 clamp **1–20** |
| `offset` | integer | 否 | `0` | 分页偏移，**≥0** |
| `enable_bm25` | boolean | 否 | `true` | 是否并入 BM25 全文路径 |

**请求示例（单仓）：**

```json
{
  "tool_name": "rag_query",
  "arguments": {
    "query": "OAuth token 刷新在哪里处理？",
    "k": 8,
    "repository": "my-service",
    "per_file_cap": 3,
    "offset": 0
  }
}
```

**请求示例（跨仓）：**

```json
{
  "tool_name": "rag_query",
  "arguments": {
    "query": "用户认证流程",
    "k": 10,
    "repositories": ["auth-service", "gateway-service", "user-service"]
  }
}
```

---

### 2. `rag_graph`（Viewer）

**说明：** 结构化图查询（Cypher 或封装查询）。`raw_cypher` **只读**（含变更关键字的语句会被拒绝）。

| 参数 | 类型 | 必填 | 默认 | 约束 / 说明 |
|------|------|------|------|-------------|
| `query_type` | string | **是** | — | 枚举见下表 |
| `name` | string | 视类型 | `""` | 多数查询的目标实体名；**`blast_radius`** 可与 `names` 二选一，或将逗号分隔多名称填在本字段 |
| `file` | string | `file_entities` 需要 | — | 文件路径 |
| `depth` | integer | 否 | `3` | 通用遍历：**1–10**；**`blast_radius` 单独限制为 1–5** |
| `direction` | string | 否 | `downstream` | **`upstream`** \| **`downstream`** \| **`children`** \| **`parents`**（调用链 / 继承树等） |
| `cypher` | string | `raw_cypher` 需要 | — | 只读 Cypher |
| `entity_type` | string | 否 | `any` | **`function`** \| **`class`** \| **`any`**（用于 `find_entity`） |
| `names` | string[] | `blast_radius` 推荐 | — | 爆炸半径分析的多实体名 |
| `repository` | string | 否 | — | 仓库范围；**`blast_radius`** 等过滤遍历建议使用 |

**`query_type` 完整枚举：**

`call_chain`，`inheritance_tree`，`class_methods`，`module_dependencies`，`reverse_dependencies`，`find_entity`，`file_entities`，`graph_stats`，`raw_cypher`，`business_flow`，`flows_for_function`，`related_concepts`，`explore_domain`，`flow_dependencies`，`blast_radius`。

**示例（调用链）：**

```json
{
  "tool_name": "rag_graph",
  "arguments": {
    "query_type": "call_chain",
    "name": "handleRequest",
    "depth": 3,
    "direction": "downstream"
  }
}
```

**示例（爆炸半径）：**

```json
{
  "tool_name": "rag_graph",
  "arguments": {
    "query_type": "blast_radius",
    "names": ["handleRequest", "UserService"],
    "depth": 3,
    "repository": "my-service"
  }
}
```

---

### 3. `documents`（Viewer）

**说明：** 无 `uid` 时列出文档节点及章节元数据；有 `uid` 时返回该文档全文结构（章节内容）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `uid` | string | 否 | — | 文档节点 uid；提供则等价于内部按 `doc_uid` 取单篇 |
| `repository` | string | 否 | — | 列表模式下按仓库过滤 |

---

### 4. `get_code_snippet`（Viewer）

**说明：** 按图节点 uid 读取已入库的函数/类代码片段及元数据（适合接在 `rag_query` 结果之后）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_uid` | string | **是** | 图谱节点 uid |

---

### 5. `analyze_code`（Viewer）

**说明：** `quality`：单实体启发式质量分；`consistency`：索引与磁盘一致性（幽灵/缺失节点）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `mode` | string | 否 | `quality` | **`quality`** \| **`consistency`** |
| `entity_uid` | string | `quality` 需要 | — | 图谱 uid |
| `entity_type` | string | 否 | — | **`function`** \| **`class`**（可选提示） |
| `repository` | string | `consistency` 需要 | — | 仓库名 |

---

### 6. `search_architecture`（Viewer）

**说明：** `layers`：按架构分层检索类；`endpoints`：HTTP/RPC/Kafka 等端点发现。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `mode` | string | 否 | `layers` | **`layers`** \| **`endpoints`** |
| `layer` | string | **`layers` 必填** | — | 枚举（与清单一致）：**`presentation`**，**`business`**，**`data_access`**，**`rpc`**，**`messaging`**，**`infrastructure`**，**`model`**，**`unknown`** |
| `repository` | string | 否 | — | 两种模式均可选过滤 |
| `limit` | integer | 否 | `50` | `layers`：**1–500** |
| `offset` | integer | 否 | `0` | `layers`，**≥0** |
| `search` | string | 否 | — | `layers`：类名子串（大小写不敏感），需通过服务端校验 |

---

### 7. `analyze_changes`（Viewer）

**说明：** 变更影响与 PR 上下文；部分模式委托 Wiki/图遍历。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `mode` | string | **是** | — | **`pr_review`** \| **`impact`** \| **`impact_scope`** \| **`wiki_pr_impact`** |
| `diff_text` | string | `pr_review` 条件 | — | 统一 diff；与 `branch`+`repo_path` **二选一** |
| `branch` | string | `pr_review` 条件 | — | 与 `repo_path` 同时提供时可替代 diff |
| `base_branch` | string | 否 | `master` | `pr_review` |
| `repo_path` | string | `pr_review` 条件 | — | **服务端本机**上的 Git 仓库路径 |
| `repo_url` | string | 否 | — | 可选远程 URL（格式校验 `looks_like_git_url`） |
| `repository` | string | 视模式 | — | 作用域；**`impact_scope` / `wiki_pr_impact` 在 Wiki 处理器中通常必填** |
| `max_depth` | integer | 否 | 清单 **3** | **`pr_review`** 默认 **3**；**`impact`** 分支代码默认 **5**（未传参时） |
| `changed_functions` | string[] | `impact` 需要 | — | 已修改函数名列表 |
| `node_name` | string | `impact_scope` 需要 | — | 目标函数/类/模块名或 FQN |
| `max_hops` | integer | 否 | `2` | `impact_scope`：Wiki 侧 clamp **1–3** |
| `changed_files` | object[] | `wiki_pr_impact` 需要 | — | 每项 **`path`**（string）、**`status`**（string）必填 |

**`pr_review` 约束：** 必须提供 **`diff_text`**，或 **同时**提供 **`branch`** 与 **`repo_path`**。

---

### 8. `get_complete_context`（Viewer）

**说明：** 单次组装实体上下文（片段、文档字符串、邻居、Wiki 等），按 token 预算裁剪。

| 参数 | 类型 | 必填 | 默认 | 约束 |
|------|------|------|------|------|
| `entity_name` | string | **是** | — | 函数/类名或可匹配子串 |
| `repository` | string | 否 | — | 限定仓库与 Wiki 查找 |
| `max_tokens` | integer | 否 | `8000` | 服务端 clamp：**256–100000** |

---

### 9. `get_insights`（Viewer）

**说明：** 仪表盘全局统计 / 单仓图异常洞察 / 二者合并。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `type` | string | 否 | `dashboard` | **`dashboard`** \| **`graph`** \| **`all`** |
| `repository` | string | `graph` / `all` 需要 | — | 单仓洞察 |

---

### 10. `index_freshness`（Viewer）

**说明：** 仓库索引时间戳、节点计数、可选 `commit_sha` 等新鲜度信息。

| 参数 | 类型 | 必填 |
|------|------|------|
| `repository` | string | **是** |

---

### 11. `get_file_content`（Viewer）

**说明：** 从已索引仓库的 **磁盘检出**读取源文件全文或行范围；用于规避 `get_code_snippet` 等路径上的长度截断。二进制（探测到 `\x00`）拒绝；单次读取上限 **512KB**，超出截断并可能带 `truncated: true`。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repository` | string | **是** | 索引登记的仓库名 |
| `file_path` | string | **是** | 仓库内相对路径；禁止绝对路径与 `..` |
| `start_line` | integer | 否 | **1-based** 起始行（含） |
| `end_line` | integer | 否 | **1-based** 结束行（含） |

---

### 12. `graph_path`（Viewer）

**说明：** 在同一仓库内，沿 **`CALLS`**、**`INHERITS`**、**`IMPORTS`** 求两实体间最短路径（有深度上限）。

| 参数 | 类型 | 必填 | 默认 | 约束 |
|------|------|------|------|------|
| `repository` | string | **是** | — | |
| `from_entity` | string | **是** | — | 起点名称或 FQN |
| `to_entity` | string | **是** | — | 终点名称或 FQN |
| `max_depth` | integer | 否 | `5` | 底层 clamp：**1–8** |

---

### 13. `get_wiki_page`（Viewer）

**说明：** 按 scope 读取生成中的 Wiki 页（若 Wiki 管线未配置则 `service_unavailable`）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repository` | string | **是** | 仓库标识 |
| `scope` | string | **是** | 如 **`module:<path>`** 或 **`class:<fqn>`**（需能通过 `parse_scope`） |

---

### 14. `list_wiki_pages`（Viewer）

**说明：** Wiki 页面目录树 + 元数据；可选子树过滤。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repository` | string | **是** | |
| `scope` | string | 否 | `repo`、`module:...`、`class:...` 等；无效 scope 返回 `invalid_scope` |

---

### 15. `wiki_search`（Viewer）

**别名：** **`search_wiki`**（同一处理器，仅为兼容旧客户端）。

**说明：** Wiki 混合检索（图 + 向量 + 全文）。若传入 `page_context` 且未显式传 `scope`，服务端会将 `scope_filter` 默认设为该页路径以增强上下文。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `repository` | string | **是** | — | |
| `query` | string | **是** | — | |
| `mode` | string | 否 | `hybrid` | **`hybrid`** \| **`graph`** \| **`semantic`** \| **`keyword`** |
| `limit` | integer | 否 | `10` | |
| `min_score` | number | 否 | `0.0` | 阈值 **0.0–1.0** |
| `scope` | string | 否 | — | 路径前缀 / 子树过滤 |
| `page_context` | string | 否 | — | 可选：提升关联页上下文 |

---

### 16. `unified_knowledge_query`（Viewer）

**说明：** 通过 **IterativeRAGEngine** 统一 Wiki + 代码问答；未装配 `rag_engine` 时返回 **`not_configured`**。

**清单内 Schema：**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `question` | string | **是** | — | |
| `scope` | string | 否 | `global` | **`global`** \| **`page`** \| **`business`** \| **`repository`** |
| `repository` | string | 否 | — | `repository` 等作用域需要 |
| `max_rounds` | integer | 否 | `5` | 迭代轮数 |

**运行时代码额外接受（未写入清单 JSON Schema，但处理器会读取）：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `business_id` | string | `business` 等作用域 |
| `page_path` | string | `page` 等作用域 |

**作用域归一化提示：** 若 `scope` 为 `global` 但提供了 `repository`，运行时会升为 **`repository`**；`repository` 作用域缺仓库名时会退回 **`global`**；`business` 缺少 `business_id` 时退回 **`global`**。

---

### 17. `wiki_export`（EDITOR）

**说明：** 将生成的 Markdown 写入 **`target_dir`**；跳过缺少 AUTO-GENERATED 标记的人工文件；依赖 Wiki 缓存配置。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repository` | string | **是** | |
| `target_dir` | string | **是** | 输出目录 |
| `selected_files` | string[] | 否 | 要写入的 Wiki 路径列表；省略表示待处理的全部创建/更新 |

---

### 18. `wiki_get_tree`（Viewer）

**说明：** 业务 Wiki 树（与 `GET /api/v1/wiki/tree` 同源思路）；依赖图存储。

| 参数 | 类型 | 必填 | 默认 | 枚举 |
|------|------|------|------|------|
| `business_id` | string | 否 | `default` | |
| `view` | string | 否 | `business_domain` | **`business_domain`** \| **`code_structure`** |

---

### 19. `wiki_get_related`（Viewer）

**说明：** 指定 Wiki 页的出链与反向引用。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page_uid` | string | **是** | 如 **`WikiPage:repo:path`** |

---

### 20. `wiki_get_domain_overview`（Viewer）

**说明：** 读取业务域总览页（内部路径形如 `/<domain_name>/_overview`）。

| 参数 | 类型 | 必填 | 默认 |
|------|------|------|------|
| `domain_name` | string | **是** | — |
| `business_id` | string | 否 | `default` |

---

### 21. `wiki_get_snapshot`（Viewer）

**说明：** 某仓库全部 Wiki 页的 **编译快照** Markdown（摘要、置信度、交叉引用、模块组织等）。

| 参数 | 类型 | 必填 |
|------|------|------|
| `repository` | string | **是** |

---

### 22. `wiki_find_implementing_modules`（Viewer）

**说明：** 从业务域/能力反查实现模块及 Wiki 路径。

| 参数 | 类型 | 必填 | 默认 |
|------|------|------|------|
| `domain_name` | string | **是** | — |
| `business_id` | string | 否 | `default` |

---

## B. Wiki HTTP MCP — 6 个工具（可选）

**前置：** `WIKI__MCP_SERVER_ENABLED=true`，且应用已挂载 `mcp_wiki_http_router`（`/api/v1/mcp` 前缀）。

| 操作 | 方法与路径 |
|------|------------|
| 列出 | `GET /api/v1/mcp/tools/list` → `{"tools":[ ... ]}` |
| 调用 | `POST /api/v1/mcp/tools/call` → body：`{"name":"<tool>","arguments":{...}}` |

成功时工具结果通常在 **`content[0].text`** 的 JSON 字符串中（见上文）。

---

### B1. `wiki_search`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `query` | string | **是** | — | |
| `repository` | string | 否 | `""` | 可选仓库过滤 |
| `limit` | integer | 否 | `5` | 返回条数上限 |

**实现备注：** 内部以 `mode="hybrid"`、`min_score=0.0` 调用搜索服务。

---

### B2. `wiki_explain`

| 参数 | 类型 | 必填 |
|------|------|------|
| `entity` | string | **是** |
| `repository` | string | **是** |

---

### B3. `wiki_navigate`

| 参数 | 类型 | 必填 | 默认 |
|------|------|------|------|
| `path` | string | 否 | `/` |
| `repository` | string | **是** | |

**返回：** 满足 `WikiPage.path STARTS WITH prefix` 的最多 50 条路径概要。

---

### B4. `wiki_qa`

| 参数 | 类型 | 必填 |
|------|------|------|
| `question` | string | **是** |
| `repository` | string | **是** |

**运行时额外参数（未出现在 `TOOL_DEFINITIONS`，但 `_handle_wiki_qa` 读取）：**

| 参数 | 类型 | 默认 |
|------|------|------|
| `business_id` | string | `default` |
| `scope` | string | `null`（可选） |

---

### B5. `wiki_impact`

| 参数 | 类型 | 必填 |
|------|------|------|
| `files` | string[] | **是** |
| `repository` | string | **是** |

---

### B6. `wiki_get_snapshot`

| 参数 | 类型 | 必填 |
|------|------|------|
| `repository` | string | **是** |

与主清单 **`wiki_get_snapshot`** 类似：编译快照 Markdown；实现路径均经由 `WikiCompilationSnapshot.generate("default", repo)`。

---

## Agent 集成建议

1. **发现工具**  
   - 启动时请求 **`GET /api/v1/mcp/tools`** 缓存 `name` → `inputSchema`。  
   - 若启用 Wiki HTTP MCP，再请求 **`GET /api/v1/mcp/tools/list`**，注意与主清单 **工具同名不同义** 的只有重叠名 **`wiki_search`** / **`wiki_get_snapshot`**：字段集与行为以各自 Schema 为准。

2. **调用约定**  
   - 始终携带 **`Authorization: Bearer`**（若环境要求）。  
   - 多租户场景携带 **`X-Business-Id`**。  
   - 主 MCP：**`tool_name`**；Wiki HTTP MCP：**`name`**。

3. **推荐工作流**  
   - **索引（HTTP）→ 检索（`rag_query`）→ 深入（`get_code_snippet` / `get_file_content`）→ 关系（`rag_graph` / `graph_path`）**。  
   - Wiki：**`list_wiki_pages` → `get_wiki_page`** 或 **`wiki_search`**；需要迭代综合问答时用 **`unified_knowledge_query`**（需 RAG 引擎可用）。  
   - 落地 Markdown 导出：**`wiki_export`**（需 **EDITOR**）或 HTTP **`POST /api/v1/wiki/export`**。

4. **索引不在 MCP**  
   再次强调：**建索引 / 增量更新仅能通过 HTTP（或控制台）触发**，Agent 自动化流水线应将索引步骤规划在 MCP 之外。

---

## 源码索引（维护者可跳转）

| 主题 | 位置 |
|------|------|
| 主清单 + 核心工具实现 | `api/mcp_server.py` |
| Wiki 清单 + `WikiMCPHandler` | `wiki/mcp_tools.py` |
| Wiki HTTP 六工具 | `api/mcp_wiki_server.py` |
| 路由：主 MCP | `api/routes/admin_graph_mcp_routes.py`（`POST /mcp/tool`，`GET /mcp/tools`） |
| 路由：Wiki HTTP MCP | `api/routes/wiki_mcp_routes.py`，挂载于 `api/routes/wiki_routes.py`（`/api/v1/mcp`） |
| 装饰器与角色 | `api/mcp_registry.py`，`auth.py`（`Role`） |
