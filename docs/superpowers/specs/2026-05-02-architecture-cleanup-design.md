# Architecture Cleanup: B-02/03/04/05/06

**Created**: 2026-05-02  
**Status**: Approved  
**Addresses**: B-02, B-03, B-04, B-05, B-06

---

## Phase 1: B-02 (Lifespan Split) + B-03 (Redis Interface)

### B-02: Lifespan Decomposition

**Problem**: `main.py` concentrates ~250 lines of startup/shutdown across `lifespan()`, `_init_security()`, `_init_core_services()`, `_init_wiki_and_lint()`, `_shutdown_all()`.

**Solution**: Extract into `core/startup/` subpackage:

```
core/startup/
├── __init__.py          # re-exports: init_security, init_core_services, init_wiki_and_lint, shutdown_all
├── security.py          # _enforce_production_security, _startup_auth_gate, init_security
├── core_services.py     # init_core_services (registry, scheduler, settings_store, graph adapter)
└── wiki.py              # init_wiki_and_lint (webhook, lint factory, bootstrap_wiki, lint scheduler)
```

`main.py` `lifespan()` becomes a thin orchestrator calling these functions. `_shutdown_all` also moves to `core/startup/__init__.py`.

**Rules**: Pure mechanical move. No behavior change. All existing tests must pass without modification.

### B-03: Redis Interface Formalization

**Problem**: `wiki/bootstrap.py` probes `kb.store._redis`, `kb.store._graph._redis`, `kb.store._db.connection` to obtain a Redis client.

**Solution**: Add public method to `FalkorDBStore`:

```python
def get_redis_client(self) -> Any | None:
    """Return the underlying Redis client if available."""
    for attr in ("redis", "_redis"):
        conn = getattr(self, attr, None)
        if conn is not None:
            return conn
    graph = getattr(self, "_graph", None)
    if graph is not None:
        conn = getattr(graph, "_redis", None)
        if conn is not None:
            return conn
    return None
```

`wiki/bootstrap.py` replaces the multi-step probe with `kb.store.get_redis_client()`, keeping the `_db.connection` fallback as last resort.

---

## Phase 2: B-04 (MCP Server Split) + B-05 (CodeGraphBuilder Split)

### B-04: MCP Server Decomposition (1789 lines → ~6 files)

```
api/mcp/
├── __init__.py
├── manifests.py             # MCP_TOOLS_MANIFEST dict
├── formatters.py            # _format_* helpers
├── handlers/
│   ├── __init__.py
│   ├── search_graph.py      # rag_query, rag_graph, graph_path
│   ├── source_context.py    # get_file_content, get_code_snippet, get_complete_context
│   └── analysis.py          # analyze_code, analyze_changes, search_architecture, get_insights
└── document_indexer.py      # KnowledgeBaseDocumentIndexer
```

`api/mcp_server.py` retains `KnowledgeBaseMCPHandler` as facade (~200 lines) with tool dispatch delegating to handler modules. `@mcp_tool` decorators stay on handler functions; `collect_tools` and `TOOL_ROLES` aggregate from all handlers.

### B-05: CodeGraphBuilder Decomposition (1139 lines → ~4 files)

```
indexer/
├── code_graph_builder.py      # CodeGraphBuilder facade (~500 lines)
├── graph_fqn.py               # compute_fqn + all FQN helpers
├── spring_di_graph.py         # Spring DI detection + constructor injection merge
└── cross_file_resolver.py     # _CrossFileData, symbol tables, cross-file edge resolution
```

`CodeGraphBuilder` remains the public API; extracted modules are internal implementation details.

---

## Phase 3: B-06 (FalkorDBStore Split)

### B-06: FalkorDBStore Decomposition (1241 lines → ~5 files)

```
store/
├── falkordb_store.py          # FalkorDBStore facade + connection management (~300 lines)
├── falkordb_writes.py         # upsert_node/edge, batch_upsert, deletes
├── falkordb_search.py         # vector_search, keyword_search
├── falkordb_wiki.py           # persist_wiki_pages, wiki path expressions
└── falkordb_reads.py          # find_node_*, get_repo_stats, graph traversal queries
```

`FalkorDBStore` uses composition (internal module instances) or mixin pattern. Public API unchanged — all existing callers continue using `FalkorDBStore` methods.

**High risk**: Shared `_graph` executor and connection state. Extract one slice at a time (search first, then wiki, then writes).

---

## Test Strategy

Each phase:
1. No new features — pure refactoring
2. All existing tests must pass without modification
3. `import` paths may change but public API stays identical
4. Add `__init__.py` re-exports to maintain backward compatibility
