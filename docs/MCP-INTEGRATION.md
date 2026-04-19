# MCP 集成

服务通过 HTTP 暴露 **MCP 风格**的工具契约：

- **列出工具**：`GET /api/v1/mcp/tools` — 返回与 `api/mcp_server.py` 中 `MCP_TOOLS_MANIFEST` 相同的清单（12 个基础工具 + 4 个 Wiki 工具 = **16 个**）。
- **调用工具**：`POST /api/v1/mcp/tool`，请求体为 JSON `{"tool_name": "...", "arguments": { ... }}`（参见 `main.py` 中的 `MCPToolCallRequest`）。

认证使用 `Authorization: Bearer <token>` 请求头（需配置 Token）。工具级角色检查在 `KnowledgeBaseMCPHandler.handle_tool_call` 中通过 `MCP_TOOL_MIN_ROLE` 实施。

## 角色模型

| 角色 | HTTP / 含义 | MCP |
|------|-------------|-----|
| **VIEWER** | 只读 API 路由 | 除需要 Editor 的工具外，可调用所有工具 |
| **EDITOR** | 索引、写操作 | `rag_index`、`wiki_export`（最低要求） |
| **ADMIN** | 业务管理、同步计划、破坏性操作 | MCP 无额外工具；用于 HTTP 管理路由 |

**需要 Editor（或更高角色）的 MCP 工具：** `rag_index`、`wiki_export`。其余所有工具仅需 **Viewer**。

## 工具参考（16 个工具）

以下 **inputSchema** 与 `api/mcp_server.py` 和 `wiki/mcp_tools.py` 中 `MCP_TOOLS_MANIFEST` / `WIKI_MCP_TOOLS_MANIFEST` 嵌入的 JSON Schema 一致。

### 1. `rag_query`

| | |
|--|--|
| **描述** | 自然语言混合搜索：语义 + 关键词，可选子块、RRF、图扩展。 |
| **最低角色** | Viewer |
| **参数** | `query`（string，**必填**）。`k`（int，默认 5）、`expand_depth`（int，默认 2）、`entity_type`（function / class / module / document / flow / concept）、`repository`、`language`、`use_child_chunks`（可选 bool；清单默认 false — 若**省略**该键，服务端使用 `HYBRID_SEARCH__USE_CHILD_CHUNKS` 默认 **true**）、`use_query_router`（bool，默认 true）、`use_query_expansion`（bool，默认 true）、`per_file_cap`（int，默认 3；MCP 层限制 1–20）。 |

**示例**

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

### 2. `rag_graph`

| | |
|--|--|
| **描述** | 基于 Cypher 的结构化图操作。 |
| **最低角色** | Viewer |
| **参数** | `query_type`（**必填**）：`call_chain`、`inheritance_tree`、`class_methods`、`module_dependencies`、`reverse_dependencies`、`find_entity`、`file_entities`、`graph_stats`、`raw_cypher`、`business_flow`、`flows_for_function`、`related_concepts`、`explore_domain`、`flow_dependencies`。可选：`name`、`file`、`depth`（默认 3）、`direction`（默认 `downstream`）、`cypher`（用于 `raw_cypher`）、`entity_type`（用于 `find_entity`）。 |

**示例**

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

### 3. `rag_index`

| | |
|--|--|
| **描述** | 对目录或 `git_url` 检出执行全量或增量索引。 |
| **最低角色** | **Editor** |
| **参数** | `directory`、`git_url`、`branch`、`repository`、`mode`（`full` \| `incremental`）、`base_ref`、`head_ref`。 |

### 4. `task_status`

| | |
|--|--|
| **描述** | 轮询异步索引/丰富化创建的后台任务状态。 |
| **最低角色** | Viewer |
| **参数** | `task_id`（**必填**）。 |

### 5. `documents`

| | |
|--|--|
| **描述** | 不带 `uid`：列出文档节点及段落；带 `uid`：获取完整文档。 |
| **最低角色** | Viewer |
| **参数** | `uid`（可选）、`repository`（列表时可选过滤）。 |

### 6. `get_code_snippet`

