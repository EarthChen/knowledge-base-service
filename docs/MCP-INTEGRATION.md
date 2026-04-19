# MCP integration

The service exposes an **MCP-style** tool contract over HTTP:

- **List tools**: `GET /api/v1/mcp/tools` — returns the same manifest as the in-process `MCP_TOOLS_MANIFEST` in `api/mcp_server.py` (12 base tools + 4 wiki tools = **16**).
- **Invoke tool**: `POST /api/v1/mcp/tool` with JSON body `{"tool_name": "...", "arguments": { ... } }` (see `MCPToolCallRequest` in `main.py`).

Authentication uses the `Authorization: Bearer <token>` header when tokens are configured. Tool-level role checks are applied in `KnowledgeBaseMCPHandler.handle_tool_call` using `MCP_TOOL_MIN_ROLE`.

## Role model

| Role | HTTP / meaning | MCP |
|------|----------------|-----|
| **VIEWER** | Read-only API routes | All tools **except** those requiring editor |
| **EDITOR** | Index, write operations | `rag_index`, `wiki_export` (minimum) |
| **ADMIN** | Business admin, sync schedules, destructive ops | No extra MCP tools beyond editor; used on HTTP admin routes |

**MCP tools requiring Editor (or higher):** `rag_index`, `wiki_export`. All other listed tools require **Viewer** only.

## Tool reference (16 tools)

The **inputSchema** below matches the JSON Schema embedded in `MCP_TOOLS_MANIFEST` and `WIKI_MCP_TOOLS_MANIFEST` in `api/mcp_server.py` and `wiki/mcp_tools.py`.

### 1. `rag_query`

| | |
|--|--|
| **Description** | Natural-language hybrid search: semantic + keyword, optional child chunks, RRF, graph expansion. |
| **Min role** | Viewer |
| **Parameters** | `query` (string, **required**). `k` (int, default 5), `expand_depth` (int, default 2), `entity_type` (function / class / module / document / flow / concept), `repository`, `language`, `use_child_chunks` (optional bool; manifest default false — if you **omit** the key, the server uses `HYBRID_SEARCH__USE_CHILD_CHUNKS`, default **true**), `use_query_router` (bool, default true), `use_query_expansion` (bool, default true), `per_file_cap` (int, default 3; MCP clamps 1–20). |

**Example**

