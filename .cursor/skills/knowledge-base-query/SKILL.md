---
name: knowledge-base-query
description: Query the Knowledge Base Service for code context, graph traversal, file content, wiki pages, domain structure, and architecture insights. Use when the user asks to search code, explore call chains, read source files, browse wiki, check architecture, or get context from the knowledge graph. Triggers on keywords like "knowledge base", "search code", "call chain", "graph query", "wiki", "code context", "file content", "domain tree", "architecture".
---

# Knowledge Base Query

Query the project's Knowledge Base Service (FalkorDB graph + vector hybrid) via a CLI wrapper script. All operations are read-only.

## Setup

```bash
export KB_BASE_URL="http://localhost:8100"
export KB_TOKEN="your-token"                 # if REQUIRE_AUTH=true
export KB_BUSINESS_ID="default"

# Verify connectivity
bash scripts/kb_setup.sh check
```

The CLI script is at `scripts/kb_query.py` (stdlib only, no dependencies).

## Workflows

### 1. Search Code

```bash
# Hybrid semantic + keyword search
python scripts/kb_query.py search "login authentication" --repo my-service -k 5

# Response: semantic_matches[].{name, file_path, fqn, score, snippet}
```

### 2. Read File Content

```bash
# Full file
python scripts/kb_query.py file content --repo my-service --path src/auth/handler.py

# Specific lines (512KB cap)
python scripts/kb_query.py file content --repo my-service --path src/auth/handler.py --start 10 --end 50

# File tree
python scripts/kb_query.py file tree --repo my-service

# Entities in a file
python scripts/kb_query.py file entities --path src/auth/handler.py

# Code snippet by graph entity UID
python scripts/kb_query.py code Class:my-service:AuthService
```

### 3. Graph Queries (call chains, dependencies, etc.)

```bash
# Downstream call chain
python scripts/kb_query.py graph call-chain handleRequest --dir downstream --depth 3

# Upstream callers
python scripts/kb_query.py graph call-chain handleRequest --dir upstream

# Module dependencies
python scripts/kb_query.py graph deps auth_service

# Reverse dependencies (who depends on this module)
python scripts/kb_query.py graph reverse-deps auth_service

# Class methods
python scripts/kb_query.py graph methods UserService

# Inheritance tree
python scripts/kb_query.py graph inheritance BaseHandler

# Find entity by name
python scripts/kb_query.py graph find UserService --repo my-service

# Impact analysis (blast radius)
python scripts/kb_query.py graph blast-radius processPayment --depth 3

# Raw Cypher (power-user)
python scripts/kb_query.py graph cypher "MATCH (f:Function {name:\$name})-[:CALLS]->(c) RETURN c.name LIMIT 10" --params '{"name":"login"}'

# Any query_type via raw subcommand
python scripts/kb_query.py graph raw business_flow handlePayment --repo my-service
```

**Available graph query types:** `call_chain`, `inheritance_tree`, `class_methods`, `module_dependencies`, `reverse_dependencies`, `find_entity`, `file_entities`, `graph_stats`, `raw_cypher`, `business_flow`, `flows_for_function`, `related_concepts`, `explore_domain`, `flow_dependencies`, `blast_radius`

### 4. Browse Wiki

```bash
# Wiki page by path (use leading /)
python scripts/kb_query.py wiki page --path "/__domains__/auth/_overview"
# Response: title, content, source_entity_uids[], source_locations[].{file_path, fqn, entity_uid}

# Domain tree (hierarchy)
python scripts/kb_query.py wiki domain-tree

# Full wiki tree
python scripts/kb_query.py wiki tree

# Topic tree
python scripts/kb_query.py wiki topic-tree

# Wiki search
python scripts/kb_query.py wiki search "authentication flow" --limit 10

# Cross-repo wiki search
python scripts/kb_query.py wiki global-search "payment processing"

# Cross-domain CALLS edges
python scripts/kb_query.py wiki domain-edges

# Business flows
python scripts/kb_query.py wiki flows
```

### 5. Wiki → Code Drill-Down

Use wiki page data to explore associated code entities:

```bash
# Step 1: Get wiki page → note source_entity_uids in response
python scripts/kb_query.py wiki page --path "/__domains__/auth/_overview"

# Step 2: Get entity cards for a page (uid, name, type, file, signature, summary)
python scripts/kb_query.py wiki entities --path "/__domains__/auth/_overview"

# Step 3: Trace call chain from entity name
python scripts/kb_query.py graph call-chain AuthService --dir downstream --depth 3

# Step 4: Read entity source code
python scripts/kb_query.py code Class:my-service:AuthService

# Step 5: Page references (incoming/outgoing wiki links)
python scripts/kb_query.py wiki refs "WikiPage:my-biz:/__domains__/auth/_overview"
```

### 6. Architecture & Stats

```bash
# HTTP/RPC endpoints
python scripts/kb_query.py stats arch --repo my-service --layer api

# Graph insights (architecture anomalies)
python scripts/kb_query.py stats insights my-service

# Graph stats overview
python scripts/kb_query.py stats overview --repo my-service

# Knowledge graph health
python scripts/kb_query.py stats health

# Community detection
python scripts/kb_query.py stats communities --repo my-service --min-size 5

# List indexed repositories
python scripts/kb_query.py repos
```

For full REST API endpoint reference, see [references/rest-api.md](references/rest-api.md).

## Notes

- All commands output JSON to stdout, errors to stderr
- `--compact` flag on any command for single-line JSON output
- Wiki page UIDs follow pattern `WikiPage:{business_id}:{path}`
- `file content` has a 512KB cap; use `--start`/`--end` for large files
- `graph cypher` is available for ad-hoc Cypher queries
- Use `python scripts/kb_query.py <command> --help` for detailed usage
