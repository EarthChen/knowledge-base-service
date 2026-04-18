# Wiki Generation Feature — Design Spec

## 1. Background

### Problem Statement

KBS (Knowledge-Base-Service) 已具备完整的代码知识图谱（Tree-sitter AST → FalkorDB 属性图 + 向量索引），但缺乏将图谱数据转化为人类可读文档的能力。开发者仍需手动编写和维护技术文档。

### Competitive Context

DeepWiki-Open（15.7K stars）通过 LLM 为任意 GitHub 仓库一键生成 Wiki，但其核心缺陷是：
- 依赖 LLM 猜测代码结构（无 AST 解析），图表不准确
- 无增量更新，每次全量重新生成
- 强依赖外部 LLM API

KBS 的独特优势在于：已有精确的图结构（73990 节点、180201 边），Mermaid 图可从真实代码关系确定性生成。

### Design Goal

为 KBS 增加 Wiki 生成能力，利用现有图结构 + 可选 LLM 增强，输出比 DeepWiki 更准确、可增量更新的代码文档。

---

## 2. Requirements Summary

| ID | Requirement | Priority | Phase |
|----|------------|----------|-------|
| R1 | 按需局部 Wiki 生成（模块/类级别） | Must | P1 |
| R2 | 已索引仓库一键触发生成 | Must | P1 |
| R3 | 新仓库输入 URL 自动索引+生成 | Must | P1 |
| R4 | LLM 增强降级（预计算→实时LLM→纯结构） | Must | P1 |
| R5 | Mermaid 图从图数据确定性生成 | Must | P1 |
| R6 | API 返回 Markdown + JSON | Must | P1 |
| R7 | MCP generate_wiki 工具 | Must | P1 |
| R8 | 仓库级全量 Wiki 生成 | Must | P2 |
| R9 | Markdown 文件集导出 | Should | P2 |
| R10 | Dashboard Wiki 浏览页 | Should | P2 |
| R11 | 多 LLM Provider（Gateway + OpenAI/Azure + 自定义） | Should | P2 |
| R12 | Webhook 触发自动更新 | Nice | P3 |
| R13 | Wiki 混合搜索（图+向量+全文 RRF 融合） | Must | P1.5 |
| R14 | 交互式代码问答 (Ask)，支持 SSE 流式回答 | Must | P1.5 |
| R15 | 代码位置关联（Wiki → Source file:line） | Must | P1 |
| R16 | 多语言文档生成（中/英） | Should | P1.5 |
| R17 | 层级上下文系统（Repo/Module/Page） | Must | P1 |

### Target Users

- **内部开发者**: Onboarding、了解不熟悉的模块
- **代码评审者**: PR review 前了解上下文和影响范围
- **技术管理者**: 系统架构全貌、服务依赖关系

### Non-Goals

- P1 不优先支持 Ollama 本地模型（P2 多 Provider 架构不排除本地模型）
- 不做社区/开源版本
- 不替代手写架构文档（Wiki 是自动生成的补充，不是替代）
- P1 不实现 Wiki 级别的 RBAC（假定所有 API 调用者已通过上层认证；Wiki 继承仓库级权限）

### Performance KPIs

| Metric | Target (structure mode) | Target (full mode) |
|--------|------------------------|-------------------|
| Single module Wiki generation | < 5s | < 15s |
| Single class Wiki generation | < 2s | < 10s |
| Full repo Wiki (100 pages) | < 3min | < 10min |
| Lite Index → Wiki (Quick Wiki) | < 60s | < 90s |
| Wiki Search latency (hybrid) | < 500ms | — |
| Wiki Ask (first token) | — | < 2s |

---

## 3. Architecture

### 3.1 Core Design: Composer Pipeline + MCP Agent Dual Path

```
Path 1: Composer Pipeline (batch/export/no-LLM capable)
  StructurePlanner → DataCollector → ContentComposer → DiagramGen → Exporter

Path 2: MCP Agent (interactive/on-demand/natural LLM orchestration)
  MCP generate_wiki tool → reuses existing 12 MCP tools → LLM orchestrates
```

**Path 1 (Composer Pipeline)** handles deterministic, reproducible Wiki generation:
- StructurePlanner: derives Wiki directory structure from graph CONTAINS edges
- DataCollector: queries FalkorDBStore for node/edge data
- ContentComposer: assembles Markdown sections per node type, with 3-tier LLM fallback
- DiagramGen: generates Mermaid from graph edges (deterministic, no LLM)
- Exporter: outputs Markdown string / file set / JSON

**Path 2 (MCP Agent)** handles interactive, creative requests:
- The `generate_wiki` MCP tool returns structured data
- Any MCP client (Cursor Agent, ACP Gateway) can orchestrate with LLM
- Zero new code needed for LLM orchestration — it's inherent in the MCP protocol

Both paths share the same underlying query capabilities (FalkorDBStore, GraphQuery, SemanticQuery).

### 3.2 Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    Wiki Generation Module                      │
│                                                                │
│  wiki/                                                         │
│  ├── models.py             # WikiPage, WikiStructure,          │
│  │                         # SourceLocation, WikiContext        │
│  ├── structure_planner.py  # Scope resolution + page tree      │
│  ├── data_collector.py     # Graph queries → PageData          │
│  │                         # + source location extraction      │
│  ├── composer.py           # Content composition + fallback    │
│  │                         # + enhanced Tier 3 templates       │
│  ├── context.py            # Glossary, arch summary, budget    │
│  │                         # + hierarchical context system     │
│  ├── diagram_gen.py        # Graph edges → Mermaid             │
│  ├── exporter.py           # Output formatting (MD/JSON)       │
│  │                         # + source links + cross-refs       │
│  ├── cache.py              # In-memory LRU cache (P1)          │
│  ├── search.py             # 3-path hybrid search + RRF (P1.5) │
│  └── ask.py                # Interactive Q&A + streaming (P1.5)│
│                                                                │
│  api/routes/                                                   │
│  └── wiki_routes.py        # REST + SSE + async endpoints      │
│                            # /generate /quick /search /ask     │
│                                                                │
│  Reused from existing:                                         │
│  ├── store/falkordb_store.py   # Graph queries                 │
│  ├── query/graph_query.py      # Cypher queries                │
│  ├── query/semantic_query.py   # Vector search                 │
│  ├── query/hybrid_query_service.py  # RRF fusion layer (P1.5)  │
│  ├── llm/provider.py           # LLM integration               │
│  ├── task/repo_task_manager.py # Async task infrastructure     │
│  └── api/mcp_server.py         # MCP tool registry (5 tools)  │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Data Flow

```
[User Request]
    │
    ▼
[API: POST /api/v1/wiki/generate]
    │
    ├─ scope = "module:com.example.service"
    ├─ repository = "my-repo"
    ├─ mode = "full" | "structure"
    │
    ▼
[StructurePlanner]
    │ Query: MATCH (m:Module)-[:CONTAINS]->(c) WHERE m.path = ...
    │ Output: WikiStructure { pages: [...], hierarchy: {...} }
    │
    ▼
[DataCollector] (per page)
    │ Query: node properties, edges (CALLS, INHERITS, IMPORTS)
    │ Query: node.business_summary (pre-computed description)
    │ Output: PageData { node, edges, summary, methods, ... }
    │
    ▼
[ContentComposer]
    │ 3-tier content strategy:
    │   1. Has pre-computed business_summary? → Use it
    │   2. LLM available? → Generate description in real-time
    │   3. Neither? → Use structural description only
    │ Output: Markdown string per page
    │
    ▼
[DiagramGen]
    │ Input: edges from DataCollector
    │ Algorithm: deterministic edge → Mermaid conversion
    │ Output types: class diagram, flowchart, dependency graph
    │
    ▼
[Exporter]
    │ Formats:
    │   - JSON (API response)
    │   - Markdown string (single page)
    │   - Markdown file set (docs/wiki/*)
    │
    ▼
[Response]
```

> See also: Section 4.12 for Search data flow, Section 4.13 for Ask data flow, Section 4.14 for Source Location linking.

---

## 4. Detailed Design

### 4.1 Wiki Page Types

| Page Type | Content | Diagram Type | Data Source | Phase |
|-----------|---------|--------------|------------|-------|
| **Module Overview** | Module description, contained classes/functions list, import dependencies | Dependency graph (flowchart) | CONTAINS + IMPORTS edges | P1 |
| **Class Detail** | Class description, fields, methods, inheritance chain, callers/callees | Class diagram + call flowchart | INHERITS + CALLS + CONTAINS edges | P1 |
| **Repository Overview** | Tech stack, top-level modules, entry points, stats | Architecture layer diagram | Module nodes + stats aggregation | P2 |
| **Architecture Overview** | Layer breakdown, cross-layer dependencies | Layered architecture diagram | Architecture layer classification | P2 |
| **API Reference** | Endpoint list, handlers, request/response types | Endpoint flowchart | REST endpoint nodes (if detected) | P2 |
| **Data Flow** | Key paths from entry to storage | Sequence diagram | CALLS edge chains | P2 |

> **P1 scope='repo' behavior**: P1 accepts `scope="repo"` but generates only Module Overview pages (listing all top-level modules). Repository Overview and Architecture Overview page types require P2's `compose_repo_wiki()`. In P1, `scope="repo"` is equivalent to generating Module Overview pages for all top-level modules.

### 4.2 LLM 3-Tier Fallback Strategy

```python
async def get_description(node: GraphNode, llm_provider: LLMProvider | None) -> str:
    # Tier 1: Pre-computed description (from P2 enrichment)
    if node.business_summary:
        return node.business_summary

    # Tier 2: Real-time LLM generation
    if llm_provider:
        prompt = build_description_prompt(node)
        return await llm_provider.generate(prompt)

    # Tier 3: Structural fallback
    return build_structural_description(node)
```

Structural fallback example:
- Class: `"UserService: class with 12 methods, extends BaseService, implements IUserRepository"`
- Function: `"processOrder(order: Order) -> Result: called by OrderController.handleRequest, calls PaymentService.charge"`