```json
{
  "tool_name": "rag_query",
  "arguments": {
    "query": "Where is OAuth token refresh handled?",
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
| **Description** | Structured Cypher-backed graph operations. |
| **Min role** | Viewer |
| **Parameters** | `query_type` (**required**): `call_chain`, `inheritance_tree`, `class_methods`, `module_dependencies`, `reverse_dependencies`, `find_entity`, `file_entities`, `graph_stats`, `raw_cypher`, `business_flow`, `flows_for_function`, `related_concepts`, `explore_domain`, `flow_dependencies`. Optional: `name`, `file`, `depth` (default 3), `direction` (default `downstream`), `cypher` (for `raw_cypher`), `entity_type` for `find_entity`. |

**Example**

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
| **Description** | Full or incremental index of a directory or `git_url` checkout. |
| **Min role** | **Editor** |
| **Parameters** | `directory`, `git_url`, `branch`, `repository`, `mode` (`full` \| `incremental`), `base_ref`, `head_ref`. |

### 4. `task_status`

| | |
|--|--|
| **Description** | Poll background task created by async index / enrich. |
| **Min role** | Viewer |
| **Parameters** | `task_id` (**required**). |

### 5. `documents`

| | |
|--|--|
| **Description** | Without `uid`: list document nodes and sections; with `uid`: fetch full document. |
| **Min role** | Viewer |
| **Parameters** | `uid` (optional), `repository` (optional filter when listing). |

### 6. `get_code_snippet`

| | |
|--|--|
| **Description** | Fetch stored snippet / metadata for a Function or Class `uid`. |
| **Min role** | Viewer |
| **Parameters** | `node_uid` (**required**). |

### 7. `analyze_code`

| | |
|--|--|
| **Description** | `quality`: heuristic score for one entity; `consistency`: index vs disk for a repo. |
| **Min role** | Viewer |
| **Parameters** | `mode`: `quality` \| `consistency` (default `quality`). For quality: `entity_uid`, optional `entity_type`. For consistency: `repository`. |

### 8. `search_architecture`

| | |
|--|--|
| **Description** | `layers`: classes by architecture layer; `endpoints`: HTTP/RPC/Kafka-style endpoints. |
| **Min role** | Viewer |
| **Parameters** | `mode`: `layers` \| `endpoints`. For `layers`: `layer` (**required**, enum: presentation, business, data_access, rpc, messaging, infrastructure, model, unknown), optional `repository`, `limit`, `offset`, `search`. For `endpoints`: optional `repository`. |

### 9. `analyze_changes`

| | |
|--|--|
| **Description** | `pr_review`, `impact`, `impact_scope`, `wiki_pr_impact`. |
| **Min role** | Viewer |
| **Parameters** | `mode` (**required**). Mode-specific: see manifest (diff/branch/repo_path, `changed_functions`, `node_name`, `changed_files`, etc.). |

### 10. `get_complete_context`

| | |
|--|--|
| **Description** | Assembled context for an entity: snippet, docstring, neighbors, wiki ties, token-trimmed. |
| **Min role** | Viewer |
| **Parameters** | `entity_name` (**required**), optional `repository`, `max_tokens` (default 8000). |

### 11. `get_insights`

| | |
|--|--|
| **Description** | `dashboard`: global P2 stats; `graph`: repo anomaly analysis; `all`: both (needs `repository`). |
| **Min role** | Viewer |
| **Parameters** | `type`: `dashboard` \| `graph` \| `all` (default `dashboard`), `repository` (required for `graph` / `all`). |

### 12. `index_freshness`

| | |
|--|--|
| **Description** | Latest `indexed_at`, counts, optional `commit_sha` for a repo. |
| **Min role** | Viewer |
| **Parameters** | `repository` (**required**). |

### 13. `get_wiki_page`

| | |
|--|--|
| **Description** | Fetch one generated wiki page by scope. |
| **Min role** | Viewer |
| **Parameters** | `repository` (**required**), `scope` (**required**, e.g. `module:path` or `class:fqn`). |

### 14. `list_wiki_pages`

| | |
|--|--|
| **Description** | Tree of wiki pages with metadata. |
| **Min role** | Viewer |
| **Parameters** | `repository` (**required**), optional `scope` subtree filter. |

### 15. `search_wiki`

| | |
|--|--|
| **Description** | Hybrid wiki search (graph + vector + FTS). |
| **Min role** | Viewer |
| **Parameters** | `repository` (**required**), `query` (**required**), `mode` (`hybrid` default, `graph`, `semantic`, `keyword`), `limit`, `min_score`, optional `scope`. |

### 16. `wiki_export`

| | |
|--|--|
| **Description** | Write generated Markdown files to `target_dir`; skips human files without AUTO-GENERATED marker. |
| **Min role** | **Editor** |
| **Parameters** | `repository` (**required**), `target_dir` (**required**), optional `selected_files` (array of paths). |

---

## Agent integration patterns

1. **Discover** — Call `GET /api/v1/mcp/tools` after authenticating to cache the manifest (names and schemas).
2. **Search then drill down** — `rag_query` → pick `uid` → `get_code_snippet` or `rag_graph` (`find_entity` / `call_chain`).
3. **Long-running index** — `rag_index` → poll `task_status` until completed or failed.
4. **Wiki** — `list_wiki_pages` → `get_wiki_page` or `search_wiki`; export with `wiki_export` using an editor token.

Use header **`X-Business-Id`** (default `default`) to select the tenant graph when using multi-business isolation with unbound admin tokens (`auth.resolve_business_id`).
