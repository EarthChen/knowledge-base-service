---
name: knowledge-base-query
description: Query the Knowledge Base Service for code context, graph traversal, file content, wiki, and architecture insights. Use when the user asks to search code, explore call chains, read source files, check architecture, or get context from the knowledge graph. Triggers on keywords like "knowledge base", "search code", "call chain", "graph query", "wiki", "code context", "file content".
---

# Knowledge Base Query

Query the project's Knowledge Base Service (FalkorDB graph + vector hybrid search) via its **MCP HTTP API**. The main manifest exposes **20** tools (12 core + 8 wiki, merged in `api/mcp_server.py` from `MCP_TOOLS_MANIFEST` + `WIKI_MCP_TOOLS_MANIFEST`). A separate **optional** Wiki HTTP surface (`WIKI__MCP_SERVER_ENABLED`) adds **6** more tools on `/api/v1/mcp/tools/*` — not duplicates of the 20; see project `docs/MCP-INTEGRATION.md`.

## Prerequisites

Set environment variables before calling scripts:

```bash
export KB_BASE_URL="http://localhost:8100"  # KB service address (default PORT in README)
export KB_TOKEN="your-token"                 # Auth token (if REQUIRE_AUTH=true)
export KB_BUSINESS_ID="default"              # Multi-tenant graph ID
```

Verify connectivity:

```bash
bash scripts/kb_setup.sh check
```

## Quick Reference

### Script Usage

```bash
python scripts/kb_query.py <tool_name> --arg key=value [--arg key2=value2 ...]
```

Or with JSON arguments:

```bash
python scripts/kb_query.py <tool_name> --json-args '{"query": "login", "k": 5}'
```

### Main MCP tools (20) — `POST /api/v1/mcp/tool` with `tool_name` + `arguments`

| # | Tool | Purpose |
|---|------|---------|
| 1 | `rag_query` | Hybrid search (semantic + keyword + BM25) |
| 2 | `rag_graph` | Structured graph queries (`query_type`, …) |
| 3 | `documents` | List / get indexed documentation |
| 4 | `get_code_snippet` | Entity source by graph `node_uid` |
| 5 | `analyze_code` | Quality or index vs disk `consistency` |
| 6 | `search_architecture` | Layers or `endpoints` |
| 7 | `analyze_changes` | `pr_review`, `impact`, `impact_scope`, `wiki_pr_impact` |
| 8 | `get_complete_context` | Full entity context bundle |
| 9 | `get_insights` | Dashboard / graph insights |
| 10 | `index_freshness` | Index stamp and counts for a repo |
| 11 | `get_file_content` | Raw file read (optional line range) |
| 12 | `graph_path` | Shortest path between two entities |
| 13 | `get_wiki_page` | Generated wiki page by scope |
| 14 | `list_wiki_pages` | Wiki page tree |
| 15 | `wiki_search` | Hybrid wiki search |
| 16 | `wiki_export` | Export markdown to disk (Editor) |
| 17 | `wiki_get_tree` | Business wiki tree |
| 18 | `wiki_get_related` | Cross-references for a page |
| 19 | `wiki_get_domain_overview` | Domain overview |
| 20 | `wiki_get_snapshot` | Compiled wiki snapshot (main MCP) |

### Optional Wiki HTTP MCP (6) — `POST /api/v1/mcp/tools/call` with `name` + `arguments`

`wiki_search`, `wiki_explain`, `wiki_navigate`, `wiki_qa`, `wiki_impact`, `wiki_get_snapshot` — see `api/mcp_wiki_server.py` `TOOL_DEFINITIONS`.

### Graph `query_type` (for `rag_graph`)

`call_chain`, `inheritance_tree`, `class_methods`, `module_dependencies`, `reverse_dependencies`, `find_entity`, `file_entities`, `graph_stats`, `raw_cypher`, `business_flow`, `flows_for_function`, `related_concepts`, `explore_domain`, `flow_dependencies`, `blast_radius`, …

## Common Workflows

### 1. Search → Read Full Source

```bash
python scripts/kb_query.py rag_query --arg query="login authentication" --arg k=5 --arg repository=my-service

python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth/handler.py

python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth/handler.py --arg start_line=10 --arg end_line=50
```

### 2. Trace Call Chain

```bash
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=upstream --arg depth=3

python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=downstream
```

### 3. Change Impact

```bash
python scripts/kb_query.py rag_graph --arg query_type=blast_radius --arg name=processPayment --arg depth=3 --arg repository=my-service
```

### 4. Architecture

```bash
python scripts/kb_query.py search_architecture --arg mode=endpoints --arg repository=my-service

python scripts/kb_query.py search_architecture --arg mode=layers --arg layer=business --arg repository=my-service
```

## Notes

- Scripts use Python standard library only in-repo; see `scripts/kb_query.py`
- `get_file_content` has a 512KB cap; use `start_line`/`end_line` for large files
- **Indexing** is via Dashboard or **`POST /api/v1/index`** (HTTP, Editor). `handle_rag_index` exists server-side but **`rag_index` is not in `MCP_TOOLS_MANIFEST`**
- For graph power-users, `raw_cypher` is available on `rag_graph`
