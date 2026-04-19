# B1: Parent-Child Chunk Strategy

**Created:** 2026-04-19T14:20:50  
**Status:** AwaitingApproval  
**Scope:** Indexer + Retrieval + MCP Response  
**Estimated Effort:** 6-8 hours (3 phases)  
**Risk Level:** Low (phased rollout with feature flag)

---

## 1. Problem Statement

### Current Chunking

| Entity Type | Chunk Strategy | Typical Size | Issue |
|------------|---------------|-------------|-------|
| Function | 1 AST node = 1 chunk | 10-500 lines | Large functions produce diluted embeddings |
| Class | 1 AST node = 1 chunk | 20-1000 lines | Entire class in one vector = too broad |
| Document | smart_chunker @ ~900 tokens | ~900 tokens | Reasonable but could be finer |
| Module | 1 file = 1 node | Metadata only | No body content, ok as-is |

### Impact on Retrieval Quality

1. **Embedding dilution**: A 200-line function embedding blends ALL semantics. Query "retry logic" matches weakly because retry is 10 lines out of 200.
2. **Context bloat for agents**: Retrieving 5 full functions = 500-2500 lines of code. Agent context window fills with irrelevant code, increasing hallucination risk.
3. **Equal weight problem**: A 10-line utility and a 200-line complex function have the same retrieval significance.

### Industry Benchmark

| System | Chunk Strategy |
|--------|---------------|
| LlamaIndex | ParentDocumentRetriever: small chunks for search, large for context |
| LangChain | ParentDocumentRetriever + RecursiveCharacterTextSplitter |
| Cursor (internal) | ~200 token chunks with context expansion |
| Devy | AST-aware splitting with sliding windows |

---

## 2. Design

### 2.1 Core Concept

```
                    ┌──────────────────────────┐
                    │  Parent (Function node)   │
                    │  - full code_snippet      │
                    │  - signature, docstring   │
                    │  - file, start_line       │
                    │  - embedding (existing)   │
                    └──────┬───────────────────┘
                           │ PART_OF (×N)
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ Chunk #0 │ │ Chunk #1 │ │ Chunk #2 │
       │ ~200 tok │ │ ~200 tok │ │ ~200 tok │
       │ sig+code │ │ sig+code │ │ sig+code │
       │ embedding│ │ embedding│ │ embedding│
       └──────────┘ └──────────┘ └──────────┘
```

**Search**: Query → search Chunk vectors (precise) → group by parent → return matched excerpt + parent metadata  
**Fallback**: If no chunk matches, search parent vectors (existing behavior)

### 2.2 Schema Changes

```python
# store/schema.py additions
class NodeLabel(StrEnum):
    # ... existing ...
    CHUNK = "Chunk"         # New: sub-entity chunk

class EdgeType(StrEnum):
    # ... existing ...
    PART_OF = "PART_OF"     # New: Chunk → Parent

VECTOR_INDEX_CONFIGS = [
    # ... existing ...
    {"label": NodeLabel.CHUNK, "attribute": "embedding", "similarity": "cosine"},
]
```

**Chunk node properties:**

| Property | Type | Description |
|----------|------|-------------|
| `text` | str | The chunk content (signature prefix + code/doc block) |
| `parent_uid` | str | UID of parent Function/Class/Document node |
| `parent_label` | str | "Function" / "Class" / "Document" |
| `parent_name` | str | Name of parent entity (for display) |
| `chunk_index` | int | Position within parent (0-based) |
| `file` | str | Same as parent file |
| `start_line` | int | Absolute line number within the file |
| `end_line` | int | Absolute line number within the file |
| `repository` | str | Same as parent |
| `indexed_at` | str | ISO timestamp |
| `embedding` | list[float] | 1024-dim vector |

### 2.3 Child Chunking Algorithm

**Sliding window** approach (language-agnostic, proven in production RAG):

```python
# indexer/child_chunker.py

WINDOW_CHARS = 800     # ~200 tokens
STRIDE_CHARS = 600     # ~150 tokens (25% overlap)
MIN_PARENT_CHARS = 400 # Only chunk parents > 400 chars (~100 tokens)

def chunk_code_entity(
    code_snippet: str,
    signature: str,
    entity_name: str,
    start_line: int,
) -> list[ChildChunk]:
    """Sliding window chunking with signature prefix."""
    if len(code_snippet) < MIN_PARENT_CHARS:
        return []  # Small entities don't need children

    prefix = f"// In {entity_name}: {signature}\n"
    lines = code_snippet.split("\n")
    # ... sliding window over lines, respecting line boundaries
    # Each window = prefix + window_lines
```

**Key properties:**
- Window: 800 chars (~200 tokens)
- Stride: 600 chars (~150 tokens) = 25% overlap
- Each chunk prefixed with entity signature for embedding context
- Minimum parent size: 400 chars (skip small entities)
- Split at line boundaries (never mid-line)

### 2.4 Retrieval Flow

