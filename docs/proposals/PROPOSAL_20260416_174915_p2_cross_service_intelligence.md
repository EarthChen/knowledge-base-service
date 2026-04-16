# Proposal: P2 Cross-Service Intelligence & Agent Workflow

**Date**: 2026-04-16
**Status**: ✅ Implemented
**Completed**: 2026-04-16
**Scope**: P2 Knowledge Base Enhancement (Tier 1 + Tier 2)
**Depends on**: P1 Graph Enrichment (PROPOSAL_20260416_160540)

## Background

P1 established annotation extraction, graph enrichment (API endpoints, architecture layers),
and impact analysis. P2 extends the KB to understand **cross-service distributed systems**
and provide **agent-optimized workflows** for code review and context building.

## Scope: 5 Items (Option B)

### Tier 1: Cross-Service Intelligence (Highest Impact)
- **P2-1**: Cross-Repository RPC Resolution
- **P2-2**: PR Review Composite API
- **P2-3**: Smart Context Builder

### Tier 2: Deeper Structural Understanding
- **P2-4**: Database Entity Mapping
- **P2-5**: Spring DI Container Graph

## Architecture: Approach B (Layered Aggregation)

### Module 1: CrossRepoEnricher (`indexer/cross_repo_enricher.py`)

Graph enrichment layer — runs after all repos are indexed.

#### P2-1: Cross-Repository RPC Resolution
- [x] Query all `rpc_provider` classes → collect interface name + repository
- [x] Query all `rpc_consumer` functions → collect target interface
- [x] Match Provider ↔ Consumer by interface name
- [x] Create `CROSS_REPO_CALLS` edges with `source_repo`, `target_repo`, `interface` properties
- [x] Idempotent: clear old edges before rebuild

#### P2-5: Spring DI Container Graph
- [x] Query classes with `@Autowired`, `@Inject`, `@Resource` annotations
- [x] Parse injection targets (field type or constructor parameter type)
- [x] Create `DEPENDS_ON` edges with `injection_type` (field/constructor/setter) property
- [x] Idempotent: clear old DEPENDS_ON edges before rebuild

#### P2-4: Database Entity Mapping
- [x] Add `ANNOTATION_SEMANTICS`: `@Entity`, `@Table`, `@Document` → `entity` semantic role
- [x] Extract `@Table(name="...")` → store `table_name` property
- [x] Create `ACCESSES_TABLE` edges: Repository/DAO → Entity class
- [x] Idempotent: clear old ACCESSES_TABLE edges before rebuild

**Trigger**: `POST /api/v1/enrich/cross-repo`

### Module 2: AgentWorkflowService (`query/agent_workflow.py`)

Query layer — agent-optimized composite queries.

#### P2-2: PR Review Composite API
- [x] Accept git diff text → parse changed files and functions
- [x] For each changed function: run impact analysis
- [x] Aggregate: affected endpoints, cross-repo impacts, affected layers
- [x] Return structured ReviewContext with sections: changes, impact, suggestions

#### P2-3: Smart Context Builder
- [x] Accept function/class name → build optimal context package
- [x] Include: signature + body, callers (1 up), callees (1 down)
- [x] Include: parent class siblings, cross-repo deps, entity tables
- [x] Include: architecture layer context
- [ ] Token-budget-aware truncation (deferred to P3)

### Schema Changes (`store/schema.py`)
- [x] Add `CROSS_REPO_CALLS` EdgeType
- [x] Add `DEPENDS_ON` EdgeType
- [x] Add `ACCESSES_TABLE` EdgeType

### Annotation Semantics (`indexer/annotation_semantics.py`)
- [x] Add `ENTITY` SemanticRole
- [x] Add `DI_INJECT` SemanticRole
- [x] Add mappings: `@Entity`, `@Table`, `@Document`, `@Autowired`, `@Inject`, `@Resource`

### API Endpoints (`main.py`)
- [x] `POST /api/v1/enrich/cross-repo` — trigger cross-repo enrichment
- [x] `POST /api/v1/review/context` — PR review composite
- [x] `POST /api/v1/context/build` — smart context builder

### MCP Tools (`api/mcp_server.py`)
- [x] `review_pr` tool — PR diff analysis for code review agents
- [x] `build_context` tool — smart context package for any entity
- [x] `search_architecture`, `code_quality`, `dashboard_stats` — G3/G5 MCP 对齐 REST

## Post-P2 extensions (G1–G6) — completed

以下在 P2 基线交付后合入，已全部落地（详见 `docs/MCP-INTEGRATION.md`、`docs/README-DOCS.md`）。

### G1: Parser enhancements
- [x] Java 字段级注解与 `ParsedField`
- [x] 构造器注入支持（DI 字段伪 Function 节点）
- [x] Class 节点存储泛型形参
- [x] `code_snippet` 截断优化

### G2: Graph & SmartContext
- [x] RPC 接口合约（`is_rpc_contract`、`contract_methods`）
- [x] 域事件边 `EVENT_PRODUCES` / `EVENT_CONSUMES` 至 Kafka Topic Module
- [x] SmartContext：`rpc_interface_contracts`、`event_context`

### G3: API / MCP / enrichment
- [x] `GET /api/v1/search/architecture`、`GET /api/v1/quality/{entity_uid}`
- [x] MCP：`search_architecture`、`code_quality`
- [x] 索引完成后自动跨仓库富集（与手动 `POST /api/v1/enrich/cross-repo` 同源）

### G4: PR review
- [x] `POST /api/v1/review/context`：`branch` + `repo_path` 本地 diff
- [x] MCP `review_pr`：`branch`、`repo_path`、`base_branch`

### G5: Dashboard P2
- [x] `GET /api/v1/stats/p2`
- [x] MCP `dashboard_stats`

### G6: Bulk reindex
- [x] `POST /api/v1/reindex/all`
- [x] `scripts/reindex_all.py`

## Implementation Order

1. Schema + Annotation Semantics (foundation)
2. CrossRepoEnricher (graph enrichment)
3. AgentWorkflowService (query layer)
4. API Endpoints + MCP Tools (exposure)
5. Deploy + Verify
