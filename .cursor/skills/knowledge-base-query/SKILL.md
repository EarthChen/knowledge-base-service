---
name: knowledge-base-query
description: Query and operate the Knowledge Base Service for code context, graph traversal, file content, wiki pages, domain management, AI editing, and architecture insights. Use when the user asks to search code, explore call chains, read source files, browse wiki, edit wiki pages via AI, manage domains, check architecture, analyze PR impact, or get context from the knowledge graph. Triggers on keywords like "knowledge base", "search code", "call chain", "graph query", "wiki", "code context", "file content", "domain", "edit wiki", "ask wiki", "index repo".
---

# Knowledge Base Service — Agent Skill

Interact with the Knowledge Base Service (FalkorDB graph + vector hybrid) via REST API or MCP tools.

## Setup

```bash
export KB_BASE_URL="http://localhost:8100"   # Service address
export KB_TOKEN="your-token"                  # Auth token (if REQUIRE_AUTH=true)
export KB_BUSINESS_ID="default"               # Multi-tenant business ID
```

Verify: `bash .cursor/skills/knowledge-base-query/scripts/kb_setup.sh check`

Auth header: `Authorization: Bearer $KB_TOKEN` + `X-Business-Id: $KB_BUSINESS_ID`

## Two Access Modes

### 1. MCP Tool Call (unified dispatch)

```bash
python .cursor/skills/knowledge-base-query/scripts/kb_query.py <tool_name> --arg key=value
# or with JSON:
python .cursor/skills/knowledge-base-query/scripts/kb_query.py <tool_name> --json-args '{"query":"login","k":5}'
```

Available tools: `rag_query`, `rag_graph`, `documents`, `get_code_snippet`, `analyze_code`, `search_architecture`, `analyze_changes`, `get_complete_context`, `get_insights`, `index_freshness`, `get_file_content`, `graph_path`, `get_wiki_page`, `list_wiki_pages`, `wiki_search`, `wiki_get_tree`, `wiki_get_related`, `wiki_get_domain_overview`, `wiki_get_snapshot`, `wiki_find_implementing_modules`, `unified_knowledge_query`, `wiki_export`

### 2. Direct REST API

For full API reference, see [references/rest-api.md](references/rest-api.md). Key endpoint groups:

| Group | Base Path | Auth |
|-------|-----------|------|
| Graph/Stats | `/api/v1/stats`, `/api/v1/graph/*` | VIEWER |
| Search | `/api/v1/hybrid`, `/api/v1/deep-search` | VIEWER |
| Files | `/api/v1/files/*` | VIEWER |
| Wiki Pages | `/api/v1/wiki/pages/*`, `/api/v1/wiki/tree` | VIEWER |
| Wiki Ask (AI Q&A) | `/api/v1/wiki/ask` | VIEWER |
| Wiki Edit (AI) | `/api/v1/wiki/pages/{uid}/edit-session/*` | EDITOR |
| Wiki Domains | `/api/v1/wiki/domains/hierarchy/*` | VIEWER |
| Indexing | `/api/v1/index` | EDITOR |
| Business Mgmt | `/api/v1/businesses` | EDITOR for mutations |

## Common Workflows

### Search Code → Read Source

```bash
# Hybrid search
python scripts/kb_query.py rag_query --arg query="authentication handler" --arg k=5 --arg repository=my-service

# Read file
python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth/handler.py

# Read specific lines
python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth/handler.py --arg start_line=10 --arg end_line=50
```

### Trace Call Chains

```bash
# Downstream (who does this function call?)
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=downstream --arg depth=3

# Upstream (who calls this function?)
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=upstream
```

### Graph Queries (`rag_graph` query_types)

`call_chain`, `inheritance_tree`, `class_methods`, `module_dependencies`, `reverse_dependencies`, `find_entity`, `file_entities`, `graph_stats`, `raw_cypher`, `business_flow`, `flows_for_function`, `related_concepts`, `explore_domain`, `flow_dependencies`, `blast_radius`

### Browse Wiki

```bash
# Get wiki tree
python scripts/kb_query.py wiki_get_tree --arg business_id=$KB_BUSINESS_ID

# Get specific page
python scripts/kb_query.py get_wiki_page --arg scope=path/to/page --arg repository=$KB_BUSINESS_ID

# Search wiki
python scripts/kb_query.py wiki_search --arg query="authentication flow" --arg repository=$KB_BUSINESS_ID
```

### Wiki REST API Workflows

```bash
# Page by path
curl "$KB_BASE_URL/api/v1/wiki/pages/by-path?business_id=$KB_BUSINESS_ID&path=__domains__/auth/_overview" \
  -H "Authorization: Bearer $KB_TOKEN"

# Domain tree
curl "$KB_BASE_URL/api/v1/wiki/domain-tree?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"

# AI Ask (SSE stream)
curl -X POST "$KB_BASE_URL/api/v1/wiki/ask/stream" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repository":"'$KB_BUSINESS_ID'","question":"How does auth work?","mode":"concise"}'
```

### AI Wiki Edit Session

```bash
# Create edit session
curl -X POST "$KB_BASE_URL/api/v1/wiki/pages/$PAGE_UID/edit-session" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"instruction":"Add a section about error handling"}'

# Stream SSE events
curl "$KB_BASE_URL/api/v1/wiki/pages/$PAGE_UID/edit-session/$SESSION_ID/stream" \
  -H "Authorization: Bearer $KB_TOKEN"

# Apply edit
curl -X POST "$KB_BASE_URL/api/v1/wiki/pages/$PAGE_UID/edit-session/$SESSION_ID/apply" \
  -H "Authorization: Bearer $KB_TOKEN"
```

### PR Impact Analysis

```bash
python scripts/kb_query.py analyze_changes --arg mode=wiki_pr_impact \
  --arg repository=my-service --arg changed_files='["src/auth.py","src/db.py"]'
```

### Architecture Inspection

```bash
# List endpoints
python scripts/kb_query.py search_architecture --arg mode=endpoints --arg repository=my-service

# Architecture layers
python scripts/kb_query.py search_architecture --arg mode=layers --arg layer=business --arg repository=my-service

# Graph insights
curl "$KB_BASE_URL/api/v1/graph/insights/my-service?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"
```

### Index a Repository

```bash
curl -X POST "$KB_BASE_URL/api/v1/index" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"directory":"/path/to/repo","business_id":"'$KB_BUSINESS_ID'","mode":"full"}'
```

## Notes

- `get_file_content` has a 512KB cap; use `start_line`/`end_line` for large files
- `raw_cypher` is available via `rag_graph` for power-users
- Wiki pages use `WikiPage:{business_id}:{path}` as UIDs
- Domain hierarchy mutations require `business_id` query param
- Edit sessions require EDITOR role; Ask sessions only need VIEWER
- SSE streams use `text/event-stream` content type
