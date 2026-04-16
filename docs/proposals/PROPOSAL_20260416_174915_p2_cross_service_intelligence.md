# Proposal: P2 Cross-Service Intelligence & Agent Workflow

**Date**: 2026-04-16
**Status**: Approved → Implementing
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
- [ ] Query all `rpc_provider` classes → collect interface name + repository
- [ ] Query all `rpc_consumer` functions → collect target interface
- [ ] Match Provider ↔ Consumer by interface name
- [ ] Create `CROSS_REPO_CALLS` edges with `source_repo`, `target_repo`, `interface` properties
- [ ] Idempotent: clear old edges before rebuild

#### P2-5: Spring DI Container Graph
- [ ] Query classes with `@Autowired`, `@Inject`, `@Resource` annotations
- [ ] Parse injection targets (field type or constructor parameter type)
- [ ] Create `DEPENDS_ON` edges with `injection_type` (field/constructor/setter) property
- [ ] Idempotent: clear old DEPENDS_ON edges before rebuild

#### P2-4: Database Entity Mapping
- [ ] Add `ANNOTATION_SEMANTICS`: `@Entity`, `@Table`, `@Document` → `entity` semantic role
- [ ] Extract `@Table(name="...")` → store `table_name` property
- [ ] Create `ACCESSES_TABLE` edges: Repository/DAO → Entity class
- [ ] Idempotent: clear old ACCESSES_TABLE edges before rebuild

**Trigger**: `POST /api/v1/enrich/cross-repo`

### Module 2: AgentWorkflowService (`query/agent_workflow.py`)

Query layer — agent-optimized composite queries.

#### P2-2: PR Review Composite API
- [ ] Accept git diff text → parse changed files and functions
- [ ] For each changed function: run impact analysis
- [ ] Aggregate: affected endpoints, cross-repo impacts, affected layers
- [ ] Return structured ReviewContext with sections: changes, impact, suggestions

#### P2-3: Smart Context Builder
- [ ] Accept function/class name → build optimal context package
- [ ] Include: signature + body, callers (1 up), callees (1 down)
- [ ] Include: parent class siblings, cross-repo deps, entity tables
- [ ] Include: architecture layer context
- [ ] Token-budget-aware truncation

### Schema Changes (`store/schema.py`)
- [ ] Add `CROSS_REPO_CALLS` EdgeType
- [ ] Add `DEPENDS_ON` EdgeType
- [ ] Add `ACCESSES_TABLE` EdgeType

### Annotation Semantics (`indexer/annotation_semantics.py`)
- [ ] Add `ENTITY` SemanticRole
- [ ] Add `DI_INJECT` SemanticRole
- [ ] Add mappings: `@Entity`, `@Table`, `@Document`, `@Autowired`, `@Inject`, `@Resource`

### API Endpoints (`main.py`)
- [ ] `POST /api/v1/enrich/cross-repo` — trigger cross-repo enrichment
- [ ] `POST /api/v1/review/context` — PR review composite
- [ ] `POST /api/v1/context/build` — smart context builder

### MCP Tools (`api/mcp_server.py`)
- [ ] `review_pr` tool — PR diff analysis for code review agents
- [ ] `build_context` tool — smart context package for any entity

## Implementation Order

1. Schema + Annotation Semantics (foundation)
2. CrossRepoEnricher (graph enrichment)
3. AgentWorkflowService (query layer)
4. API Endpoints + MCP Tools (exposure)
5. Deploy + Verify