### 4.3 Diagram Generation (Deterministic)

```python
def generate_mermaid_class_diagram(class_node, edges) -> str:
    """Generate Mermaid class diagram from graph edges. No LLM needed."""
    lines = ["classDiagram"]
    # Inheritance
    for edge in edges.filter(type="INHERITS"):
        lines.append(f"    {edge.target} <|-- {class_node.name}")
    # Methods
    for method in class_node.methods:
        lines.append(f"    {class_node.name} : +{method.signature}")
    # Dependencies
    for edge in edges.filter(type="CALLS"):
        lines.append(f"    {class_node.name} ..> {edge.target} : calls")
    return "\n".join(lines)
```

**Diagram complexity control**: When a diagram would exceed 15 nodes, display the top-N nodes by connectivity (INHERITS > CALLS > IMPORTS) and collapse the rest into a single "... and N more" group node. This prevents unreadable diagrams for large modules.

### 4.4 API Design

#### P1 Endpoints

```
POST /api/v1/wiki/generate
  Body: {
    "repository": "my-repo",
    "scope": "module:com.example.service" | "class:com.example.UserService" | "repo",
    "mode": "full" | "structure",  // full = with LLM enhancement
    "format": "markdown" | "json"
  }
  Response: {
    "pages": [
      {
        "path": "modules/service.md",
        "title": "Service Module",
        "content": "# Service Module\n...",
        "diagrams": ["classDiagram\n..."],
        "metadata": { "node_count": 15, "edge_count": 42 }
      }
    ],
    "structure": { "children": [...] },
    "stats": { "total_pages": 5, "generation_time_ms": 1200 }
  }

POST /api/v1/wiki/quick
  Body: {
    "git_url": "https://gitlab.example.com/team/repo.git",
    "branch": "main",
    "token": "...",  // optional, for private repos
    "mode": "full" | "structure"
  }
  Response: same as above (after auto-indexing)
```

#### P1.5 Endpoints

```
GET /api/v1/wiki/{repository}/pages
  Query: scope (optional, default: entire repo)
  Response: {
    "pages": [
      { "path": "modules/service.md", "title": "Service Module", "scope": "module:src/service.py" }
    ],
    "total": 12
  }

GET /api/v1/wiki/{repository}/pages/{scope}
  Response: {
    "path": "classes/UserService.md",
    "title": "UserService",
    "content": "# UserService\n...",
    "diagrams": ["classDiagram\n..."],
    "source_locations": [...],
    "method_locations": [...],
    "context": { "repository": "...", "module": "...", "page": "..." }
  }

POST /api/v1/wiki/search
  Body: {
    "repository": "my-repo",
    "query": "authentication login",
    "mode": "hybrid" | "graph" | "semantic" | "keyword",
    "limit": 10,
    "min_score": 0.0
  }
  Response: {
    "results": [
      {
        "page": "classes/UserService.md",
        "score": 0.92,
        "snippet": "UserService delegates to AuthProvider...",
        "source_locations": [...],
        "context": { "repository": "...", "module": "...", "page": "..." }
      }
    ],
    "query_expansion": { "original": "authentication login", "expanded": ["AuthProvider", "TokenService"] }
  }

POST /api/v1/wiki/ask
  → See Section 4.13 for detailed API design (SSE streaming)
```

#### MCP Tools (5 tools)

```json
[
  {
    "name": "generate_wiki",
    "description": "Generate documentation wiki for indexed code. Returns structured Markdown with Mermaid diagrams and source locations.",
    "parameters": {
      "repository": "Repository name",
      "scope": "Scope: 'repo' for full, 'module:<path>' for module, 'class:<fqn>' for class",
      "mode": "Generation mode: 'full' (with LLM) or 'structure' (graph data only)"
    }
  },
  {
    "name": "search_wiki",
    "description": "Search generated Wiki pages using hybrid search (graph + vector + full-text). Returns ranked results with scores, snippets, source locations, and hierarchical context.",
    "parameters": {
      "repository": "Repository name",
      "query": "Search query string",
      "mode": "Search mode: 'hybrid' (default) | 'graph' | 'semantic' | 'keyword'",
      "limit": "Max results (default: 10)",
      "min_score": "Minimum relevance score threshold (0.0-1.0)"
    }
  },
  {
    "name": "get_wiki_page",
    "description": "Retrieve a specific Wiki page by scope. Returns page content, diagrams, source locations, and method-level code references. Suggests similar pages if not found.",
    "parameters": {
      "repository": "Repository name",
      "scope": "Page scope: 'module:<path>' or 'class:<fqn>'"
    }
  },
  {
    "name": "list_wiki_pages",
    "description": "List generated Wiki pages as a directory tree with metadata.",
    "parameters": {
      "repository": "Repository name",
      "scope": "Optional scope filter (default: entire repo)"
    }
  },
  {
    "name": "ask_about_code",
    "description": "Interactive Q&A about code using Wiki context + hybrid search. Returns streaming answer with source code references.",
    "parameters": {
      "repository": "Repository name",
      "question": "Natural language question about the code",
      "scope": "Optional scope to focus the search",
      "conversation_id": "Optional ID for multi-turn conversation"
    }
  }
]
```

### 4.5 Async Task Model

Wiki generation can be time-consuming (especially with LLM enhancement or auto-indexing). Both `generate` and `quick` endpoints support two modes:

**Synchronous** (for small scopes, e.g., single class/module):
- Returns result directly in response body

**Asynchronous** (for large scopes or auto-index):
- Returns `{ "task_id": "wiki-xxx", "status": "pending" }` immediately
- Client polls `GET /api/v1/wiki/tasks/{task_id}` for status
- Reuses existing `RepoTaskManager` infrastructure (same pattern as `enrich:` tasks)

**Streaming** (P1):
- `POST /api/v1/wiki/generate` with `Accept: text/event-stream` header
- Returns SSE stream: each event is one generated WikiPage
- Enables real-time progress display for large repositories

```
event: wiki-page
data: { "path": "modules/service.md", "content": "...", "progress": "3/12" }

event: wiki-page
data: { "path": "modules/store.md", "content": "...", "progress": "4/12" }

event: wiki-complete
data: { "total_pages": 12, "generation_time_ms": 5400 }
```

### 4.6 Scope Parameter Format

The `scope` parameter supports three formats:
- `"repo"` — entire repository
- `"module:<file_path>"` — module by file path, e.g., `"module:src/service.py"` or `"module:com/example/service"`
- `"class:<fqn>"` — class by fully qualified name, e.g., `"class:com.example.UserService"`

The system resolves scope to graph nodes: first tries exact match on `path` property, then falls back to `fqn` property.

### 4.7 LLM Context Quality Assurance Strategy

When generating Wiki for a large repo (e.g., 73990 nodes), independent per-page LLM calls risk:
- **Cross-page terminology inconsistency** (same concept called different names)
- **Narrative incoherence** (overview and detail pages tell contradictory stories)
- **Context overflow** for complex nodes (50+ methods, 100+ edges)
- **Incremental update style drift** (new pages vs old pages use different tone)

The solution is a 3-layer combined strategy:

#### Layer 1: Global Context Anchor (P1)

**Pre-generation phase** creates shared context artifacts before any page is generated:

```
1. Glossary Generation (one LLM call):
   Input: top-level module names + entry points + high-frequency identifiers
   Output: { "terms": { "UserService": "Core user management service", ... },
             "abbreviations": { "KBS": "Knowledge-Base-Service", ... },
             "conventions": { "naming": "PascalCase for classes", ... } }

2. Architecture Summary (one LLM call or structural):
   Input: module dependency graph + layer classification
   Output: "This is a 3-layer Spring Boot application with REST API, service, and repository layers..."

3. Style Sheet (static template):
   - Section order: Overview → Key Components → Relationships → Diagrams
   - Tone: technical, concise, third-person
   - Terminology: use glossary terms consistently
```

**Hierarchical generation order** ensures parent context is available:

```
Step 1: Generate repo overview (uses glossary + arch summary)
Step 2: Generate module pages (inject repo overview summary as context)
Step 3: Generate class pages (inject module summary as context)
```

Each LLM call receives: `[system: glossary + style sheet] + [context: parent summary] + [data: node + edges]`

**Context overhead**: ~1000-2000 tokens per page (acceptable for 16K-128K context windows).

#### Layer 2: Per-Page Context Management (P1)

For complex nodes that generate too much context data:

| Strategy | Trigger | Action |
|----------|---------|--------|
| **Edge prioritization** | All pages | Rank edges: INHERITS > IMPLEMENTS > CALLS(top-10) > IMPORTS(top-10) |
| **Method grouping** | Classes with >20 methods | Group methods by category (CRUD, events, helpers), summarize groups |
| **Neighbor truncation** | Nodes with >15 connected neighbors | Full detail for top-5 by connectivity, one-line summary for rest |
| **Context budget** | All pages | Hard token budget per section; truncate gracefully with "... and N more" |

**Context budget model per page:**
```
System prefix (glossary + style):    ~500 tokens
Architecture summary:                ~200 tokens
Parent page summary:                 ~300 tokens
Node data (methods, fields, docs):   ~2000-5000 tokens
Edge data (top-N neighbors):         ~1000-3000 tokens
─────────────────────────────────────────────────
Total per page:                      ~4000-9000 tokens
```

#### Layer 3: Incremental Consistency Guard (P2)

When regenerating only changed pages during incremental updates:

1. **Glossary persistence**: Glossary is stored per-repo in graph metadata. Loaded and injected for all incremental generations.
2. **Neighbor context injection**: Read EXISTING content of changed page's parent + sibling pages. Inject their first-paragraph summaries as context.
3. **Diff-aware regeneration**: Instead of regenerating from scratch, provide the OLD page content + code DIFF to LLM. Prompt: "Update this documentation to reflect the following code changes." This preserves style continuity.
4. **Post-generation validation**: Cross-check generated terminology against glossary. Log warnings for new terms not in glossary.