| | |
|--|--|
| **描述** | 获取 Function 或 Class `uid` 的存储代码片段/元数据。 |
| **最低角色** | Viewer |
| **参数** | `node_uid`（**必填**）。 |

### 7. `analyze_code`

| | |
|--|--|
| **描述** | `quality`：单个实体的启发式质量评分；`consistency`：仓库级索引 vs 磁盘一致性检查。 |
| **最低角色** | Viewer |
| **参数** | `mode`：`quality` \| `consistency`（默认 `quality`）。quality 模式：`entity_uid`，可选 `entity_type`。consistency 模式：`repository`。 |

### 8. `search_architecture`

| | |
|--|--|
| **描述** | `layers`：按架构层分类的类列表；`endpoints`：HTTP/RPC/Kafka 风格端点。 |
| **最低角色** | Viewer |
| **参数** | `mode`：`layers` \| `endpoints`。`layers` 模式：`layer`（**必填**，枚举：presentation、business、data_access、rpc、messaging、infrastructure、model、unknown），可选 `repository`、`limit`、`offset`、`search`。`endpoints` 模式：可选 `repository`。 |

### 9. `analyze_changes`

| | |
|--|--|
| **描述** | `pr_review`、`impact`、`impact_scope`、`wiki_pr_impact` 等变更分析模式。 |
| **最低角色** | Viewer |
| **参数** | `mode`（**必填**）。各模式特定参数：参见清单（diff/branch/repo_path、`changed_functions`、`node_name`、`changed_files` 等）。 |

### 10. `get_complete_context`

| | |
|--|--|
| **描述** | 为实体组装完整上下文：代码片段、文档字符串、邻居、Wiki 关联，按 Token 预算裁剪。 |
| **最低角色** | Viewer |
| **参数** | `entity_name`（**必填**），可选 `repository`、`max_tokens`（默认 8000）。 |

### 11. `get_insights`

| | |
|--|--|
| **描述** | `dashboard`：全局 P2 统计；`graph`：仓库异常分析；`all`：两者合并（需 `repository`）。 |
| **最低角色** | Viewer |
| **参数** | `type`：`dashboard` \| `graph` \| `all`（默认 `dashboard`），`repository`（`graph` / `all` 必填）。 |

### 12. `index_freshness`

| | |
|--|--|
| **描述** | 查询仓库的最新 `indexed_at`、节点计数和可选 `commit_sha`。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）。 |

### 13. `get_wiki_page`

| | |
|--|--|
| **描述** | 按作用域获取一个生成的 Wiki 页面。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）、`scope`（**必填**，如 `module:path` 或 `class:fqn`）。 |

### 14. `list_wiki_pages`

| | |
|--|--|
| **描述** | 获取 Wiki 页面的树形结构及元数据。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**），可选 `scope` 子树过滤。 |

### 15. `search_wiki`

| | |
|--|--|
| **描述** | 混合 Wiki 搜索（图 + 向量 + 全文）。 |
| **最低角色** | Viewer |
| **参数** | `repository`（**必填**）、`query`（**必填**）、`mode`（`hybrid` 默认 / `graph` / `semantic` / `keyword`）、`limit`、`min_score`，可选 `scope`。 |

### 16. `wiki_export`

| | |
|--|--|
| **描述** | 将生成的 Markdown 文件写入 `target_dir`；跳过不含 AUTO-GENERATED 标记的人工文件。 |
| **最低角色** | **Editor** |
| **参数** | `repository`（**必填**）、`target_dir`（**必填**），可选 `selected_files`（路径数组）。 |

---

## Agent 集成模式

1. **发现** — 认证后调用 `GET /api/v1/mcp/tools` 缓存工具清单（名称和 Schema）。
2. **搜索后深入** — `rag_query` → 选取 `uid` → `get_code_snippet` 或 `rag_graph`（`find_entity` / `call_chain`）。
3. **长时间索引** — `rag_index` → 轮询 `task_status` 直到 completed 或 failed。
4. **Wiki** — `list_wiki_pages` → `get_wiki_page` 或 `search_wiki`；使用 Editor Token 通过 `wiki_export` 导出。

使用请求头 **`X-Business-Id`**（默认 `default`）在多租户图隔离场景下选择目标图（`auth.resolve_business_id`）。
