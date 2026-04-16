# Proposal: Annotation Extraction, Index Quality Report & Type Modeling

**Date**: 2026-04-16
**Status**: Implemented
**Scope**: P0 Knowledge Base Enhancement

## Background

The current knowledge base indexes code at the Function/Class/Module level with
CALLS/CONTAINS/INHERITS/IMPORTS edges. However it cannot answer questions about
the **role** of a class (Controller vs Service vs DAO), **RPC relationships**
(who provides, who consumes), or **API endpoints**. This is because:

1. `_extract_decorators` only supports Python; Java annotations are ignored.
2. Even Python decorators are extracted but **never stored** in graph nodes.
3. `find_entry_points` uses unreliable `signature CONTAINS '@Annotation'` matching.
4. No type information (parameters, return types) is captured.
5. No index quality reporting exists — users cannot know if indexing is healthy.

## Goals

1. **Multi-language annotation/decorator extraction** — Java, Python, TypeScript, Go.
2. **Annotation semantic mapping** — Map annotations to roles (rpc_provider, http_controller, service, etc.).
3. **RPC relationship modeling** — @MoaProvider/@MoaConsumer (P0), @DubboService/@DubboReference.
4. **Index quality report** — File counts, entity counts, edge counts, failure list.
5. **Type information modeling** — Function parameters and return types.

## Design

### Module 1: Multi-Language Annotation Extraction

**File**: `indexer/tree_sitter_parser.py`

Changes:
- [ ] Add `decorators: list[str]` field to `ParsedClass`
- [ ] Extend `_extract_decorators` to support Java (annotation/marker_annotation nodes in modifiers)
- [ ] Extend `_extract_decorators` to support TypeScript (decorator nodes)
- [ ] Extend `_extract_decorators` to support Go (comment-based annotations like `//go:generate`)
- [ ] Extract class-level decorators in `_extract_classes`

Java annotation extraction strategy:
```
class_declaration / method_declaration
  └── modifiers
       ├── marker_annotation → @Service (no args)
       │    └── name: identifier → "Service"
       └── annotation → @RequestMapping("/api") (with args)
            ├── name: identifier → "RequestMapping"
            └── annotation_argument_list → ("api")
```

### Module 2: Annotation Semantic Mapping Table

**New file**: `indexer/annotation_semantics.py`

A pure-data mapping from annotation names to semantic roles:

- [ ] Define `SemanticRole` enum (rpc_provider, rpc_consumer, http_controller, http_endpoint, service, repository, component, scheduled_task, message_listener, transaction)
- [ ] Define `AnnotationSemantic` dataclass (role, target, framework)
- [ ] Define `ANNOTATION_SEMANTICS` dict covering:
  - Moa: MoaProvider, MoaConsumer
  - Dubbo: DubboService, DubboReference
  - Spring Web: Controller, RestController, RequestMapping, GetMapping, PostMapping, PutMapping, DeleteMapping
  - Spring Core: Service, Repository, Component, Scheduled, Transactional
  - Kafka: KafkaListener, KafkaHandler
  - Python: app.route, abstractmethod
- [ ] Provide `lookup_annotation(name: str) -> AnnotationSemantic | None` helper

### Module 3: Graph Model Extension

**File**: `store/schema.py`

- [ ] Add `PROVIDES_RPC` and `CONSUMES_RPC` to `EdgeType`
- [ ] Document new node properties: `annotations`, `semantic_roles`, `parameters`, `return_type`

### Module 4: CodeGraphBuilder Enhancement

**File**: `indexer/code_graph_builder.py`

- [ ] Store `decorators` → `annotations` property on Function and Class nodes
- [ ] Lookup annotation semantics and store matched roles in `semantic_roles` list property
- [ ] Store `parameters` and `return_type` from ParsedFunction
- [ ] For RPC provider classes: create `PROVIDES_RPC` edges from Class to Module
- [ ] For RPC consumer methods: create `CONSUMES_RPC` edges from Function to a target (if resolvable)

### Module 5: BusinessFlowInferencer Refactor

**File**: `indexer/business_flow_inferencer.py`

- [ ] Replace `f.signature CONTAINS '@RequestMapping'` with `'http_endpoint' IN f.semantic_roles`
- [ ] Replace all other annotation string matching with semantic_roles queries
- [ ] Add `'rpc_provider' IN n.semantic_roles` for class-level entry points (query Class nodes too)

### Module 6: Index Quality Report

**New file**: `indexer/index_report.py`

- [ ] Define `IndexReport` dataclass with:
  - total_files, success_files, skipped_files, failed_files
  - failed_file_list: list[dict] with file path and error message
  - node_counts: dict[str, int] (by label)
  - edge_counts: dict[str, int] (by edge type)
  - annotation_counts: dict[str, int] (by annotation name)
  - type_coverage: float (ratio of functions with type info)
  - duration_seconds: float

**File**: `indexer/incremental_indexer.py`

- [ ] Collect statistics during indexing
- [ ] Return `IndexReport` from `index_full` and `index_incremental`

**File**: `main.py`

- [ ] Add `/api/v1/index/report/{repository}` endpoint
- [ ] Store latest IndexReport per repository

**File**: `dashboard/src/pages/Repositories.tsx` (optional enhancement)

- [ ] Show index quality badge (healthy/degraded/error) based on report data

### Module 7: Type Information Extraction

**File**: `indexer/tree_sitter_parser.py`

- [ ] Add `parameters: list[dict[str, str]]` field to `ParsedFunction` (name, type pairs)
- [ ] Add `return_type: str` field to `ParsedFunction`
- [ ] Implement `_extract_parameters` for Java (formal_parameters → formal_parameter → type + name)
- [ ] Implement `_extract_parameters` for Python (typed_parameter, typed_default_parameter)
- [ ] Implement `_extract_return_type` for Java (method return type node)
- [ ] Implement `_extract_return_type` for Python (return_type annotation after ->)
- [ ] Implement for TypeScript/Go as well

## Implementation Order

1. Module 1 + 2 (annotation extraction + semantics) — foundation for everything else
2. Module 3 + 4 (schema + graph builder) — make annotations queryable
3. Module 5 (inferencer refactor) — immediate reliability improvement
4. Module 7 (type information) — independent track
5. Module 6 (index report) — depends on all above for meaningful metrics

## Testing Strategy

- Unit tests for `_extract_decorators` with Java/Python/TS sample code
- Unit tests for annotation semantic lookup
- Integration test: index a Java file with @MoaProvider and verify graph nodes have correct semantic_roles
- Index report validation: verify counts match expected values for a known codebase