#### Implementation Mapping

| Layer | Phase | Effort | Integrated With |
|-------|-------|--------|----------------|
| Layer 1: Global Context Anchor | P1 | +1d (added to T1.4 Composer) | T1.4 composer.py |
| Layer 2: Per-Page Context Management | P1 | +0.5d (added to T1.4 Composer) | T1.4 composer.py |
| Layer 3: Incremental Consistency Guard | P2 | +1d (added to T-A3 Incremental) | T-A3 incremental update |
| Glossary persistence | P2 | +0.5d | T-C2 cache layer |

### 4.8 Quick Wiki Flow (R2 + R3)

```
[Already indexed repo]
  POST /api/v1/wiki/generate { repository: "my-repo", scope: "repo" }
  → Instant response (reads from graph)

[New repo via URL]
  POST /api/v1/wiki/quick { git_url: "https://..." }
  → Step 1: Clone + Index (reuse existing index pipeline)
  → Step 2: Generate Wiki
  → Response includes both index stats and wiki content
```

### 4.9 Inline Cross-Reference Auto-Linking (P1)

When generated wiki content mentions another class, module, or function that has its own wiki page, the system should auto-link it:

```
Input (raw Markdown from Composer):
  "UserService delegates to PaymentService.charge() for billing."

Output (after auto-linking):
  "UserService delegates to [PaymentService](../classes/PaymentService.md).charge() for billing."
```

**Implementation**: Post-processing step in Exporter:
1. Build entity→page-path index from WikiStructure
2. Scan composed Markdown content for entity name matches
3. Wrap matched names in Markdown links (`[EntityName](relative/path.md)`)
4. Skip if entity is the current page itself (no self-link)

**Path deduplication**: When multiple entities share the same short name (e.g., `com.a.UserService` and `com.b.UserService`), the Exporter uses FQN-based paths (`classes/com.a.UserService.md` vs `classes/com.b.UserService.md`) to ensure uniqueness.

### 4.10 Quick Wiki Lite Indexing Mode (P1)

Standard Quick Wiki for new repos requires full Tree-sitter indexing (5-10 min for large repos), making time-to-first-result much slower than DeepWiki (~30s).

**Solution: Two-phase indexing:**

```
Phase 1 — Lite Index (fast, <60s):
  - Parse top-level structure only (modules, classes, public methods)
  - Skip deep call graph analysis, skip vector embedding
  - Generate initial wiki immediately from lite graph

Phase 2 — Full Index (background):
  - Async task enriches the full graph (call chains, imports, embeddings)
  - When complete, wiki can be regenerated with full accuracy
```

API behavior:
```
POST /api/v1/wiki/quick { git_url: "...", mode: "structure" }
  → Phase 1: Lite index + generate (returns in <60s)
  → Response includes: { "indexing": "lite", "full_index_task_id": "idx-xxx" }
  → Client can later re-generate after full index completes
```

### 4.11 Error Handling

| Error Scenario | HTTP Status | Response | Behavior |
|---------------|------------|----------|----------|
| Invalid scope format (e.g., `"foo:bar:baz"`) | 400 | `{ "error": "invalid_scope", "detail": "Scope must be 'repo', 'module:<path>', or 'class:<fqn>'" }` | Reject immediately |
| Scope resolves to zero nodes | 404 | `{ "error": "scope_not_found", "detail": "No graph nodes match scope 'module:src/missing.py'" }` | Reject after graph query |
| Repository not indexed | 404 | `{ "error": "repo_not_found", "detail": "Repository 'unknown-repo' not indexed. Use /wiki/quick to auto-index." }` | Suggest /quick |
| FalkorDB unavailable | 503 | `{ "error": "service_unavailable", "detail": "Graph database is unavailable" }` | Log ERROR + Hubble alert |
| LLM unavailable in `full` mode | 200 (degraded) | Normal response with `"degraded": true, "fallback_tier": "structural"` | Auto-fallback to Tier 3; log WARN |
| LLM rate limited | 200 (degraded) | Same as above | Partial LLM results + structural for remaining pages |
| Task not found (polling) | 404 | `{ "error": "task_not_found" }` | — |
| Generation timeout (>5min) | — | Task status: `"failed"`, `"error": "generation_timeout"` | Async task fails; log ERROR |

**Key principle**: LLM failures NEVER block generation. The system degrades gracefully to structural mode and reports `degraded: true` in the response.

### 4.12 Wiki Hybrid Search Pipeline (Inspired by QMD)

Wiki Search and Wiki Ask use a **3-path fusion pipeline** that combines KBS's unique graph query capability with vector search and full-text search, inspired by [QMD](https://github.com/tobi/qmd)'s RRF fusion architecture but enhanced with a graph path that neither QMD nor DeepWiki can offer.

#### Architecture

```
[User Query]
    │
    ▼
[Graph-Aware Query Expansion]
    │ 1. LLM semantic expansion: "UserService login" → "authentication verify token"
    │ 2. Graph structure expansion (KBS-unique):
    │    Query graph for UserService's CALLS edges → AuthProvider, TokenService
    │    Expand query with neighbor names → "AuthProvider verify TokenService generate"
    │
    ├─ Original query (×2 weight)
    ├─ LLM expanded variant
    └─ Graph-expanded variant
          │
    ┌─────┼─────────────────────────────┐
    │     │                             │
    ▼     ▼                             ▼
[Graph Path]    [Vector Path]      [FTS Path]
 Cypher query    bge-m3 cosine      Wiki Markdown
 CALLS/INHERITS  similarity on      full-text search
 /IMPORTS edges  code embeddings    on generated pages
 weight: ×2      weight: ×1         weight: ×1.5
    │             │                    │
    └─────────────┼────────────────────┘
                  │
                  ▼
         [RRF Fusion (k=60)]
          score = Σ(weight × 1/(k+rank+1))
          Top-rank bonus: #1 +0.05, #2-3 +0.02
                  │
                  ▼
         [Top-30 candidates]
                  │
                  ▼
         [Optional: LLM Re-ranking] (P2)
          Cross-encoder relevance scoring
                  │
                  ▼
         [Final ranked results with context]
```

#### Why 3-Path Fusion Outperforms QMD and DeepWiki

| System | Search Paths | Accuracy | Structural Understanding |
|--------|-------------|----------|--------------------------|
| **DeepWiki** | Vector only (FAISS) | Low — text similarity only | None |
| **QMD** | BM25 + Vector + Reranker | High — hybrid retrieval | None (text-level) |
| **KBS Wiki** | **Graph + Vector + FTS** | Highest — structural + semantic + keyword | Full (AST-parsed relationships) |

The graph path provides **structural precision** that text-based search cannot achieve. For example:
- "Who calls UserService.createUser?" → Graph path returns exact CALLS edges (100% accurate)
- "Classes similar to UserService" → Vector path returns semantically related classes
- "UserService authentication" → FTS path returns wiki pages containing these keywords

#### Graph-Aware Query Expansion

Unlike QMD's pure LLM expansion, KBS can expand queries using real code relationships. **P1.5 default: Graph Expansion only** (no LLM call, ensuring < 500ms search latency KPI). LLM semantic expansion is opt-in via `expand_mode: "llm"` parameter and recommended only for the Ask feature where latency tolerance is higher (2s first-token KPI).

```python
async def expand_query_with_graph(query: str, graph_store: FalkorDBStore) -> list[str]:
    entities = extract_entity_names(query)  # e.g., ["UserService"]
    expanded_terms = []
    for entity in entities:
        neighbors = await graph_store.query(
            "MATCH (n)-[:CALLS|INHERITS|IMPORTS]->(m) "
            "WHERE n.name = $name RETURN m.name LIMIT 5",
            {"name": entity}
        )
        expanded_terms.extend([n["m.name"] for n in neighbors])
    return expanded_terms  # ["AuthProvider", "TokenService", "BaseService"]
```

#### Implementation Mapping

| Component | Phase | Effort | Depends On |
|-----------|-------|--------|------------|
| RRF fusion layer in HybridQueryService | P1.5 | +1d | P1 complete |
| Graph-Aware Query Expansion | P1.5 | +0.5d | P1 complete |
| Wiki FTS index (on generated Markdown) | P1.5 | +0.5d | P1 exporter |
| LLM Re-ranking (optional) | P2 | +1d | P1.5 fusion |

#### FTS Engine Selection

P1.5 uses **FalkorDB's built-in full-text index** (`db.idx.fulltext.createNodeIndex`) on WikiPage nodes stored in the graph. This avoids introducing a new dependency (Elasticsearch/Meilisearch) while leveraging the existing FalkorDB infrastructure.

Wiki page content is stored as a `content` property on `WikiPage` graph nodes, with a full-text index created at generation time. If FalkorDB's FTS proves insufficient for large corpora (>10K pages), P2 can migrate to a dedicated search engine.

```cypher
CALL db.idx.fulltext.createNodeIndex('WikiPage', 'content', 'title')
CALL db.idx.fulltext.queryNodes('WikiPage', 'authentication login') YIELD node, score
```

### 4.13 Wiki Ask Feature

The Ask feature enables interactive Q&A about code, scoped to the current Wiki page or entire repository. This addresses the most significant capability gap vs DeepWiki.

#### Design

```
[User Question] + [Current Wiki Page Context]
    │
    ▼
[3-Path Hybrid Search] (Section 4.12)
    │ Graph: structural relationships relevant to question
    │ Vector: semantically similar code segments
    │ FTS: keyword matches in Wiki content
    │
    ▼
[Context Assembly]
    │ Wiki page summary (from hierarchical context)
    │ + Top-5 search results (code snippets + graph context)
    │ + Source locations for each result
    │
    ▼
[LLM Generation] (streaming)
    │ System: glossary + architecture summary
    │ Context: assembled search results
    │ User: question + conversation history
    │
    ▼
[Streaming Response with Source Links]
```

#### API Design

