# Knowledge Base Service — REST API Reference

## Auth Roles

- **VIEWER**: Read-only access (default for most endpoints)
- **EDITOR**: Write access (indexing, wiki edits, reviews)
- **ADMIN**: System administration (delete repos, settings, sync)

Headers: `Authorization: Bearer <token>`, `X-Business-Id: <business_id>`

---

## Graph & Stats (`/api/v1`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/stats` | Graph stats | `repository?` |
| GET | `/stats/p2` | P2 enrichment stats | — |
| GET | `/stats/health` | Knowledge graph health | — |
| GET | `/graph/insights/{repository:path}` | Architecture insights | `business_id?` |
| GET | `/repositories` | List indexed repos | `offset`, `limit` |
| POST | `/graph` | Structured graph query | Body: `GraphQueryRequest` |
| POST | `/hybrid` | Hybrid semantic + graph search | Body: `HybridSearchRequest` |
| POST | `/deep-search` | LLM multi-step deep search | Body: `DeepSearchRequest` |
| POST | `/deep-search/stream` | Deep search SSE | Same body |
| POST | `/graph/explore` | Graph neighborhood for viz | Body: `GraphExploreRequest` |
| POST | `/graph/expand` | Incremental expansion | Body: `GraphExpandRequest` |
| POST | `/graph/blast-radius` | Impact from entities | Body: `BlastRadiusRequest` |
| GET | `/graph/communities` | Community detection | `repository`, `min_size` |
| GET | `/code/{node_uid:path}` | Code snippet for entity | — |
| POST | `/pr/fetch` | Resolve PR/MR URL → changed files | Body: `PrFetchRequest` |

## Files (`/api/v1`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/files/tree` | Module file tree | `repository` |
| GET | `/files/content` | Read file from disk | `repository`, `file_path`, `start_line?`, `end_line?` |
| GET | `/files/entities` | Entities in a file | `file_path` |

## Documents (`/api/v1`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/documents` | List documents | `repository?`, `offset`, `limit` |
| GET | `/documents/{doc_uid:path}` | Document + sections | — |

## Indexing (`/api/v1`, EDITOR)

| Method | Path | Description | Key Body Fields |
|--------|------|-------------|-----------------|
| POST | `/index` | Trigger indexing | `directory` or `git_url`, `business_id`, `mode` (full/incremental) |
| POST | `/reindex/all` | Queue full reindex | `business_id` |
| POST | `/enrich` | LLM enrich task | `repository`, `force?` |
| POST | `/index/files` | Index file contents | `files`, `repository` |
| GET | `/index/tasks` | List index tasks | — |
| GET | `/index/tasks/{task_id}` | Task detail | — |

## Wiki Pages (`/api/v1/wiki`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/pages/by-path` | Page by path | `business_id`, `path`, `repository?` |
| GET | `/pages/{uid:path}/entities` | Source entities | `business_id` |
| GET | `/pages/{uid:path}/references` | Incoming/outgoing refs | — |
| GET | `/pages/{uid:path}/versions` | Version list | — |
| GET | `/pages/{uid:path}/diff` | Diff two versions | `from_version`, `to_version` |
| GET | `/{repository}/pages` | Paginated page list | `scope?`, `skip`, `limit` |
| GET | `/{repository}/pages/{path:path}` | Page detail + related | — |
| POST | `/search` | Wiki search | Body: `WikiSearchBody` |
| POST | `/search/global` | Cross-repo wiki search | Body: `WikiGlobalSearchBody` |
| POST | `/semantic-search` | Vector/fulltext/graph | Body: `query`, `repository`, `limit` |

## Wiki Tree & Domains (`/api/v1/wiki`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| GET | `/tree` | Wiki tree | `business_id`, `view`, `wiki_tier?` |
| GET | `/domain-tree` | Domain hierarchy + review | `business_id` |
| GET | `/topic-tree` | Topic navigation tree | `business_id` |
| GET | `/domain-edges` | Cross-domain CALLS edges | `business_id` |
| GET | `/references` | Reference graph | `business_id` |
| GET | `/coverage-report` | Coverage analysis | `business_id` |
| GET | `/quality-score` | Aggregate quality 0–100 | `business_id` |

## Domain Hierarchy Management (`/api/v1/wiki/domains/hierarchy`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| PATCH | `/{uid}` | Rename domain | `business_id`, Body: `title`, `description?` |
| DELETE | `/{uid}` | Delete domain | `business_id`, `promote_children?` |
| POST | `/{uid}/children` | Create subdomain | `business_id`, Body: `title` |
| POST | `/{uid}/move` | Move domain | `business_id`, Body: `new_parent_uid` |
| POST | `/merge` | Merge domains | `business_id`, Body: `source_uid`, `target_uid` |
| POST | `/move-module` | Move module between domains | `business_id`, Body: `module_name`, `target_domain_uid` |

