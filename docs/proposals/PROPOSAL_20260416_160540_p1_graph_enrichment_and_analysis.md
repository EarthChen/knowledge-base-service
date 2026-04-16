# Proposal: P1 Graph Enrichment, Analysis & Interface Resolution

**Date**: 2026-04-16
**Status**: ✅ Implemented
**Scope**: P1 Knowledge Base Enhancement
**Depends on**: P0 Annotation Extraction (PROPOSAL_20260416_152408)
**Completed**: 2026-04-16

## Background

P0 established the annotation extraction pipeline and semantic role mapping.
P1 builds on this foundation to provide:
- Structured API endpoint discovery
- Architecture layer classification
- Change impact analysis for code review
- Incremental index consistency verification
- Java interface-implementation relationship tracking

## Goals

1. **API Endpoint Discovery**: Aggregate annotations into structured HTTP/RPC/Kafka endpoint views
2. **Architecture Layer Identification**: Auto-classify classes into Controller/Service/DAO/RPC layers
3. **Change Impact Analysis**: Trace call chains to determine blast radius of code changes
4. **Index Consistency Verification**: Detect ghost nodes and missing files after incremental indexing
5. **Interface Implementation**: Parse Java `implements` clauses and create IMPLEMENTS edges

## Design

### Module 1: GraphEnricher (API Endpoints + Architecture Layers)

**New file**: `indexer/graph_enricher.py`

Runs as a post-indexing step, enriching graph nodes with derived properties.

#### API Endpoint Enrichment

For Function nodes with `semantic_roles` containing `http_endpoint`:
- [ ] Parse the annotation argument to extract the HTTP path (e.g., `@GetMapping("/api/users")` → path="/api/users")
- [ ] Determine HTTP method from annotation name (GetMapping→GET, PostMapping→POST, etc.)
- [ ] For methods in `@RequestMapping` classes, compose full path (class path + method path)
- [ ] Store as node properties: `api_path`, `http_method`

For Class nodes with `rpc_provider` role:
- [ ] Store `rpc_interface` property with the class FQN
- [ ] Mark all public methods as RPC endpoints

For Function nodes with `message_listener` role:
- [ ] Extract topic from `@KafkaListener(topics="...")` annotation argument
- [ ] Store as `kafka_topic` property

#### Architecture Layer Enrichment

- [ ] Define layer classification rules (ordered by priority):
  1. `semantic_roles` contains `http_controller` → "presentation"
  2. `semantic_roles` contains `rpc_provider` → "rpc"
  3. `semantic_roles` contains `service` → "business"
  4. `semantic_roles` contains `repository` → "data_access"
  5. `semantic_roles` contains `message_listener` → "messaging"
  6. `semantic_roles` contains `component` or `scheduled_task` → "infrastructure"
  7. FQN/package contains `.controller.` → "presentation"
  8. FQN/package contains `.service.` → "business"
  9. FQN/package contains `.dao.` or `.repository.` or `.mapper.` → "data_access"
  10. FQN/package contains `.model.` or `.entity.` or `.dto.` → "model"
  11. FQN/package contains `.config.` → "infrastructure"
- [ ] Store as `architecture_layer` property on Class nodes
- [ ] Propagate to contained Function nodes

### Module 2: AnalysisService (Impact Analysis + Consistency Check)

**New file**: `query/analysis_service.py`

#### Change Impact Analysis

- [ ] `analyze_impact(changed_functions: list[str], max_depth: int = 5) -> ImpactReport`
- [ ] Cypher query: `MATCH p=(target:Function)<-[:CALLS*1..{max_depth}]-(caller) WHERE target.name IN $names RETURN ...`
- [ ] Return: affected functions, affected classes, affected layers, entry points in blast radius
- [ ] Include direct callers and transitive callers with depth info

```python
@dataclass
class ImpactReport:
    changed_functions: list[str]
    direct_callers: list[dict]       # depth=1
    transitive_callers: list[dict]   # depth>1
    affected_classes: list[str]
    affected_layers: list[str]       # ["presentation", "business"]
    affected_entry_points: list[dict] # API endpoints in blast radius
    max_depth_reached: bool
```

#### Index Consistency Verification

- [ ] `verify_consistency(repository: str, repo_path: str) -> ConsistencyReport`
- [ ] Compare graph file list vs actual repo file list
- [ ] Detect ghost nodes (in graph but not on disk)
- [ ] Detect missing files (on disk but not in graph)
- [ ] Detect stale nodes (file modified after last index)

```python
@dataclass
class ConsistencyReport:
    total_graph_files: int
    total_repo_files: int
    ghost_files: list[str]      # in graph, not on disk
    missing_files: list[str]    # on disk, not in graph
    stale_files: list[str]      # modified since last index
    is_consistent: bool
```

### Module 3: Interface Resolution (Tree-Sitter + Graph)

**File**: `indexer/tree_sitter_parser.py`

- [ ] Add `interfaces: list[str]` field to `ParsedClass`
- [ ] Add Java tree-sitter query for `interface_declaration`
- [ ] Extract `implements` clause from Java `class_declaration` (super_interfaces child)
- [ ] Extract `interface_declaration` as a Class node with `is_interface=True`

**File**: `indexer/code_graph_builder.py`

- [ ] For classes with `interfaces` list, create `IMPLEMENTS` edges to interface nodes
- [ ] Add `is_interface` property to Class nodes derived from interface_declaration

**File**: `store/schema.py`

- [ ] `IMPLEMENTS` edge type already exists, no schema change needed

### Module 4: API Endpoints

**File**: `main.py`

- [ ] `GET /api/v1/endpoints/{repository:path}` — list all API endpoints
- [ ] `POST /api/v1/analysis/impact` — analyze impact of changed functions
- [ ] `GET /api/v1/analysis/consistency/{repository:path}` — run consistency check
- [ ] `GET /api/v1/architecture/{repository:path}` — get architecture layer breakdown

### MCP Tool Integration

**File**: `api/mcp_server.py`

- [ ] Add `analyze_impact` tool for code review agent
- [ ] Add `list_endpoints` tool for architecture exploration
- [ ] Add `check_consistency` tool for index health

## Implementation Order

1. Module 3 (Interface Resolution) — parser-level, independent
2. Module 1 (GraphEnricher) — post-indexing enrichment
3. Module 2 (AnalysisService) — query-time analysis
4. Module 4 (API + MCP) — expose everything

## Testing Strategy

- Unit tests for GraphEnricher with mock nodes
- Unit tests for AnalysisService with mock FalkorDB
- Integration test for interface parsing with Java sample code
- API tests for new endpoints