```
POST /api/v1/wiki/ask
  Body: {
    "repository": "my-repo",
    "scope": "module:com.example.service",  // optional, scopes search
    "question": "How does UserService handle authentication?",
    "conversation_id": "conv-xxx",  // optional, for multi-turn
    "mode": "hybrid"  // "hybrid" | "graph" | "semantic"
  }
  Response (SSE stream):
    event: wiki-answer
    data: { "content": "UserService delegates...", "delta": "delegates" }

    event: wiki-sources
    data: {
      "sources": [
        {
          "entity": "UserService",
          "file_path": "src/service/UserService.java",
          "start_line": 45,
          "wiki_page": "classes/UserService.md",
          "relevance_score": 0.92
        }
      ]
    }

    event: wiki-answer-complete
    data: { "conversation_id": "conv-xxx", "tokens_used": 1200 }
```

#### Advantage Over DeepWiki's Ask

| Aspect | DeepWiki Ask | KBS Wiki Ask |
|--------|-------------|--------------|
| Retrieval | FAISS vector only | Graph + Vector + FTS (3-path) |
| Accuracy | Text similarity | Structural precision |
| Context | Raw code chunks | Wiki page + graph relationships |
| Source linking | None | Exact file:line references |
| Conversation | Basic history | History + graph context evolution |

#### Implementation

| Task | Effort | Depends On |
|------|--------|------------|
| Ask API endpoint (SSE) | 1d | P1 API layer |
| Hybrid search integration | 0.5d | 4.12 Search Pipeline |
| Conversation history | 0.5d | — |
| Dashboard Ask UI | 1d | P2 Dashboard |
| **Total** | **3d** | P1 + P1.5 |

#### Conversation History Storage

P1.5 uses an **in-memory dict with LRU eviction** for conversation history:

```python
conversation_store: dict[str, ConversationHistory]  # conversation_id → history
max_conversations = 200   # LRU eviction
max_turns_per_conversation = 10  # oldest turns dropped
conversation_ttl = 30 * 60  # 30 minutes inactivity timeout
```

Multi-instance deployments: P1.5 conversations are **sticky to the instance** (acceptable for single-instance P1.5 deployment). P2 adds Redis-backed storage for multi-instance support.

### 4.14 Code Location Linking

Every Wiki page links back to the exact source code location, enabling both human developers and AI agents to navigate from documentation to code instantly. This is a **unique KBS advantage** — neither DeepWiki nor QMD can provide this because they lack AST-level code parsing.

#### Source Location Model

```python
@dataclass
class SourceLocation:
    file_path: str       # "src/main/java/com/example/UserService.java"
    start_line: int      # 15
    end_line: int        # 120
    fqn: str             # "com.example.UserService"
    repository: str      # "my-repo"

@dataclass
class WikiPage:
    # ... existing fields ...
    source_locations: list[SourceLocation]
```

#### Three Linking Modes

**Mode A: Page-Level Source Link** — Each Wiki page header shows its primary source file:

```markdown
# UserService
> 📍 Source: [`src/service/UserService.java:15-120`](source://my-repo/src/service/UserService.java#L15)
```

**Mode B: Inline Source Links** — Method/field references link to their definitions:

```markdown
## Methods

| Method | Source | Description |
|--------|--------|-------------|
| `createUser()` | [`L45`](source://UserService.java#L45) | Creates a new user account |
| `findById()` | [`L67`](source://UserService.java#L67) | Finds user by primary key |
```

**Mode C: IDE Deep Links** — Dashboard renders source links as clickable IDE deep links:

```
vscode://file/{repo_path}/{file_path}:{line}
cursor://file/{repo_path}/{file_path}:{line}
idea://open?file={repo_path}/{file_path}&line={line}
```

Configurable via API parameter or dashboard settings, inspired by QMD's `editor_uri` template.

#### For Agent Workflows

MCP tools return `source_locations` in every response, enabling agents to:
1. Read Wiki documentation about a module
2. Get exact file:line references for each entity
3. Navigate directly to code for modification
4. Include source context in PR reviews

#### API Response Extension

```json
{
  "pages": [
    {
      "path": "classes/UserService.md",
      "content": "# UserService\n...",
      "source_locations": [
        {
          "file_path": "src/service/UserService.java",
          "start_line": 15,
          "end_line": 120,
          "fqn": "com.example.UserService"
        }
      ],
      "method_locations": [
        { "name": "createUser", "file_path": "...", "start_line": 45, "end_line": 62 },
        { "name": "findById", "file_path": "...", "start_line": 67, "end_line": 78 }
      ]
    }
  ]
}
```

#### Implementation

| Task | Effort | Phase |
|------|--------|-------|
| SourceLocation model + DataCollector extraction | 0.5d | P1 (T1.3b) |
| Exporter: inline source link generation | 0.5d | P1 (T2.1) |
| API response: source_locations field | 0.25d | P1 (T2.2) |
| MCP tool: source_locations in response | 0.25d | P1 (T2.6) |
| Dashboard: IDE deep link rendering | 0.5d | P2 (T-C3) |
| **Total** | **2d** | P1 + P2 |

### 4.15 Hierarchical Context System

Inspired by QMD's path-level context, the Wiki generation pipeline maintains a hierarchical context system that improves both content quality and search relevance.

#### Three Context Levels

| Level | Content | Generated By | Used By |
|-------|---------|-------------|---------|
| **Repository Context** | Architecture summary, tech stack, layer classification | One LLM call or structural analysis | All page generation + search |
| **Module Context** | Module purpose, key classes, domain responsibility | Per-module LLM call or structural | Child page generation + search |
| **Page Context** | One-sentence summary of each Wiki page | Auto-extracted from first paragraph | Search result display + Ask context |

#### Context Storage

```python
@dataclass
class WikiContext:
    repository_context: str       # "3-layer Spring Boot app with REST/Service/Repository"
    module_contexts: dict[str, str]  # {"service/": "Core business logic...", ...}
    page_contexts: dict[str, str]    # {"classes/UserService.md": "User management service...", ...}
    glossary: dict[str, str]         # {"KBS": "Knowledge-Base-Service", ...}
```

Repository-level and module-level contexts are persisted in graph metadata for incremental generation consistency (Layer 3).

#### Context in Search Results

Search results include hierarchical context for better relevance assessment:

```json
{
  "results": [
    {
      "page": "classes/UserService.md",
      "score": 0.92,
      "snippet": "UserService delegates to AuthProvider...",
      "context": {
        "repository": "3-layer Spring Boot application",
        "module": "Core business logic layer",
        "page": "User management service with CRUD and auth"
      }
    }
  ]
}
```

### 4.16 Concurrency Control

Wiki generation can be resource-intensive (LLM API calls, graph queries). The system implements concurrency control to prevent resource exhaustion.

| Control | Default | Configurable |
|---------|---------|-------------|
| Max concurrent generation tasks | 5 | Yes (env var) |
| LLM API rate limit (per provider) | 10 req/s | Yes (config) |
| Max pages per single generation | 200 | Yes (API param) |
| Task queue priority | module > class > repo > quick | Fixed |
| Generation timeout | 5 min (module), 30 min (repo) | Yes (config) |

Tasks exceeding the concurrency limit are queued with priority ordering. The existing `RepoTaskManager` infrastructure handles queue management.

### 4.17 P1 Simple Cache

P1 includes an in-memory LRU cache to avoid redundant generation for the same scope:

```python
cache_key = (repository, scope, mode, graph_version_hash)
cache_ttl = until graph re-index (version hash changes)
cache_size = 100 entries (LRU eviction)
```

Note: `mode` is part of the cache key because `structure` and `full` modes produce different outputs for the same scope.

Cache is automatically invalidated when the underlying graph is updated (re-index or incremental update changes the version hash). P2 adds persistent file-based cache with the full `WikiCacheLayer`.

#### graph_version_hash Computation

`graph_version_hash` is a monotonically increasing integer stored as graph metadata on the repository node. It increments on every re-index or incremental update:

```python
# Stored as: MATCH (r:Repository {name: $repo}) SET r.graph_version = r.graph_version + 1
graph_version_hash = repo_node.graph_version  # e.g., 42
```

Simple and deterministic — no need for content hashing. The version counter is set to 1 on initial indexing.

### 4.18 Enhanced Tier 3 Structural Output

Tier 3 (no-LLM) output uses natural language templates instead of dry key-value format:

```python
# Before (dry):
"UserService: class with 12 methods, extends BaseService, implements IUserRepository"

# After (template-based natural language):
"""UserService is the core class in the service layer for user management.
It extends BaseService and implements the IUserRepository interface,
providing 12 public methods including createUser(), findById(), and updateProfile().
It is called by UserController and depends on UserRepository for data access.
Key relationships: inherits from BaseService, calls PaymentService.charge()
and NotificationService.send()."""
```

Templates are defined per page type (module overview, class detail) and populated from graph data. This provides significantly better readability without LLM, making the structural mode viable for real onboarding use cases. Templates support i18n; see P1.5 T-S4 for multi-language implementation.

---

## 5. Phased Delivery Plan

### P1 — MVP: On-Demand Local Generation (~3.5 weeks)

#### Build Order & Dependency Graph

```
T1.1 Data Models ──┐
                    ├──→ T1.4 Composer ──→ T2.1 Exporter ──→ T2.2 API (sync)
T1.2 DiagramGen ───┤                                          │
                    │                                          ├──→ T2.3 Async Model
T1.3 StructurePlanner ─┘                                      ├──→ T2.4 SSE Streaming
                                                               ├──→ T2.5 /quick Endpoint
                                                               └──→ T2.6 MCP Tool
                                                                         │
                                                                    T2.7 Tests
```

#### Sprint 1 (Week 1): Foundation Layer