```
Query "how does retry work in processOrder"
    │
    ▼
┌─────────────────────────────┐
│ 1. Search Chunk vectors     │  ← More precise: chunk about retry logic
│    (k=15, top chunks)       │     scores higher than full function
│                             │
│ 2. Group by parent_uid      │  ← Deduplicate: if 3 chunks from same
│    (merge overlapping)      │     function, merge into one excerpt
│                             │
│ 3. Fetch parent metadata    │  ← Add: file, signature, class context
│    (signature, docstring)   │
│                             │
│ 4. Fallback: parent search  │  ← If no chunk hits, search Function/Class
│    (existing behavior)      │     vectors (backward compatible)
└─────────────────────────────┘
    │
    ▼
Response:
{
  "semantic_matches": [
    {
      "name": "processOrder",
      "type": "Function",
      "file": "order_service.py",
      "start_line": 45,
      "matched_excerpt": "// In processOrder(order_id: str)\n  for attempt in range(3):\n    try:\n      result = api.submit(order)\n    except TimeoutError:\n      if attempt == 2: raise\n      time.sleep(2 ** attempt)",
      "excerpt_lines": [67, 73],
      "confidence": 0.92,
      "score": 0.87
    }
  ]
}
```

### 2.5 Configuration

```python
# config.py addition
class HybridSearchConfig(BaseModel):
    use_child_chunks: bool = False  # Feature flag, off by default
    child_chunk_window_chars: int = 800
    child_chunk_stride_chars: int = 600
    child_chunk_min_parent_chars: int = 400
```

---

## 3. Implementation Phases

### Phase 1: Schema + Generation (Zero Risk)

Generate child chunks during indexing, store in graph. No retrieval changes.

- [ ] P1.1: Add `NodeLabel.CHUNK`, `EdgeType.PART_OF` to `store/schema.py`
- [ ] P1.2: Add Chunk vector index to `VECTOR_INDEX_CONFIGS`
- [ ] P1.3: Create `indexer/child_chunker.py` with sliding window algorithm
- [ ] P1.4: In `code_graph_builder.py`, generate Chunk nodes after Function/Class creation
- [ ] P1.5: In `doc_indexer.py`, generate Chunk nodes for large document sections
- [ ] P1.6: Ensure `batch_upsert` handles Chunk nodes and PART_OF edges
- [ ] P1.7: Tests: `test_child_chunker.py` (unit), `test_chunk_generation.py` (integration)

### Phase 2: Chunk-Aware Retrieval (Opt-in)

Add chunk search behind feature flag.

- [ ] P2.1: In `semantic_query.py`, add `search_chunks(query, k)` method
- [ ] P2.2: In `semantic_query.py`, add `search_with_parent_context(query, k)` method
- [ ] P2.3: In `hybrid_query.py`, use chunk search when `use_child_chunks=True`
- [ ] P2.4: Add `matched_excerpt` and `excerpt_lines` to result format
- [ ] P2.5: Config flag `HYBRID_SEARCH__USE_CHILD_CHUNKS`
- [ ] P2.6: Tests: `test_chunk_retrieval.py`

### Phase 3: Activate + MCP Enhancement

Make chunk retrieval the default, enhance MCP responses.

- [ ] P3.1: Set `use_child_chunks=True` as default
- [ ] P3.2: MCP `rag_query` includes `matched_excerpt` in results
- [ ] P3.3: `get_complete_context` uses chunk-level precision
- [ ] P3.4: Performance benchmark: compare retrieval latency before/after
- [ ] P3.5: Quality benchmark: manual evaluation of top-5 relevance

---

## 4. Sizing Estimates

| Metric | Before | After |
|--------|--------|-------|
| Nodes per 1000 functions | 1,000 | ~4,000 (1000 parents + ~3000 chunks) |
| Embedding calls per function | 1 | ~4 (1 parent + ~3 chunks) |
| Vector index size | 1× | ~4× |
| Indexing time | 1× | ~1.3× (embedding is batched) |
| Search latency | 1× | ~1.1× (one more vector search) |
| Retrieval precision | Baseline | Expected +20-30% (from RAG literature) |

---

## 5. Test Plan

### Unit Tests
- [ ] `test_child_chunker.py`: Window sizes, overlap, signature prefix, min-size threshold
- [ ] `test_chunk_schema.py`: Chunk node creation with all required properties

### Integration Tests
- [ ] `test_chunk_generation.py`: Indexing produces expected chunk count per entity
- [ ] `test_chunk_retrieval.py`: Chunk search returns parent metadata correctly
- [ ] `test_chunk_dedup.py`: Multiple chunks from same parent are merged

### Quality Tests (Manual)
- [ ] Compare retrieval relevance before/after on 10 representative queries
- [ ] Measure matched_excerpt usefulness for agent context

---

## 6. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Index size growth (4×) | High | Low | FalkorDB handles well; chunk nodes are small |
| Indexing time increase | Medium | Low | Embedding batched; ~30% increase acceptable |
| Chunk boundary misses context | Medium | Medium | 25% overlap ensures key content in ≥1 chunk |
| Regression in existing search | Low | High | Phase 1 = generation only; Phase 2 = opt-in flag |
| Small functions get unnecessary chunks | Low | Low | MIN_PARENT_CHARS=400 threshold prevents this |

---

## 7. Non-Goals (Out of Scope)

- Recursive multi-level chunking (not needed for code entities)
- Agentic chunk re-ranking (future enhancement)
- Cross-entity chunk merging (too complex for first iteration)
- Changing the existing parent-level vectors (they remain for backward compatibility)
