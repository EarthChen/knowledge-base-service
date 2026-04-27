# MCP 集成

服务通过 HTTP 暴露 **两种** MCP 风格契约（可并存）：

| 表面 | 列出 | 调用 | 工具数 |
|------|------|------|--------|
| **主服务 MCP** | `GET /api/v1/mcp/tools` | `POST /api/v1/mcp/tool`，体为 `{"tool_name":"...","arguments":{...}}` | **20**（`MCP_TOOLS_MANIFEST` 12 个 + `WIKI_MCP_TOOLS_MANIFEST` 8 个） |
| **Wiki 专用 MCP** | `GET /api/v1/mcp/tools/list` | `POST /api/v1/mcp/tools/call`，体为 `{"name":"...","arguments":{...}}` | **5**；仅当 `WIKI__MCP_SERVER_ENABLED=true` 且已 `bootstrap_wiki` 时可用 |

> 主清单在 `api/mcp_server.py` 末尾与 `wiki/mcp_tools.py` 的 `WIKI_MCP_TOOLS_MANIFEST` 合并；五工具定义在 `api/mcp_wiki_server.py` 的 `TOOL_DEFINITIONS`。

认证使用 `Authorization: Bearer <token>`。主 MCP 工具级角色在 `KnowledgeBaseMCPHandler.handle_tool_call` 经 `MCP_TOOL_MIN_ROLE` 校验；Wiki 五工具与主路由相同，默认 **Viewer**（以服务端实现为准）。

## 角色模型

| 角色 | HTTP / 含义 | MCP |
|------|-------------|-----|
| **VIEWER** | 只读 API 路由 | 除需要 Editor 的工具外，可调用主清单与 Wiki 五工具（若已启用） |
| **EDITOR** | 索引、写操作 | `wiki_export`（最低要求）；索引通过 HTTP API 触发，不暴露为 MCP 工具 |
| **ADMIN** | 业务管理、同步计划、破坏性操作 | MCP 无额外管理专用工具；用于 HTTP 管理路由 |

**需要 Editor（或更高角色）的 MCP 工具：** `wiki_export`。其余主清单与五工具在实现上为 **Viewer** 即可。

## 工具参考

### A. 主服务 MCP（20 个工具）

第 1–12 为图谱/检索类，第 13–20 为 Wiki 管线类（`wiki/mcp_tools.py`）。

#### 1. `rag_query`

| | |
|--|--|
| **描述** | 自然语言混合搜索：语义 + 关键词 + BM25 全文，RRF 三路融合，可选子块、图扩展。 |
| **最低角色** | Viewer |
| **参数** | `query`（string，**必填**）。`k`（int，默认 5）、`expand_depth`（int，默认 2）、`entity_type`（function / class / module / document / flow / concept）、`repository`（单仓过滤）、**`repositories`**（string[]，跨仓聚合搜索，最多 10 个；与 `repository` 互斥，优先级更高）、`language`、`use_child_chunks`（可选 bool；清单默认 false — 若**省略**该键，服务端使用 `HYBRID_SEARCH__USE_CHILD_CHUNKS` 默认 **true**）、`use_query_router`（bool，默认 true）、`use_query_expansion`（bool，默认 true）、`per_file_cap`（int，默认 3；MCP 层限制 1–20）、`offset`（int，默认 0，分页偏移）、`enable_bm25`（bool，默认 true，是否启用 BM25 全文搜索路径）。 |

**示例（单仓搜索）**

```json
{
  "tool_name": "rag_query",
  "arguments": {
    "query": "OAuth token 刷新在哪里处理？",
    "k": 8,
    "expand_depth": 2,
    "repository": "my-service",
    "per_file_cap": 3
  }
}
```

**示例（跨仓聚合搜索）**

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

#### 2. `rag_graph`

| | |
|--|--|
| **描述** | 基于 Cypher 的结构化图操作。 |
| **最低角色** | Viewer |
| **参数** | `query_type`（**必填**）：`call_chain`、`inheritance_tree`、`class_methods`、`module_dependencies`、`reverse_dependencies`、`find_entity`、`file_entities`、`graph_stats`、`raw_cypher`、`business_flow`、`flows_for_function`、`related_concepts`、`explore_domain`、`flow_dependencies`、**`blast_radius`**。可选：`name`、`file`、`depth`（默认 3）、`direction`（默认 `downstream`）、`cypher`（用于 `raw_cypher`）、`entity_type`（用于 `find_entity`）、`repository`。`blast_radius`：`names`、`depth`（1–5，默认 3）、`repository`。 |