| Task | Description | Effort | Dependencies | Existing Code Touched |
|------|------------|--------|-------------|----------------------|
| T1.1 | Data models: `WikiPage`, `WikiStructure`, `WikiConfig`, `ScopeParam` | 0.5d | None | New: `wiki/models.py` |
| T1.2 | `diagram_gen.py`: class diagram, dependency graph, call flowchart — 3 diagram types, each with edge filtering + Mermaid template | 2d | T1.1 | Reads from: `query/graph_query.py` |
| T1.3 | `structure_planner.py`: scope parser (`repo`/`module:<path>`/`class:<fqn>`), graph query for matching nodes, page tree from CONTAINS edges | 2d | T1.1 | Reads from: `query/graph_query.py`, `store/falkordb_store.py` |
| T1.3b | `data_collector.py`: per-page data collection — query node properties, edges (CALLS, INHERITS, IMPORTS), business_summary, **source locations (file_path, start_line, end_line, fqn)**; applies Layer 2 edge prioritization + neighbor truncation | 1.5d | T1.1, T1.3 | Reads from: `query/graph_query.py`, `store/falkordb_store.py` |
| T1.4 | `composer.py` + `context.py`: content composition per page type (module overview, class detail), 3-tier LLM fallback with **enhanced Tier 3 natural language templates**, diagram embedding, **inline source links**, **Layer 1 Global Context Anchor** (glossary generation + hierarchical ordering + **hierarchical context system: repo/module/page-level context**), context budget management | 4d | T1.1, T1.2, T1.3, T1.3b | Reads from: `llm/provider.py` |

**Sprint 1 parallelism**: T1.2 and T1.3 can be developed in parallel after T1.1.

#### Sprint 2 (Week 2): Integration Layer

| Task | Description | Effort | Dependencies | Existing Code Touched |
|------|------------|--------|-------------|----------------------|
| T2.1 | `exporter.py`: JSON / Markdown string / Markdown file set output, **inline cross-reference auto-linking** (entity mentions → wiki page links), **inline source location links** (Mode A page-level + Mode B inline method links), **source_locations + method_locations in API response** | 2d | T1.4 | New: `wiki/exporter.py` |
| T2.2 | `POST /api/v1/wiki/generate` endpoint (sync mode), **source_locations in response** | 1d | T2.1 | Modify: `api/routes/` (add `wiki_routes.py`), register in main app |
| T2.3 | Async task model: task_id creation, `GET /wiki/tasks/{task_id}` polling, auto-detect sync vs async by scope size, **concurrency control** (max 5 concurrent tasks, task queue with priority) | 1.5d | T2.2 | Modify: `task/repo_task_manager.py` (extend task types) |
| T2.4 | SSE streaming: `Accept: text/event-stream` header detection, per-page event emission | 1d | T2.2 | New: streaming response in `wiki_routes.py` |
| T2.5 | `POST /api/v1/wiki/quick` endpoint: clone → index → generate pipeline, **P1 in-memory LRU cache** (cache_key = repo+scope+graph_version_hash) | 1.5d | T2.2, T2.3 | Reads from: existing index pipeline |
| T2.6 | MCP **3 tools** registration: `generate_wiki`, `get_wiki_page`, `list_wiki_pages` (search_wiki + ask_about_code deferred to P1.5 after search/ask modules exist) | 1d | T2.1 | Modify: `api/mcp_server.py` |
| T2.7 | Unit tests + integration tests + API tests | 2d | All above | New: `tests/wiki/` |

#### P1 Testing Strategy

> See **Section 8: Comprehensive Testing Plan** for full test case details, coverage requirements, and snapshot test strategy.

#### P1 Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| LLM rate limiting in `full` mode with many pages | Slow generation | Medium | Async model handles long waits; `structure` mode works without LLM |
| FalkorDB query performance for complex CONTAINS trees | Timeout | Low | P1 scope limited to module/class (not full repo) |
| Scope resolution ambiguity (path vs fqn) | Wrong nodes selected | Medium | Two-step resolution (exact path → fqn fallback) + user-facing error on zero matches |
| Cross-page terminology inconsistency | Poor doc quality | Medium | Layer 1 Global Context Anchor: glossary + hierarchical generation + style sheet |
| Context overflow for complex nodes (50+ methods) | Truncated / inaccurate pages | Medium | Layer 2 Per-Page Context Management: edge prioritization + method grouping + token budget |

#### P1 Success Criteria

- Generate accurate Wiki for a single module/class with correct Mermaid diagrams
- Work without LLM (structural mode)
- Existing indexed repos can trigger Wiki generation instantly
- Quick Wiki: new repo URL → auto index + generate in one call
- Streaming mode returns pages progressively via SSE

---

### P1.5 — Search + Ask + Hybrid Pipeline (~1.5 weeks)

P1.5 adds interactive capabilities that address the largest feature gap vs DeepWiki.

| Task | Description | Effort | Dependencies |
|------|------------|--------|-------------|
| T-S1 | Wiki Hybrid Search Pipeline: 3-path RRF fusion (Graph + Vector + FTS), Wiki FTS index on generated Markdown, RRF scoring with graph-weight ×2 | 2d | P1 complete |
| T-S2 | Graph-Aware Query Expansion: extract entities from query, expand via CALLS/INHERITS/IMPORTS edges, combine with LLM semantic expansion | 1d | T-S1 |
| T-S3 | Wiki Ask Feature: `POST /api/v1/wiki/ask` endpoint (SSE streaming), hybrid search integration, context assembly (Wiki page + graph + vector), conversation history management | 2d | T-S1 |
| T-S4 | Multi-language support: `language` parameter in WikiConfig, LLM prompt injection, Tier 3 template i18n (Chinese + English), glossary per-language caching | 1d | P1 complete |
| T-S5 | MCP **2 tools** registration: `search_wiki`, `ask_about_code` | 0.5d | T-S1, T-S3 |
| T-S6 | Tests: search pipeline tests, Ask API tests, MCP tool tests, multi-language snapshot tests | 1.5d | T-S1, T-S2, T-S3, T-S4, T-S5 |

#### P1.5 Success Criteria

- Hybrid search returns relevant results combining graph precision + semantic understanding
- Ask feature answers questions about code with source location references
- Graph-aware query expansion improves recall for entity-related queries
- Wiki generation supports Chinese and English output

---

### P2 — Full Repo + UI + Multi-Provider (~3 weeks)

#### Track Structure

P2 has three parallelizable tracks:

```
Track A: Full Repo Wiki        Track B: Multi-LLM Provider     Track C: Export + UI
─────────────────────          ────────────────────────          ──────────────
T-A1 compose_repo_wiki()      T-B1 Provider abstraction        T-C1 MD file export
T-A2 New page types (4)       T-B2 OpenAI + Azure direct       T-C2 Wiki cache layer
T-A3 Incremental update       T-B3 Custom compatible           T-C3 Dashboard Wiki page
                               T-B4 Provider config in API
```

**Track A and Track B are fully parallelizable.** Track C depends partially on Track A (directory tree needs full repo wiki).

#### Track A: Full Repo Wiki Generation

| Task | Description | Effort | Dependencies |
|------|------------|--------|-------------|
| T-A1 | `compose_repo_wiki()`: auto-detect top-level modules from graph, generate overview + per-module pages recursively, architecture layer classification | 2d | P1 composer |
| T-A2 | New page types — Repo Overview, Architecture Overview, API Reference, Data Flow — each with composition template + Mermaid integration | 3d | T-A1 |
| T-A3 | Incremental update: hook into `IncrementalIndexer` git diff results, determine affected Wiki pages by file→node mapping, regenerate only affected pages, **Layer 3 Incremental Consistency Guard** (glossary persistence + neighbor context injection + diff-aware regeneration) | 3.5d | T-A1 |

#### Track B: Multi-LLM Provider

| Task | Description | Effort | Dependencies |
|------|------------|--------|-------------|
| T-B1 | LLM provider abstraction refactoring: strategy/factory pattern, Gateway remains default | 1d | P1 llm/provider.py |
| T-B2 | OpenAI direct + Azure OpenAI integration (API key config, model selection) | 1.5d | T-B1 |
| T-B3 | Custom OpenAI-compatible endpoint support (base_url + api_key) | 0.5d | T-B1 |
| T-B4 | Provider config in wiki generate API (`llm_provider` field) + config file | 0.5d | T-B2, T-B3 |

**Backward compatibility**: Gateway remains the default provider. New providers are opt-in via API parameter or config.

#### Track C: Export + UI

| Task | Description | Effort | Dependencies |
|------|------------|--------|-------------|
| T-C1 | Markdown file set export: generate `docs/wiki/` directory with correct structure, relative links between pages | 1d | T-A1 |
| T-C2 | Wiki cache layer: cache key = `(repo, scope, graph_version)`, invalidate on re-index, avoid regenerating unchanged pages | 1.5d | T-A1 |
| T-C3 | Dashboard Wiki browse page: directory tree sidebar, Markdown renderer with Mermaid support (react-markdown + mermaid.js), permalink + breadcrumb navigation, **hybrid search integration** (server-side via P1.5 search API), **Ask sidebar** (chat with code using P1.5 Ask API), **IDE deep links** (source locations rendered as vscode/cursor/idea links, configurable editor URI template), **DeepResearch mode** (multi-turn investigation using MCP Agent path) | 5d | T-A1, T-C1, P1.5 |

#### P2 Testing Strategy

> See **Section 8: Comprehensive Testing Plan** for the unified testing approach. P2 adds:
> - Unit tests for each new page type template (snapshot-based)
> - Multi-provider adapter tests (mock HTTP per provider)
> - Incremental update integration tests (fixture-based before/after graph)
> - Cache layer integration tests (hit/miss/invalidate)
> - Dashboard E2E tests (Playwright)

#### P2 Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| Multi-LLM refactoring breaks existing enrichment | Regression | Medium | Backward-compatible: Gateway stays default, add providers as new classes |
| Full repo generation on large repos is slow | UX | Medium | Cache layer + incremental update + async model from P1 |
| Dashboard Wiki page complexity (tree + MD + Mermaid) | Over-budget | Medium | Use existing libraries (react-markdown, mermaid.js); defer styling to polish pass |
| Incremental update style drift (new vs old pages) | Inconsistent docs | Medium | Layer 3: diff-aware regeneration + glossary persistence + neighbor context injection |

#### P2 Success Criteria

