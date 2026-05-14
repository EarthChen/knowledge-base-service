# Knowledge Base Service — Query REST API Reference

Auth headers: `Authorization: Bearer <token>`, `X-Business-Id: <business_id>`

## Graph & Stats (`/api/v1`)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/stats` | Graph stats | `repository?` |
| GET | `/stats/p2` | P2 enrichment stats | — |
| GET | `/stats/health` | Knowledge graph health | — |
| GET | `/graph/insights/{repository:path}` | Architecture insights | `business_id?` |
| GET | `/repositories` | List indexed repos | `offset`, `limit` |
| POST | `/graph` | Structured graph query | Body: `query_type`, `name`, `direction?`, `depth?`, `repository?` |
| POST | `/hybrid` | Hybrid semantic + graph search | Body: `query`, `repository`, `k?` |
| POST | `/graph/explore` | Graph neighborhood for viz | Body: `node_uid`, `depth` |
| POST | `/graph/expand` | Incremental expansion | Body: `node_uids`, `direction` |
| POST | `/graph/blast-radius` | Impact from entities | Body: `entities`, `depth` |
| GET | `/graph/communities` | Community detection | `repository`, `min_size` |
| GET | `/code/{node_uid:path}` | Code snippet for entity | — |
| POST | `/pr/fetch` | Resolve PR/MR URL → changed files | Body: `url` |

## Files (`/api/v1`)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/files/tree` | Module file tree | `repository` |
| GET | `/files/content` | Read file from disk | `repository`, `file_path`, `start_line?`, `end_line?` |
| GET | `/files/entities` | Entities in a file | `file_path` |

## Documents (`/api/v1`)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/documents` | List documents | `repository?`, `offset`, `limit` |
| GET | `/documents/{doc_uid:path}` | Document + sections | — |

## Wiki Pages (`/api/v1/wiki`)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/pages/by-path` | Page by path | `business_id`, `path`, `repository?` |
| GET | `/pages/{uid:path}/entities` | Source entities | `business_id` |
| GET | `/pages/{uid:path}/references` | Incoming/outgoing refs | — |
| GET | `/pages/{uid:path}/versions` | Version list | — |
| GET | `/pages/{uid:path}/diff` | Diff two versions | `from_version`, `to_version` |
| GET | `/{repository}/pages` | Paginated page list | `scope?`, `skip`, `limit` |
| GET | `/{repository}/pages/{path:path}` | Page detail + related | — |
| POST | `/search` | Wiki search | Body: `query`, `repository`, `limit` |
| POST | `/search/global` | Cross-repo wiki search | Body: `query`, `limit` |
| POST | `/semantic-search` | Vector/fulltext/graph | Body: `query`, `repository`, `limit` |

## Wiki Tree & Domains (`/api/v1/wiki`)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/tree` | Wiki tree | `business_id`, `view`, `wiki_tier?` |
| GET | `/domain-tree` | Domain hierarchy + review | `business_id` |
| GET | `/topic-tree` | Topic navigation tree | `business_id` |
| GET | `/domain-edges` | Cross-domain CALLS edges | `business_id` |
| GET | `/references` | Reference graph | `business_id` |
| GET | `/coverage-report` | Coverage analysis | `business_id` |
| GET | `/quality-score` | Aggregate quality 0–100 | `business_id` |
| GET | `/flows` | BusinessFlow nodes | `business_id` |
| GET | `/{business_id}/domains` | List domain anchors | — |
| GET | `/{business_id}/domains/{slug}/modules` | Modules in domain | — |
| GET | `/{business_id}/checkpoint` | Pipeline checkpoint | — |

## MCP Tool Dispatch

| Endpoint | Description |
|----------|-------------|
| POST `/api/v1/mcp/tool` | Main MCP tool invocation (22 tools) |
| GET `/api/v1/mcp/tools` | Main MCP tool manifest |

## Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Readiness check |
| GET | `/api/v1/auth/me` | Token introspection |