**示例（调用链）**

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

**示例（Blast Radius）**

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

#### 3. `documents`

| | |
|--|--|
| **描述** | 不带 `uid`：列出文档节点及段落；带 `uid`：获取完整文档。 |
| **最低角色** | Viewer |
| **参数** | `uid`（可选）、`repository`（列表时可选过滤）。 |

#### 4. `get_code_snippet`

| | |
|--|--|
| **描述** | 获取 Function 或 Class `uid` 的存储代码片段/元数据。 |
| **最低角色** | Viewer |
| **参数** | `node_uid`（**必填**）。 |

#### 5. `get_file_content`

| | |
|--|--|
| **描述** | 从已索引仓库的磁盘检出读取**原始源文件**全文或行范围；用于规避 `get_code_snippet` 等路径上约 **5000 字符**截断导致的上下文缺失。 |
| **最低角色** | Viewer |
| **参数** | 见下表。 |

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `repository` | string | 是 | 索引时登记的仓库名 |
| `file_path` | string | 是 | 仓库内相对路径（禁止绝对路径与 `..` 路径穿越） |
| `start_line` | int | 否 | 起始行号（**1-based**，含）；省略则从文件开头 |
| `end_line` | int | 否 | 结束行号（**1-based**，含）；省略则读到末尾 |

路径经规范化后须落在仓库根内；检出路径异常时拒绝。二进制文件（内容探测含 `\x00`）拒绝读取。单次读取上限 **512KB**，超出截断并在响应中带 `truncated: true` 警告。

#### 6. `analyze_code`

| | |
|--|--|
| **描述** | `quality`：单个实体的启发式质量评分；`consistency`：仓库级索引 vs 磁盘一致性检查。 |
| **最低角色** | Viewer |
| **参数** | `mode`：`quality` \| `consistency`（默认 `quality`）。quality 模式：`entity_uid`，可选 `entity_type`。consistency 模式：`repository`。 |

#### 7. `search_architecture`

| | |
|--|--|
| **描述** | `layers`：按架构层分类的类列表；`endpoints`：HTTP/RPC/Kafka 风格端点。 |
| **最低角色** | Viewer |
| **参数** | `mode`：`layers` \| `endpoints`。`layers` 模式：`layer`（**必填**，枚举：presentation、business、data_access、rpc、messaging、infrastructure、model、unknown），可选 `repository`、`limit`、`offset`、`search`。`endpoints` 模式：可选 `repository`。 |

#### 8. `analyze_changes`

| | |
|--|--|
| **描述** | `pr_review`、`impact`、`impact_scope`、`wiki_pr_impact` 等变更分析模式。 |
| **最低角色** | Viewer |
| **参数** | `mode`（**必填**）。各模式特定参数：参见清单（diff/branch/repo_path、`changed_functions`、`node_name`、`changed_files` 等）。 |

#### 9. `get_complete_context`

| | |
|--|--|
| **描述** | 为实体组装完整上下文：代码片段、文档字符串、邻居、Wiki 关联，按 Token 预算裁剪。 |
| **最低角色** | Viewer |
| **参数** | `entity_name`（**必填**），可选 `repository`、`max_tokens`（默认 8000）。 |

#### 10. `get_insights`

| | |
|--|--|
| **描述** | `dashboard`：全局 P2 统计；`graph`：仓库异常分析；`all`：两者合并（需 `repository`）。 |
| **最低角色** | Viewer |
| **参数** | `type`：`dashboard` \| `graph` \| `all`（默认 `dashboard`），`repository`（`graph` / `all` 必填）。 |

#### 11. `index_freshness`

| | |
|--|--|
| **描述** | 查询仓库的最新 `indexed_at`、节点计数和可选 `commit_sha`。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）。 |

#### 12. `graph_path`

| | |
|--|--|
| **描述** | 在仓库内，沿 `CALLS`、`INHERITS`、`IMPORTS` 边查找两个具名代码实体（Function/Class/Module）之间的**最短路径**（有深度上限）。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）、`from_entity`（**必填**，起点名称或 FQN）、`to_entity`（**必填**，终点名称或 FQN）、`max_depth`（int，默认 5，服务端限制 1–8）。 |

#### 13. `get_wiki_page`

| | |
|--|--|
| **描述** | 按作用域获取一个生成的 Wiki 页面。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）、`scope`（**必填**，如 `module:path` 或 `class:fqn`）。 |