- Generate complete Wiki for an entire repository with all 6 page types
- Support OpenAI/Azure direct + custom OpenAI-compatible endpoints
- Incremental: only regenerate Wiki pages for files changed since last index
- Dashboard: browse generated Wiki with working Mermaid diagrams
- Cache: second generation of unchanged scope returns instantly

---

### P3 — Automation (~2 weeks)

**Deliverables:**
- [ ] Webhook-triggered Wiki update on push/PR
- [ ] Scheduled Wiki regeneration (daily/weekly)
- [ ] Wiki diff: show what changed in Wiki between two commits
- [ ] Integration with code-review-bot: auto-attach relevant Wiki pages to PR

---

## 6. New Files Summary

| File | Purpose | Phase |
|------|---------|-------|
| `wiki/__init__.py` | Module init | P1 |
| `wiki/models.py` | Data models: WikiPage, WikiStructure, WikiConfig, ScopeParam, **SourceLocation** | P1 |
| `wiki/data_collector.py` | Per-page graph data collection + edge prioritization + **source location extraction** | P1 |
| `wiki/composer.py` | Content composition + 3-tier LLM fallback + **enhanced Tier 3 templates** + **inline source links** | P1 |
| `wiki/structure_planner.py` | Scope resolution + Wiki hierarchy from graph | P1 |
| `wiki/diagram_gen.py` | Deterministic Mermaid generation (3 diagram types) | P1 |
| `wiki/exporter.py` | Output formatting (MD/JSON/file set) + **cross-references** + **source location links** | P1 |
| `wiki/context.py` | **Hierarchical Context System**: repo/module/page-level context, glossary gen, arch summary, context budget | P1 |
| `wiki/cache.py` | **P1 in-memory LRU cache** (P2 adds persistent file-based cache) | P1 |
| `api/routes/wiki_routes.py` | REST endpoints: /generate, /quick, /tasks/{id}, SSE (P1); extended with /search, /ask in P1.5 | P1 |
| `tests/wiki/` | Unit + integration + API tests for wiki module | P1 |
| `wiki/search.py` | **3-path hybrid search pipeline**: RRF fusion, graph-aware query expansion | P1.5 |
| `wiki/ask.py` | **Wiki Ask Feature**: hybrid search + LLM generation + conversation history | P1.5 |
| `dashboard/src/pages/Wiki.tsx` | Wiki browse UI (tree + MD renderer + Mermaid + **Ask sidebar** + **IDE deep links**) | P2 |

### Existing Files Modified

| File | Modification | Phase |
|------|-------------|-------|
| `api/mcp_server.py` | Register **3 MCP tools** in P1 (generate_wiki, get_wiki_page, list_wiki_pages); **+2 tools** in P1.5 (search_wiki, ask_about_code) | P1 + P1.5 |
| `task/repo_task_manager.py` | Extend task types with wiki generation + **concurrency control** | P1 |
| `api/main.py` (or app init) | Register wiki_routes router | P1 |
| `query/hybrid_query_service.py` | Add **RRF fusion layer** for 3-path search | P1.5 |
| `llm/provider.py` | Refactor to strategy/factory pattern for multi-provider | P2 |

---

## 7. KBS Wiki vs DeepWiki — Final Comparison

### Advantages (KBS wins)

| Advantage | Detail |
|-----------|--------|
| **Diagram Accuracy** | 100% accurate — generated from real AST-parsed code relationships, not LLM guesses |
| **Incremental Updates** | Only regenerate pages for changed files (via git diff), not full rebuild |
| **Works Without LLM** | Structural mode with natural language templates provides readable docs without LLM |
| **Data Sovereignty** | Local embeddings (bge-m3) + local graph DB, no code sent to external APIs |
| **Function-Level Precision** | Wiki pages for individual functions showing callers, callees, parameter types |
| **Code Location Linking** | Every Wiki entity links to exact source file:line, enabling IDE deep links and agent navigation |
| **3-Path Hybrid Search** | Graph + Vector + FTS fusion (RRF) outperforms DeepWiki's vector-only and QMD's 2-path search |
| **Graph-Aware Query Expansion** | Query expansion using real code relationships, not just LLM guesses |
| **Engineering Integration** | 5 MCP tools + ACP Gateway + code-review-bot deep integration |
| **Multi-Tenancy** | Business-level graph isolation with RBAC |
| **Quick Wiki Mode** | For indexed repos: instant generation; for new repos: auto-index + generate |
| **Streaming Output** | SSE stream returns pages as they're generated for real-time progress |
| **Async Task Support** | Long-running generation uses task_id + polling, won't block clients |
| **Auto Cross-References** | Entity mentions in content auto-linked to corresponding wiki pages |
| **Lite Index Mode** | Quick Wiki returns initial result in <60s via top-level-only indexing |
| **Wiki Ask (Hybrid)** | Interactive Q&A with graph-enhanced retrieval; answers include source code references |
| **Hierarchical Context** | Repository/module/page-level context improves both generation quality and search relevance |
| **Wiki Structure Determinism** | Page structure derived from graph CONTAINS edges; identical input → identical structure |

### Disadvantages (DeepWiki wins)

| Disadvantage | Detail | Mitigation | Resolved By |
|-------------|--------|-----------|-------------|
| **Setup Complexity** | Requires FalkorDB + indexing | Quick Wiki mode + docker-compose one-click | P1 |
| **Time-to-First-Result** | Full indexing takes 5-10min for large repos vs DeepWiki's ~30s | Lite Indexing Mode: top-level structure only, <60s; full index async in background | P1 (Section 4.10) |
| **Frontend Polish** | P1 is API-only, no web UI | Dashboard Wiki browse page with Ask integration | P2 |
| **LLM Provider Variety** | Currently Gateway-only | Direct OpenAI/Azure + custom support | P2 |
| **Full Repo Docs** | P1 is module/class level only | compose_repo_wiki() + full page types | P2 |
| **Monitoring** | No wiki-specific metrics | Add wiki metrics: `wiki.generation.count`, `wiki.generation.latency_ms`, `wiki.generation.fallback_tier`, `wiki.search.latency_ms`, `wiki.cache.hit_rate`, `wiki.ask.tokens_used` | P2 |
| **Multi-Language Docs** | No i18n for generated documentation | Add `language` parameter to LLM prompt + template i18n | P2 |
| **Deploy Overhead** | More infrastructure than DeepWiki (FalkorDB + 3 services) | Inherent trade-off for accuracy; cannot fully eliminate | Accepted |
| **DeepResearch** | No multi-turn deep investigation like DeepWiki | MCP Agent path naturally supports multi-tool orchestration | P2 |
| **Custom Templates** | Fixed page structure, no user customization | Custom Jinja/Handlebars templates | P3+ |

---

## 8. Comprehensive Testing Plan

### 8.1 Test Framework & Infrastructure

| Item | Choice | Rationale |
|------|--------|-----------|
| Framework | pytest | Project standard |
| Async support | pytest-asyncio | Composer / API are async |
| Coverage tool | pytest-cov | Target: ≥80% per wiki module file |
| Snapshot testing | syrupy or inline snapshots | Diagram + composed page golden files |
| Fixture management | conftest.py per test directory | Shared graph data, mock providers |

### 8.2 Test Directory Structure

```
tests/wiki/
├── conftest.py                    # Shared fixtures: mock graph data, mock LLM provider
├── fixtures/
│   ├── graph_data.py              # Sample nodes, edges, structures
│   ├── expected_diagrams/         # Golden Mermaid files
│   └── expected_pages/            # Golden Markdown files
├── unit/
│   ├── test_models.py             # Data model validation
│   ├── test_diagram_gen.py        # Mermaid generation
│   ├── test_structure_planner.py  # Scope resolution + tree
│   ├── test_data_collector.py     # Data collection + prioritization
│   ├── test_context.py            # Glossary, budget, anchor
│   ├── test_composer.py           # Content composition + fallback
│   ├── test_exporter.py           # Output formatting
│   ├── test_cache.py              # LRU cache hit/miss/invalidation/eviction
│   ├── test_search.py             # RRF fusion, graph expansion, FTS index
│   └── test_ask.py                # Ask pipeline, streaming, conversation
├── integration/
│   ├── test_pipeline.py           # Full pipeline: scope → wiki
│   ├── test_quick_flow.py         # Auto-index + generate
│   └── test_search_pipeline.py    # 3-path fusion end-to-end
├── api/
│   ├── test_wiki_routes.py        # REST endpoints (generate, quick, tasks)
│   ├── test_streaming.py          # SSE streaming
│   ├── test_async_tasks.py        # Async task model
│   ├── test_search_api.py         # Search REST endpoint (P1.5)
│   └── test_ask_api.py            # Ask REST endpoint (P1.5)
└── mcp/
    └── test_mcp_wiki_tool.py      # MCP tool registration + invoke (all 5 tools)
```

### 8.3 Unit Test Cases

#### test_models.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_scope_parse_repo` | `"repo"` | `ScopeParam(type="repo", value=None)` |
| `test_scope_parse_module` | `"module:src/service.py"` | `ScopeParam(type="module", value="src/service.py")` |
| `test_scope_parse_class` | `"class:com.example.UserService"` | `ScopeParam(type="class", value="com.example.UserService")` |
| `test_scope_parse_invalid` | `"invalid"` | `raises ValueError` |
| `test_scope_parse_empty_value` | `"module:"` | `raises ValueError` |
| `test_wiki_page_to_json` | `WikiPage(...)` | Valid JSON with all fields |
| `test_wiki_page_to_markdown` | `WikiPage(...)` | Markdown string with title + content + diagrams |
| `test_wiki_structure_ordering` | Nested structure | Children sorted alphabetically |