## Wiki AI Ask (`/api/v1/wiki`, VIEWER)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| POST | `/ask` | Ask SSE (named events) | Body: `WikiAskBody` |
| POST | `/ask/stream` | Ask SSE (`type`: token/sources/done) | Body: `WikiAskBody` |
| GET | `/ask/stream` | GET variant for EventSource | Query: `repository`, `question`, `mode?`, `conversation_id?` |
| GET | `/pages/{uid:path}/questions` | Suggested questions | — |
| POST | `/ask/crystallize` | Save Q&A as wiki page (EDITOR) | Body: `WikiCrystallizeBody` |
| POST | `/research` | Deep research | Body: `WikiResearchBody` |

## Wiki AI Edit (`/api/v1/wiki`, EDITOR for all)

| Method | Path | Description | Key Params |
|--------|------|-------------|------------|
| POST | `/pages/{uid:path}/edit-session` | Create session + first message | Body: `instruction` |
| POST | `/pages/{uid:path}/edit-session/{sid}/message` | Follow-up message | Body: `instruction` |
| GET | `/pages/{uid:path}/edit-session/{sid}/stream` | SSE event stream | — |
| POST | `/pages/{uid:path}/edit-session/{sid}/apply` | Apply edit to graph | — |
| DELETE | `/pages/{uid:path}/edit-session/{sid}` | Delete session | — |

## Wiki Tasks & Events (`/api/v1/wiki`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/business/generate` | EDITOR | Business wiki background job |
| GET | `/business/tasks/{task_id}` | VIEWER | Business task status |
| POST | `/quick` | VIEWER | Quick wiki from git_url |
| GET | `/tasks/active` | VIEWER | Active wiki tasks |
| POST | `/tasks/{task_id}/cancel` | EDITOR | Cancel generation |
| GET | `/events` | VIEWER | SSE wiki events (`business_id`) |

## Wiki Feedback & Review (`/api/v1/wiki`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/pages/{uid:path}/feedback` | VIEWER | Submit feedback |
| GET | `/pages/{uid:path}/feedback/summary` | VIEWER | Aggregate counts |
| POST | `/pages/{uid:path}/review` | EDITOR | Set review status |
| POST | `/review/batch` | EDITOR | Batch review |
| POST | `/pages/{uid:path}/regenerate` | EDITOR | Regenerate page |

## Wiki Content Editing (`/api/v1/wiki`, EDITOR via editor_router)

| Method | Path | Description |
|--------|------|-------------|
| PATCH | `/pages/{uid:path}/content` | Update page markdown (LWW) |
| POST | `/pages/{uid:path}/editing` | Editing heartbeat |
| DELETE | `/pages/{uid:path}/editing` | Stop editing presence |
| GET | `/pages/{uid:path}/editors` | List active editors |

## Wiki Export & Lint

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/export` | EDITOR | Business wiki ZIP or git publish |
| POST | `/{repository}/lint` | VIEWER | Wiki lint |
| POST | `/{repository}/export/preview` | EDITOR | Export preview |
| POST | `/{repository}/export/execute` | EDITOR | Write export |
| GET | `/{repository}/offline-pack` | VIEWER | Offline JSON pack |

## Businesses (`/api/v1`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/businesses` | — | List businesses |
| POST | `/businesses` | EDITOR | Create business |
| PUT | `/businesses/{id}` | EDITOR | Update business |
| DELETE | `/businesses/{id}` | EDITOR | Delete business |
| PUT | `/businesses/{id}/repositories` | EDITOR | Bind repos |
| GET | `/businesses/{id}/repositories` | — | List bound repos |

## Admin (`/api/v1`, ADMIN)

| Method | Path | Description |
|--------|------|-------------|
| DELETE | `/index/{repository:path}` | Drop repo index |
| DELETE | `/wiki/{business_id}` | Delete wiki graph data |
| GET | `/index/report/{repository:path}` | Last indexing report |
| POST | `/sync/repo` | Git pull + incremental index |
| POST | `/sync/all` | Sync all repos |
| POST | `/sync/repo-update-wiki` | Sync + background wiki regen |

## Settings (`/api/v1/settings`, ADMIN)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | All settings categories |
| GET | `/{category}` | One category |
| PUT | `/` | Batch update |
| PUT | `/{key:path}` | Single key update |
| DELETE | `/{key:path}` | Delete key |
| POST | `/test-connection` | FalkorDB / LLM probe |

## MCP Tool Dispatch

| Endpoint | Description |
|----------|-------------|
| POST `/api/v1/mcp/tool` | Main MCP tool invocation (22 tools) |
| GET `/api/v1/mcp/tools` | Main MCP tool manifest |
| POST `/api/v1/mcp/tools/call` | Wiki HTTP MCP (6 tools) |
| GET `/api/v1/mcp/tools/list` | Wiki HTTP MCP manifest |

## Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Readiness check |
| GET | `/api/v1/auth/me` | Token introspection |