#### 14. `list_wiki_pages`

| | |
|--|--|
| **描述** | 获取 Wiki 页面的树形结构及元数据。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**），可选 `scope` 子树过滤。 |

#### 15. `search_wiki`

| | |
|--|--|
| **描述** | 混合 Wiki 搜索（图 + 向量 + 全文）。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）、`query`（**必填**）、`mode`（`hybrid` 默认 / `graph` / `semantic` / `keyword`）、`limit`、`min_score`，可选 `scope`。 |

#### 16. `wiki_export`

| | |
|--|--|
| **描述** | 将生成的 Markdown 文件写入 `target_dir`；跳过不含 AUTO-GENERATED 标记的人工文件。 |
| **最低角色** | **Editor** |
| **参数** | `repository`（**必填**）、`target_dir`（**必填**），可选 `selected_files`（路径数组）。 |

#### 17. `wiki_get_tree`

| | |
|--|--|
| **描述** | 按业务与视图拉取 Wiki 树（`business_domain` / `code_structure`），与 `GET /api/v1/wiki/tree` 同数据源。 |
| **最低角色** | Viewer |
| **参数** | `business_id`（默认 `default`）、`view`（枚举，默认 `business_domain`）。 |

#### 18. `wiki_get_related`

| | |
|--|--|
| **描述** | 某 Wiki 页的出链与反向交叉引用。 |
| **最低角色** | Viewer |
| **参数** | `page_uid`（**必填**，如 `WikiPage:repo:path`）。 |

#### 19. `wiki_get_domain_overview`

| | |
|--|--|
| **描述** | 指定业务域的域总览页内容/元数据。 |
| **最低角色** | Viewer |
| **参数** | `domain_name`（**必填**）、`business_id`（默认 `default`）。 |

#### 20. `wiki_get_snapshot`

| | |
|--|--|
| **描述** | 获取某仓库下全部 Wiki 页的**编译快照**：结构化 Markdown，含页摘要、置信度、交叉引用与模块组织。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）。 |

### B. Wiki 专用 MCP（5 个工具，`WIKI__MCP_SERVER_ENABLED=true`）

**列出**：`GET /api/v1/mcp/tools/list` → `{"tools":[...]}`。**调用**：`POST /api/v1/mcp/tools/call`，体为 `{"name":"<工具名>","arguments":{...}}`；成功响应包在 `content[0].text` 的 JSON 字符串中（与 MCP 内容块约定一致）。

| 工具 | 作用 | 主要参数（摘录） |
|------|------|------------------|
| `wiki_search` | Wiki/知识混合检索 | `query`（必填），`repository` 可选，`limit` 默认 5 |
| `wiki_explain` | 针对某实体生成结构化说明 | `entity`、`repository`（均必填） |
| `wiki_navigate` | 浏览 Wiki 树 | `repository`（必填），`path` 默认 `/` |
| `wiki_qa` | 基于 wiki 的问答 | `question`、`repository`（均必填） |
| `wiki_impact` | 文件变更对 Wiki/实体的影响 | `files`（路径数组）、`repository`（均必填） |

> 五工具由 `MCPWikiServer` 将请求委托给 `WikiSearchService` / `WikiStore` / `WikiAskService` / `ChangeDetector`；未启用时上述端点返回 503（`MCP server not configured`）。

---

## Agent 集成模式

1. **发现** — 主 MCP：`GET /api/v1/mcp/tools`；若启用 Wiki MCP，再调 `GET /api/v1/mcp/tools/list` 合并本地缓存。
2. **搜索后深入** — `rag_query` → 选取 `uid` → `get_code_snippet`；长文件用 **`get_file_content`**；图关系用 **`rag_graph`**。启用五工具时可用 **`wiki_search`** / **`wiki_explain`** 替代或补充主清单中的 `search_wiki` / 页面拉取组合。
3. **Wiki 管线** — `list_wiki_pages` → `get_wiki_page` 或 `search_wiki`；或五工具 path：`wiki_navigate` → `wiki_qa`；导出仍需 **`wiki_export`**（Editor）或 HTTP `POST /api/v1/wiki/export`。

> **注意**：索引操作（全量 / 增量）通过 Dashboard 或 HTTP API 端点触发，不暴露为 MCP 工具。

使用请求头 **`X-Business-Id`**（默认 `default`）在多租户图隔离场景下选择目标图（`auth.resolve_business_id`）。