#### test_diagram_gen.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_class_diagram_simple` | Class with 3 methods, no inheritance | Valid Mermaid classDiagram |
| `test_class_diagram_inheritance` | Class extending 2 parents | `<\|--` arrows for each parent |
| `test_class_diagram_deep_chain` | 4-level inheritance | All levels connected |
| `test_class_diagram_many_methods` | Class with 50 methods | Methods listed (may be grouped) |
| `test_dependency_graph_basic` | Module with 5 imports | Flowchart with arrows |
| `test_dependency_graph_circular` | Modules A→B→C→A | All edges shown, no infinite loop |
| `test_call_flowchart_linear` | A→B→C call chain | Correct linear flowchart |
| `test_call_flowchart_branching` | A→B, A→C | Branching shown |
| `test_empty_edges` | No edges | Returns minimal valid diagram or empty string |
| `test_mermaid_syntax_valid` | Any diagram | Mermaid syntax parseable (no broken arrows) |
| `test_special_chars_escaped` | Node name with `<`, `>`, `&` | Characters escaped in Mermaid |

#### test_structure_planner.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_resolve_module_by_path` | `"module:src/service.py"` + graph with matching node | Correct module node returned |
| `test_resolve_class_by_fqn` | `"class:com.example.UserService"` | Correct class node |
| `test_resolve_fallback_path_to_fqn` | Path not found, fqn matches | Fallback succeeds |
| `test_resolve_no_match` | No matching node | `raises WikiScopeError` |
| `test_build_page_tree_flat` | Module with 5 direct children | Flat list of 5 pages |
| `test_build_page_tree_nested` | Module with nested sub-modules | Hierarchical tree |
| `test_repo_scope_lists_modules` | `"repo"` | All top-level Module nodes as pages |

#### test_data_collector.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_collect_class_data` | Class node ID | PageData with methods, fields, edges |
| `test_collect_module_data` | Module node ID | PageData with contained classes/functions |
| `test_edge_prioritization` | Node with 50 edges of mixed types | INHERITS first, then CALLS(top-10), then IMPORTS(top-10) |
| `test_neighbor_truncation` | Node with 20 neighbors | Top-5 full detail, rest summarized |
| `test_method_grouping` | Class with 30 methods | Methods grouped into categories |
| `test_empty_node` | Node with no edges | PageData with empty edges list |

#### test_context.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_glossary_generation_with_llm` | Module list + mock LLM | Glossary dict with terms + abbreviations |
| `test_glossary_generation_structural` | Module list, no LLM | Structural glossary (module names as terms) |
| `test_context_budget_within_limit` | Small node (~2000 tokens) | No truncation |
| `test_context_budget_exceeds_limit` | Large node (~15000 tokens) | Truncated to budget with "... and N more" |
| `test_hierarchical_context_injection` | Parent summary + child data | Context includes parent summary prefix |
| `test_style_sheet_template` | Any | Returns consistent section order + tone rules |

#### test_composer.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_fallback_tier1_summary_exists` | Node with business_summary | Uses business_summary directly |
| `test_fallback_tier2_llm_available` | No summary, LLM available | Calls LLM, uses result |
| `test_fallback_tier3_structural` | No summary, no LLM | Structural description generated |
| `test_module_overview_page` | Module PageData | Markdown with: title, description, class list, imports, diagram |
| `test_class_detail_page` | Class PageData | Markdown with: title, description, methods, inheritance, callers/callees, diagram |
| `test_compose_with_glossary` | PageData + glossary context | Glossary terms injected in system prompt |
| `test_compose_with_parent_summary` | PageData + parent summary | Parent summary in context |
| `test_compose_structure_mode` | mode="structure" | No LLM calls made, structural output |
| `test_compose_full_mode` | mode="full" + mock LLM | LLM called for descriptions |
| `test_tier3_natural_language_template_module` | Module node, no LLM | Natural language description with relationships |
| `test_tier3_natural_language_template_class` | Class node, no LLM | Natural language description mentioning inheritance, methods, callers |
| `test_tier3_includes_relationship_info` | Node with edges, no LLM | Description includes "inherits from", "calls", "called by" |

#### test_exporter.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_export_json` | List of WikiPages | Valid JSON with pages + structure + stats |
| `test_export_markdown_single` | Single WikiPage | Markdown string with title + content + diagrams |
| `test_export_markdown_fileset` | WikiPages + output dir | Files created with correct structure |
| `test_export_relative_links` | Pages with cross-references | Links use relative paths (`../module/class.md`) |

#### test_cache.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_cache_hit` | Same (repo, scope, mode, version) twice | Second call returns cached result |
| `test_cache_miss_different_scope` | Different scope | Cache miss, fresh generation |
| `test_cache_miss_different_mode` | Same scope, different mode | Cache miss (mode is part of key) |
| `test_cache_invalidation_on_reindex` | Reindex changes graph_version | Old entries invalidated |
| `test_cache_lru_eviction` | Insert >100 entries | Oldest entry evicted |
| `test_cache_key_composition` | Various inputs | Key = (repo, scope, mode, version_hash) |
| `test_cache_concurrent_access` | Parallel reads/writes | No race conditions |

#### test_search.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_rrf_fusion_scoring` | 3 ranked lists | Correct RRF formula: Σ(weight × 1/(k+rank+1)) |
| `test_rrf_top_rank_bonus` | #1 result | Receives +0.05 bonus |
| `test_graph_query_expansion` | Query with entity name | Expands with CALLS/INHERITS neighbors |
| `test_graph_expansion_no_entity` | Query without entity | Returns original query only |
| `test_fts_index_build` | Generated Wiki pages | FTS index created and searchable |
| `test_3path_parallel_execution` | Any query | All 3 paths execute concurrently |
| `test_graph_path_weight_2x` | Graph + Vector same rank | Graph scored 2× higher |
| `test_fts_path_weight_1_5x` | FTS + Vector same rank | FTS scored 1.5× higher |
| `test_search_empty_results` | Non-matching query | Empty list returned |
| `test_search_respects_limit` | limit=5 | At most 5 results |
| `test_search_min_score_filter` | min_score=0.5 | Only results with score ≥ 0.5 |

#### test_ask.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_ask_returns_streaming` | Valid question | SSE stream with delta events |
| `test_ask_includes_sources` | Question about class | Response contains source_locations |
| `test_ask_conversation_history` | Follow-up with conversation_id | Context-aware answer |
| `test_ask_conversation_ttl` | Expired conversation_id | Treated as new conversation |
| `test_ask_max_turns` | >10 turns | Oldest turns evicted |
| `test_ask_scoped_search` | Question + scope | Search limited to scope |
| `test_ask_hybrid_context` | Question | Context includes Wiki + graph + vector results |
| `test_ask_no_llm_fallback` | LLM unavailable | Graceful error, no crash |

### 8.4 Integration Test Cases

| Test Case | Scope | Description | Requires |
|-----------|-------|-------------|----------|
| `test_pipeline_module_structure_mode` | Module | Full pipeline, structure mode, no LLM | FalkorDB test fixtures |
| `test_pipeline_class_full_mode` | Class | Full pipeline, full mode, mock LLM | FalkorDB + mock LLM |
| `test_pipeline_repo_scope` | Repo | Lists all modules as pages | FalkorDB |
| `test_pipeline_large_module` | Module with >20 classes | Context budget + method grouping applied | FalkorDB |
| `test_pipeline_hierarchical_context` | Multi-level module | Parent summaries injected correctly | FalkorDB + mock LLM |
| `test_quick_flow_new_repo` | New repo URL | Clone → index → generate | Mock git clone + mock index |
| `test_quick_flow_indexed_repo` | Already indexed | Skips indexing, generates directly | FalkorDB |

### 8.5 API Test Cases

| Test Case | Endpoint | Scenario | Expected Status |
|-----------|----------|----------|----------------|
| `test_generate_sync_200` | POST /wiki/generate | Valid module scope | 200 with pages + source_locations |
| `test_generate_async_202` | POST /wiki/generate | Repo scope (large) | 202 with task_id |
| `test_generate_streaming` | POST /wiki/generate | Accept: text/event-stream | SSE events in order |
| `test_generate_invalid_scope_400` | POST /wiki/generate | `scope="invalid"` | 400 |
| `test_generate_repo_not_found_404` | POST /wiki/generate | Unknown repo | 404 |
| `test_generate_falkordb_down_503` | POST /wiki/generate | FalkorDB unavailable | 503 |
| `test_generate_llm_degraded` | POST /wiki/generate | mode=full, LLM down | 200 with degraded=true |
| `test_generate_source_locations` | POST /wiki/generate | Valid class scope | 200 with source_locations containing file_path + line numbers |
| `test_generate_method_locations` | POST /wiki/generate | Class with methods | 200 with method_locations for each method |
| `test_generate_cache_hit` | POST /wiki/generate | Same scope twice | Second call returns cached result |
| `test_generate_concurrency_limit` | POST /wiki/generate | 6 concurrent requests | 5 accepted, 1 queued |
| `test_task_polling_lifecycle` | GET /wiki/tasks/{id} | pending → running → completed | 200 at each stage |
| `test_task_not_found_404` | GET /wiki/tasks/{id} | Unknown task_id | 404 |
| `test_quick_201` | POST /wiki/quick | Valid git_url | 200/202 |
| `test_quick_invalid_url_400` | POST /wiki/quick | Malformed URL | 400 |
| `test_ask_streaming` | POST /wiki/ask | Valid question + scope | SSE stream with answer + sources |
| `test_ask_with_conversation` | POST /wiki/ask | Follow-up question with conversation_id | Context-aware response |
| `test_ask_source_references` | POST /wiki/ask | Question about specific class | Response includes source_locations |

### 8.6 MCP Tool Test Cases

| Test Case | Description | Expected |
|-----------|-------------|----------|
| `test_all_tools_registered` | MCP server started | All 5 tools in tool list: generate_wiki, search_wiki, get_wiki_page, list_wiki_pages, ask_about_code |
| `test_generate_wiki_valid` | Valid repo + scope + mode | Returns WikiPage list with source_locations |
| `test_generate_wiki_invalid_scope` | Invalid scope string | Error response with detail |
| `test_search_wiki_hybrid` | Valid query, mode=hybrid | Returns ranked results with scores + context |
| `test_search_wiki_graph_only` | Valid query, mode=graph | Returns graph-based results only |
| `test_get_wiki_page_exists` | Valid scope for generated page | Returns page content + diagrams + source_locations |
| `test_get_wiki_page_not_found` | Invalid scope | Error with similar page suggestions |
| `test_list_wiki_pages` | Valid repo | Returns directory tree with metadata |
| `test_ask_about_code` | Valid question + repo | Returns streaming answer with source references |
| `test_tool_error_propagation` | FalkorDB down | Error propagated to MCP client |

