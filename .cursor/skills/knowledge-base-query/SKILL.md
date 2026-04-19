---
name: knowledge-base-query
description: Query the Knowledge Base Service for code context, graph traversal, file content, wiki, and architecture insights. Use when the user asks to search code, explore call chains, read source files, check architecture, or get context from the knowledge graph. Triggers on keywords like "knowledge base", "search code", "call chain", "graph query", "wiki", "code context", "file content".
---

# Knowledge Base Query

Query the project's Knowledge Base Service (FalkorDB graph + vector hybrid search) via its MCP HTTP API. The service provides 15 query tools for code search, graph traversal, file access, architecture analysis, and wiki.

## Prerequisites

Set environment variables before calling scripts:

```bash
export KB_BASE_URL="http://localhost:8000"  # KB service address
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

### Core Query Tools

| Tool | Purpose | Key Args |
|------|---------|----------|
| `rag_query` | Hybrid search (semantic + keyword + BM25) | `query` (required), `k`, `repository`, `language`, `entity_type` |
| `rag_graph` | Graph traversal and structured queries | `query_type` (required), `name`, `depth`, `direction` |
| `get_file_content` | Read raw source files | `repository` + `file_path` (required), `start_line`, `end_line` |
| `get_code_snippet` | Get entity source by graph UID | `node_uid` (required) |
| `get_complete_context` | Full entity context (code + callers + wiki) | `entity_name` (required), `repository`, `max_tokens` |

### Graph Query Types

`rag_graph` supports these `query_type` values:

| Type | Description | Required Args |
|------|-------------|---------------|
| `call_chain` | Function call chain (upstream/downstream) | `name`, `direction`, `depth` |
| `inheritance_tree` | Class hierarchy | `name`, `direction` |
| `class_methods` | Methods of a class | `name` |
| `find_entity` | Find entity by name | `name`, `entity_type` |
| `file_entities` | List entities in a file | `file` |
| `blast_radius` | Change impact analysis | `names` or `name`, `depth` |
| `nl_query` | Natural language → Cypher (needs LLM) | `name` (the question), `repository` |
| `raw_cypher` | Direct Cypher query | `cypher` |

### Analysis & Wiki Tools

| Tool | Purpose |
|------|---------|
| `documents` | List/get indexed documentation |
| `analyze_code` | Quality score or consistency check |
| `search_architecture` | Classes by layer or endpoint discovery |
| `analyze_changes` | PR review, impact analysis |
| `get_insights` | Dashboard stats or graph anomalies |
| `index_freshness` | Repository index timestamp and counts |
| `search_wiki` | Hybrid wiki search |
| `get_wiki_page` | Get generated wiki page |
| `list_wiki_pages` | Wiki page tree |

## Common Workflows

### 1. Search → Read Full Source

```bash
# Search for login handling code
python scripts/kb_query.py rag_query --arg query="login authentication" --arg k=5 --arg repository=my-service

# Get full file content for a result
python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth/handler.py

# Or get specific lines
python scripts/kb_query.py get_file_content --arg repository=my-service --arg file_path=src/auth/handler.py --arg start_line=10 --arg end_line=50
```

### 2. Trace Call Chain

```bash
# Who calls handleRequest?
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=upstream --arg depth=3

# What does handleRequest call?
python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest --arg direction=downstream
```

### 3. Natural Language Graph Query

```bash
# Ask a question in natural language (requires LLM enabled)
python scripts/kb_query.py rag_graph --arg query_type=nl_query --arg name="列出所有调用了 UserService.login 的函数" --arg repository=my-service
```

### 4. Change Impact Analysis

```bash
# Analyze blast radius of a change
python scripts/kb_query.py rag_graph --arg query_type=blast_radius --arg name=processPayment --arg depth=3 --arg repository=my-service
```

### 5. Architecture Discovery

```bash
# List all HTTP endpoints
python scripts/kb_query.py search_architecture --arg mode=endpoints --arg repository=my-service

# List business layer classes
python scripts/kb_query.py search_architecture --arg mode=layers --arg layer=business --arg repository=my-service
```

## Filtering

Most query tools support optional `repository` and `language` filters applied at Cypher level:

```bash
python scripts/kb_query.py rag_query --arg query="database connection" --arg repository=backend-api --arg language=java
```

## Notes

- All scripts use Python standard library only (no pip dependencies needed)
- Results are JSON; pipe to `jq` for formatting: `python scripts/kb_query.py ... | jq .`
- `get_file_content` has a 512KB limit; use `start_line`/`end_line` for large files
- `nl_query` requires the KB service to have LLM enabled (`LLM__ENABLED=true`)
- Indexing is triggered via Dashboard UI or HTTP API, not through these query tools
