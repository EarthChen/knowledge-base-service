---
name: knowledge-base-query
description: Query the Knowledge Base Service for code context, graph traversal, file content, wiki pages, domain structure, and architecture insights. Use when the user asks to search code, explore call chains, read source files, browse wiki, check architecture, or get context from the knowledge graph. Triggers on keywords like "knowledge base", "search code", "call chain", "graph query", "wiki", "code context", "file content", "domain tree", "architecture".
---

# Knowledge Base Query

Query the project's Knowledge Base Service (FalkorDB graph + vector hybrid) via REST API. All operations are read-only HTTP calls.

## Setup

```bash
export KB_BASE_URL="http://localhost:8100"
export KB_TOKEN="your-token"                 # if REQUIRE_AUTH=true
export KB_BUSINESS_ID="default"
```

Verify: `curl -s "$KB_BASE_URL/api/v1/health" | python -m json.tool`

Common headers for all requests:

```bash
-H "Authorization: Bearer $KB_TOKEN" -H "X-Business-Id: $KB_BUSINESS_ID"
```

## Workflows

### 1. Search Code

```bash
# Hybrid semantic + keyword search
curl -X POST "$KB_BASE_URL/api/v1/hybrid" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"login authentication","repository":"my-service","k":5}'

# Response: semantic_matches[].{name, file_path, fqn, score, snippet}
```

### 2. Read File Content

```bash
# Full file
curl "$KB_BASE_URL/api/v1/files/content?repository=my-service&file_path=src/auth/handler.py" \
  -H "Authorization: Bearer $KB_TOKEN"

# Specific lines (512KB cap)
curl "$KB_BASE_URL/api/v1/files/content?repository=my-service&file_path=src/auth/handler.py&start_line=10&end_line=50" \
  -H "Authorization: Bearer $KB_TOKEN"

# File tree
curl "$KB_BASE_URL/api/v1/files/tree?repository=my-service" \
  -H "Authorization: Bearer $KB_TOKEN"

# Code snippet by graph entity UID
curl "$KB_BASE_URL/api/v1/code/Class:my-service:AuthService" \
  -H "Authorization: Bearer $KB_TOKEN"
```

### 3. Graph Queries (call chains, dependencies, etc.)

```bash
# Downstream call chain
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query_type":"call_chain","name":"handleRequest","direction":"downstream","depth":3}'

# Upstream callers
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query_type":"call_chain","name":"handleRequest","direction":"upstream"}'

# Module dependencies
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query_type":"module_dependencies","name":"auth_service"}'

# Find entity by name
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query_type":"find_entity","name":"UserService","repository":"my-service"}'

# Blast radius
curl -X POST "$KB_BASE_URL/api/v1/graph/blast-radius" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"entities":["processPayment"],"depth":3}'

# Raw Cypher (power-user)
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query_type":"raw_cypher","cypher":"MATCH (f:Function {name:$name})-[:CALLS]->(c) RETURN c.name LIMIT 10","params":{"name":"login"}}'
```

**Available `query_type` values:** `call_chain`, `inheritance_tree`, `class_methods`, `module_dependencies`, `reverse_dependencies`, `find_entity`, `file_entities`, `graph_stats`, `raw_cypher`, `business_flow`, `flows_for_function`, `related_concepts`, `explore_domain`, `flow_dependencies`, `blast_radius`

### 4. Browse Wiki

```bash
# Wiki page by path
curl "$KB_BASE_URL/api/v1/wiki/pages/by-path?business_id=$KB_BUSINESS_ID&path=__domains__/auth/_overview" \
  -H "Authorization: Bearer $KB_TOKEN"
# Response: title, content, source_locations[].{file_path, fqn, entity_uid}, source_entity_uids[]

# Domain tree (hierarchy)
curl "$KB_BASE_URL/api/v1/wiki/domain-tree?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"

# Full wiki tree
curl "$KB_BASE_URL/api/v1/wiki/tree?business_id=$KB_BUSINESS_ID&view=business_domain" \
  -H "Authorization: Bearer $KB_TOKEN"

# Wiki search
curl -X POST "$KB_BASE_URL/api/v1/wiki/search" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"authentication flow","repository":"'"$KB_BUSINESS_ID"'","limit":10}'

# Cross-domain CALLS edges
curl "$KB_BASE_URL/api/v1/wiki/domain-edges?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"
```

### 5. Wiki → Code Drill-Down

Use wiki page data to explore associated code entities:

```bash
# Step 1: Get wiki page → extract source_entity_uids
curl "$KB_BASE_URL/api/v1/wiki/pages/by-path?business_id=$KB_BUSINESS_ID&path=__domains__/auth/_overview" \
  -H "Authorization: Bearer $KB_TOKEN"
# Response includes: source_entity_uids, source_locations[].entity_uid

# Step 2: Get full entity cards for a page (uid, name, type, file, signature, summary)
curl "$KB_BASE_URL/api/v1/wiki/pages/WikiPage:$KB_BUSINESS_ID:__domains__/auth/_overview/entities?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"

# Step 3: Trace call chain from entity name
curl -X POST "$KB_BASE_URL/api/v1/graph" \
  -H "Authorization: Bearer $KB_TOKEN" -H "Content-Type: application/json" \
  -d '{"query_type":"call_chain","name":"AuthService","direction":"downstream","depth":3}'

# Step 4: Read entity source code
curl "$KB_BASE_URL/api/v1/code/Class:my-service:AuthService" \
  -H "Authorization: Bearer $KB_TOKEN"

# Step 5: Page references (incoming/outgoing wiki links)
curl "$KB_BASE_URL/api/v1/wiki/pages/WikiPage:$KB_BUSINESS_ID:__domains__/auth/_overview/references" \
  -H "Authorization: Bearer $KB_TOKEN"
```

### 6. Architecture & Stats

```bash
# HTTP/RPC endpoints
curl "$KB_BASE_URL/api/v1/search/architecture?layer=api&repository=my-service" \
  -H "Authorization: Bearer $KB_TOKEN"

# Graph insights (architecture anomalies)
curl "$KB_BASE_URL/api/v1/graph/insights/my-service?business_id=$KB_BUSINESS_ID" \
  -H "Authorization: Bearer $KB_TOKEN"

# Graph stats
curl "$KB_BASE_URL/api/v1/stats?repository=my-service" \
  -H "Authorization: Bearer $KB_TOKEN"

# Knowledge graph health
curl "$KB_BASE_URL/api/v1/stats/health" \
  -H "Authorization: Bearer $KB_TOKEN"

# List indexed repositories
curl "$KB_BASE_URL/api/v1/repositories" \
  -H "Authorization: Bearer $KB_TOKEN"
```

For full REST API endpoint reference, see [references/rest-api.md](references/rest-api.md).

## Notes

- All endpoints return JSON
- Wiki page UIDs follow pattern `WikiPage:{business_id}:{path}`
- `files/content` has a 512KB cap; use `start_line`/`end_line` for large files
- `raw_cypher` via `POST /graph` is available for ad-hoc graph queries
- Graph explore/expand endpoints support interactive visualization