### 8.7 Snapshot Tests (Golden Files)

| File | Content | Purpose |
|------|---------|---------|
| `fixtures/expected_diagrams/class_simple.mmd` | Mermaid classDiagram for simple class | Regression prevention |
| `fixtures/expected_diagrams/dependency_graph.mmd` | Mermaid flowchart for module deps | Regression prevention |
| `fixtures/expected_diagrams/call_flowchart.mmd` | Mermaid flowchart for call chain | Regression prevention |
| `fixtures/expected_pages/module_overview.md` | Complete module overview page | Output format stability |
| `fixtures/expected_pages/class_detail.md` | Complete class detail page | Output format stability |

### 8.8 Coverage Requirements

| Module | Minimum Coverage | Rationale |
|--------|-----------------|-----------|
| `wiki/models.py` | 95% | Data models must be fully validated |
| `wiki/diagram_gen.py` | 90% | Core differentiator — accuracy critical |
| `wiki/structure_planner.py` | 85% | Scope resolution edge cases |
| `wiki/data_collector.py` | 85% | Data collection paths |
| `wiki/context.py` | 80% | LLM-dependent code harder to fully cover |
| `wiki/composer.py` | 80% | 3-tier fallback paths all tested |
| `wiki/exporter.py` | 90% | Output format correctness + source links |
| `wiki/cache.py` | 90% | Cache hit/miss/invalidation paths |
| `wiki/search.py` | 85% | RRF fusion + query expansion paths |
| `wiki/ask.py` | 80% | Streaming + conversation paths |
| `api/routes/wiki_routes.py` | 80% | All endpoints + error paths |
| **Overall wiki module** | **≥80%** | **Project quality gate** |

---

## 9. Execution Strategy — Subagent-Driven + TDD

### 9.1 TDD Workflow (per task)

Every implementation task follows the RED → GREEN → REFACTOR cycle:

```
┌─────────┐     ┌─────────┐     ┌───────────┐     ┌────────┐
│   RED   │────→│  GREEN  │────→│ REFACTOR  │────→│ VERIFY │
│ Write   │     │ Minimal │     │ Clean up  │     │ Coverage│
│ failing │     │ impl to │     │ keeping   │     │ ≥80%   │
│ tests   │     │ pass    │     │ tests     │     │ No lint │
└─────────┘     └─────────┘     │ green     │     │ errors │
                                └───────────┘     └────────┘
```

**RED phase**: Write test file first. Tests must fail (import errors are acceptable at this stage).
**GREEN phase**: Write minimal implementation to make all tests pass.
**REFACTOR phase**: Clean up code, extract helpers, improve naming — tests must stay green.
**VERIFY phase**: `pytest --cov=wiki tests/wiki/ --cov-fail-under=80` + `ruff check wiki/`

### 9.2 Subagent Dispatch Plan — P1

```
Phase 1: Sequential Foundation
═══════════════════════════════
Subagent-0: T1.1 Data Models [sequential, 0.5d]
  TDD: tests/wiki/unit/test_models.py → wiki/models.py
  Gate: all model tests pass

Phase 2: Parallel Foundation
═══════════════════════════════
┌──────────────────────────────┐  ┌──────────────────────────────┐
│ Subagent-1: T1.2 DiagramGen │  │ Subagent-2: T1.3 Structure   │
│ [parallel, 2d]               │  │ Planner [parallel, 2d]       │
│                              │  │                              │
│ TDD:                         │  │ TDD:                         │
│  test_diagram_gen.py         │  │  test_structure_planner.py   │
│  → diagram_gen.py            │  │  → structure_planner.py      │
│                              │  │                              │
│ Gate: diagram tests pass     │  │ Gate: planner tests pass     │
│       coverage ≥90%          │  │       coverage ≥85%          │
└──────────────────────────────┘  └──────────────────────────────┘

Phase 3: Sequential Core
═══════════════════════════════
Subagent-3: T1.3b DataCollector [sequential, 1d]
  TDD: test_data_collector.py → data_collector.py
  Gate: collector tests pass, coverage ≥85%

Subagent-4: T1.4 Composer + Context [sequential, 3d]
  TDD: test_context.py → context.py
       test_composer.py → composer.py
  Gate: composer + context tests pass, 3-tier fallback verified

Phase 4: Integration
═══════════════════════════════
Subagent-5: T2.1 Exporter [1d]
  TDD: test_exporter.py → exporter.py

┌──────────────────────────────┐  ┌──────────────────────────────┐
│ Subagent-6: T2.2-T2.4       │  │ Subagent-7: T2.6 MCP 3 Tools│
│ API Layer [3d]               │  │ [parallel, 1d]               │
│                              │  │                              │
│ TDD:                         │  │ TDD:                         │
│  test_wiki_routes.py         │  │  test_mcp_wiki_tool.py       │
│  test_streaming.py           │  │  → 3 tools: generate_wiki,   │
│  test_async_tasks.py         │  │    get_wiki_page,            │
│  → wiki_routes.py            │  │    list_wiki_pages           │
│                              │  │                              │
│ Gate: API tests pass         │  │ Gate: MCP tests pass         │
└──────────────────────────────┘  └──────────────────────────────┘

Subagent-8: T2.5 Quick Endpoint [1d]
  TDD: test_quick_flow.py → quick endpoint
  Gate: quick flow tests pass

Phase 5: Final P1 Verification
═══════════════════════════════
Subagent-9: Integration + Coverage Audit [1.5d]
  - Run ALL tests: pytest tests/wiki/ --cov=wiki --cov-fail-under=80
  - Run full project test suite (regression check)
  - Generate coverage report
  - Fix any coverage gaps
  Gate: overall coverage ≥80%, zero regressions, zero lint errors

Phase 6: P1.5 — Search + Ask + Hybrid Pipeline
═══════════════════════════════════════════════
┌──────────────────────────────┐  ┌──────────────────────────────┐
│ Subagent-10: T-S1+T-S2      │  │ Subagent-11: T-S4            │
│ Hybrid Search Pipeline [3d]  │  │ Multi-language [1d]           │
│                              │  │                              │
│ TDD:                         │  │ TDD:                         │
│  test_search.py              │  │  test_multilang.py           │
│  → search.py (RRF fusion)   │  │  → language params + templates│
│  → query expansion           │  │                              │
│                              │  │ Gate: i18n tests pass        │
│ Gate: search tests pass      │  │                              │
│       coverage ≥85%          │  │                              │
└──────────────────────────────┘  └──────────────────────────────┘

Subagent-12: T-S3 Wiki Ask Feature [2d]
  TDD: test_ask.py → ask.py
  Gate: ask tests pass, streaming verified, source refs included

Subagent-13: T-S5 MCP 2 Tools (search_wiki + ask_about_code) [0.5d]
  TDD: extend test_mcp_wiki_tool.py → register 2 remaining MCP tools
  Gate: all 5 MCP tools registered and tested

Subagent-14: T-S6 P1.5 Integration Tests [1.5d]
  - Run ALL P1 + P1.5 tests
  - Verify search + ask integration
  Gate: overall coverage ≥80%, zero regressions
```

### 9.3 Quality Gates

Each subagent must pass ALL gates before the next dependent subagent starts:

| Gate | Check | Tool |
|------|-------|------|
| Tests pass | All new tests green | `pytest tests/wiki/unit/test_<module>.py -v` |
| Coverage | ≥80% (module-specific targets in 8.8) | `pytest --cov=wiki/<module>.py --cov-fail-under=<target>` |
| Lint clean | No new linter errors | `ruff check wiki/` |
| No regressions | Existing test suite still passes | `pytest tests/ --ignore=tests/wiki/` |
| Snapshot stable | Golden files match or explicitly updated | `pytest tests/wiki/ --snapshot-update` (only if intentional) |

### 9.4 Branch Strategy

```
main
 └── feat/wiki-generation (integration branch)
      ├── feat/wiki-models        (Subagent-0)
      ├── feat/wiki-diagram-gen   (Subagent-1)
      ├── feat/wiki-planner       (Subagent-2)
      ├── feat/wiki-collector     (Subagent-3)
      ├── feat/wiki-composer      (Subagent-4)
      ├── feat/wiki-exporter      (Subagent-5)
      ├── feat/wiki-api           (Subagent-6)
      ├── feat/wiki-mcp           (Subagent-7)
      ├── feat/wiki-quick         (Subagent-8)
      ├── feat/wiki-integration   (Subagent-9: P1 merge + verify)
      ├── feat/wiki-search        (Subagent-10: P1.5 hybrid search)
      ├── feat/wiki-i18n          (Subagent-11: P1.5 multi-language)
      ├── feat/wiki-ask           (Subagent-12: P1.5 ask feature)
      ├── feat/wiki-mcp-p15      (Subagent-13: P1.5 MCP 2 tools)
      └── feat/wiki-p15-integration (Subagent-14: P1.5 merge + verify)
```

- Parallel subagents work in isolated git worktrees
- Each subagent commits to its feature branch
- Integration subagent (Subagent-9) merges all branches and runs full suite
- Final PR: `feat/wiki-generation` → `main`

### 9.5 Subagent Communication Protocol

| Event | Action |
|-------|--------|
| Subagent completes | Update spec checklist (`[ ]` → `[x]`), report coverage % |
| Subagent fails tests | Fix in-place, do NOT proceed to next task |
| Dependency ready | Next subagent can start (check gate status) |
| All subagents done | Integration subagent runs full verification loop |
| Integration passes | Create PR with full test report |
