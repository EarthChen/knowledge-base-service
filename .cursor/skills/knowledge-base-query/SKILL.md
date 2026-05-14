---
name: knowledge-base-query
description: Query the Knowledge Base Service for code context, graph traversal, file content, wiki pages, domain structure, and architecture insights. Use when the user asks to search code, explore call chains, read source files, browse wiki, check architecture, or get context from the knowledge graph. Triggers on keywords like "knowledge base", "search code", "call chain", "graph query", "wiki", "code context", "file content", "domain tree", "architecture".
---

# Knowledge Base Query

Query the project's Knowledge Base Service (FalkorDB graph + vector hybrid) via MCP tools or REST API. Read-only operations only.

## Setup

```bash
export KB_BASE_URL="http://localhost:8100"
export KB_TOKEN="your-token"                 # if REQUIRE_AUTH=true
export KB_BUSINESS_ID="default"
```

Verify: `bash .cursor/skills/knowledge-base-query/scripts/kb_setup.sh check`

## MCP Tool CLI

```bash
python .cursor/skills/knowledge-base-query/scripts/kb_query.py <tool_name> --arg key=value
```

## Workflows

### 1. Search Code → Read Source

```bash
# Hybrid search
python scripts/kb_query.py rag_query --arg query="login handler" --arg k=5 --arg repository=my-service

# Read file content
python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth.py

# Read specific lines (512KB cap)
python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth.py --arg start_line=10 --arg end_line=50

# Entity source by graph UID
python scripts/kb_query.py get_code_snippet --arg node_uid="Function:my-service:handleLogin"
```

### 2. Trace Call Chains & Dependencies

```bash
# Downstream calls
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=downstream --arg depth=3

# Upstream callers
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=upstream

# Module dependencies
python scripts/kb_query.py rag_graph --arg query_type=module_dependencies --arg name=auth_service

# Reverse dependencies
python scripts/kb_query.py rag_graph --arg query_type=reverse_dependencies --arg name=UserRepository

# Inheritance tree
python scripts/kb_query.py rag_graph --arg query_type=inheritance_tree --arg name=BaseHandler

# Blast radius
python scripts/kb_query.py rag_graph --arg query_type=blast_radius --arg name=processPayment --arg depth=3 --arg repository=my-service
```

**All `rag_graph` query_types:** `call_chain`, `inheritance_tree`, `class_methods`, `module_dependencies`, `reverse_dependencies`, `find_entity`, `file_entities`, `graph_stats`, `raw_cypher`, `business_flow`, `flows_for_function`, `related_concepts`, `explore_domain`, `flow_dependencies`, `blast_radius`

### 3. Browse Wiki

```bash
# Wiki tree
python scripts/kb_query.py wiki_get_tree --arg business_id=$KB_BUSINESS_ID

# Page content
python scripts/kb_query.py get_wiki_page --arg scope=__domains__/auth/_overview --arg repository=$KB_BUSINESS_ID

# Wiki search
python scripts/kb_query.py wiki_search --arg query="authentication" --arg repository=$KB_BUSINESS_ID

# Domain overview
python scripts/kb_query.py wiki_get_domain_overview --arg domain=auth --arg business_id=$KB_BUSINESS_ID

# Related pages
python scripts/kb_query.py wiki_get_related --arg page_uid="WikiPage:biz:__domains__/auth/_overview"

# Full snapshot
python scripts/kb_query.py wiki_get_snapshot --arg business_id=$KB_BUSINESS_ID
```

### 4. Architecture

```bash
# HTTP/RPC endpoints
python scripts/kb_query.py search_architecture --arg mode=endpoints --arg repository=my-service

# Architecture layers
python scripts/kb_query.py search_architecture --arg mode=layers --arg layer=business --arg repository=my-service

# Graph insights
python scripts/kb_query.py get_insights --arg repository=my-service
```

### 5. Wiki → Code Exploration (drill down)

MCP `get_wiki_page` returns `source_locations` with `fqn` (no entity_uid). Use `fqn` to trace into code graph:

```bash
# Step 1: Get wiki page with source_locations
python scripts/kb_query.py get_wiki_page --arg scope=__domains__/auth/_overview --arg repository=$KB_BUSINESS_ID

# Step 2: Use fqn from source_locations to find entity in graph
python scripts/kb_query.py rag_graph --arg query_type=find_entity --arg name=AuthService

# Step 3: Trace call chain from entity
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=AuthService --arg direction=downstream --arg depth=3

# Step 4: Read source code
python scripts/kb_query.py get_code_snippet --arg node_uid="Class:my-service:AuthService"
```

For richer entity data (with graph UIDs), use REST API instead:

```bash
# Get page with source_entity_uids
curl "$KB_BASE_URL/api/v1/wiki/pages/by-path?business_id=$KB_BUSINESS_ID&path=__domains__/auth/_overview" \
  -H "Authorization: Bearer $KB_TOKEN"
# Response includes: source_entity_uids, source_locations[].entity_uid

# Get full entity cards for a page
curl "$KB_BASE_URL/api/v1/wiki/pages/WikiPage:$KB_BUSINESS_ID:__domains__/auth/_overview/entities?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"
# Response: entities[].{uid, name, entity_type, file_path, signature, business_summary}
```

### 6. Graph Stats & File Tree

```bash
# Graph stats
python scripts/kb_query.py rag_graph --arg query_type=graph_stats --arg repository=my-service

# Index freshness
python scripts/kb_query.py index_freshness --arg repository=my-service

# Complete entity context bundle
python scripts/kb_query.py get_complete_context --arg name=UserService --arg repository=my-service
```

### 7. REST API (when MCP tool is insufficient)

```bash
# Wiki page by path
curl "$KB_BASE_URL/api/v1/wiki/pages/by-path?business_id=$KB_BUSINESS_ID&path=__domains__/auth/_overview" \
  -H "Authorization: Bearer $KB_TOKEN"

# Domain tree
curl "$KB_BASE_URL/api/v1/wiki/domain-tree?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"

# File tree
curl "$KB_BASE_URL/api/v1/files/tree?repository=my-service" \
  -H "Authorization: Bearer $KB_TOKEN"

# Graph insights (with business_id resolution)
curl "$KB_BASE_URL/api/v1/graph/insights/my-service?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"

# Structured graph query
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query_type":"call_chain","name":"handleLogin","direction":"downstream","depth":3}'
```

For full REST API reference, see [references/rest-api.md](references/rest-api.md).

## Notes

- `raw_cypher` via `rag_graph` is available for ad-hoc graph queries
- Wiki page UIDs follow pattern `WikiPage:{business_id}:{path}`
- Scripts use Python stdlib only; see `scripts/kb_query.py`
