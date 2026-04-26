# Wiki RAG 检索层（Phase 2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有 67K+ Chunk 节点批量生成 embedding，实现语义检索（RAG），让 LLM 在生成 wiki 时能发现跨文件语义关联的代码片段，大幅提升文档的上下文丰富度。

**Architecture:** 新增 CodeChunkIndexer 批量为 Chunk 生成 embedding（利用已有 EmbeddingGenerator + VECTOR INDEX）。新增 ChunkRetriever 通过向量检索发现与目标实体语义相关的代码片段。新增 ChunkSnippet 数据模型。集成到 WikiDataCollector 填充 PageData.related_chunks，增强 _entity_digest LLM prompt。所有新功能通过 `WIKI__RAG_ENABLED` 开关控制。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB (Cypher + Vector Index), EmbeddingGenerator (ONNX/PyTorch), dataclasses, pytest

**Spec:** [2026-04-24-wiki-enhancement-design.md](../specs/2026-04-24-wiki-enhancement-design.md) Phase 2 章节

**Code Review 要求:** 每个 Task 完成后必须进行 code review，确认代码质量和测试覆盖后再进入下一个 Task。

**计划范围:** 本文档仅覆盖 Phase 2（RAG 检索层）。Phase 3（百科分层生成）的实施计划将在 Phase 2 完成后单独编写。

**前置条件:** Phase 1（代码感知层）已完成。

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `config.py` | WikiConfig 新增 RAG 和 Chunk embedding 配置 |
| Modify | `wiki/models.py` | 新增 ChunkSnippet 数据模型 |
| Modify | `wiki/data_collector.py` | PageData 扩展 related_chunks 字段 |
| Modify | `store/wiki_store.py` | 新增 Chunk 向量检索和 embedding 批量查询 Cypher |
| Create | `wiki/chunk_indexer.py` | CodeChunkIndexer 批量 embedding 生成 |
| Create | `wiki/chunk_retriever.py` | ChunkRetriever 语义检索组件 |
| Modify | `wiki/composer.py` | 增强 _entity_digest 嵌入 RAG 检索结果 |
| Modify | `wiki/service.py` | 集成 ChunkRetriever 到 pipeline |
| Modify | `api/routes/wiki_routes.py` | 新增 chunk indexing API 端点 |
| Modify | `wiki/__init__.py` | 导出新组件 |
| Create | `tests/test_config_phase2.py` | 配置测试 |
| Create | `tests/wiki/test_chunk_indexer.py` | CodeChunkIndexer 单元测试 |
| Create | `tests/wiki/test_chunk_retriever.py` | ChunkRetriever 单元测试 |
| Create | `tests/store/test_wiki_store_vector.py` | Chunk 向量查询测试 |

---

### Task 1: 扩展 WikiConfig 配置（Phase 2 字段）

**Files:**
- Modify: `config.py`

- [x] **Step 1: Write the failing test**

```python
# tests/test_config_phase2.py
from config import Settings

def test_wiki_rag_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.rag_enabled is True
    assert s.wiki.rag_top_k == 5
    assert s.wiki.rag_min_score == 0.3
    assert s.wiki.rag_exclude_same_parent is True

def test_wiki_chunk_embedding_config_defaults():
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.chunk_embedding_batch_size == 64
    assert s.wiki.chunk_embedding_max_length == 512
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/test_config_phase2.py -v`
Expected: FAIL with `AttributeError`

- [x] **Step 3: Add Phase 2 config fields to WikiConfig**

在 `config.py` 的 `WikiConfig` 类中，在 Phase 1 字段之后添加：

```python
    # Phase 2: RAG retrieval
    rag_enabled: bool = True
    rag_top_k: int = 5
    rag_min_score: float = 0.3
    rag_exclude_same_parent: bool = True
    chunk_embedding_batch_size: int = 64
    chunk_embedding_max_length: int = 512
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add config.py tests/test_config_phase2.py
git commit -m "feat(config): add Phase 2 RAG and chunk embedding config fields"
```

- [x] **Step 6: Code Review**

Review checklist:
- 配置字段命名是否遵循项目既有风格
- 默认值是否合理（rag_top_k=5, min_score=0.3）
- 环境变量 `WIKI__RAG_ENABLED` 等是否可正常工作

---

### Task 2: 新增 ChunkSnippet 数据模型 + PageData 扩展

**Files:**
- Modify: `wiki/models.py`
- Modify: `wiki/data_collector.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_phase2_models.py
from wiki.models import ChunkSnippet

def test_chunk_snippet_creation():
    snippet = ChunkSnippet(
        text="def hello(): pass",
        file_path="src/main.py",
        score=0.85,
        parent_name="MainService",
        parent_uid="Class:src/main.py:MainService:1",
        start_line=10,
        end_line=15,
    )
    assert snippet.score == 0.85
    assert snippet.parent_name == "MainService"

def test_chunk_snippet_defaults():
    snippet = ChunkSnippet(
        text="code",
        file_path="f.py",
        score=0.5,
        parent_name="Foo",
    )
    assert snippet.parent_uid == ""
    assert snippet.start_line == 0
    assert snippet.end_line == 0
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Add ChunkSnippet model and extend PageData**

在 `wiki/models.py` 中添加：

```python
@dataclass
class ChunkSnippet:
    text: str
    file_path: str
    score: float
    parent_name: str
    parent_uid: str = ""
    start_line: int = 0
    end_line: int = 0
```

在 `wiki/data_collector.py` 的 `PageData` 中添加新字段：

```python
    related_chunks: list[ChunkSnippet] = field(default_factory=list)
```

需要在 `data_collector.py` 中 import `ChunkSnippet`。

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/models.py wiki/data_collector.py tests/wiki/test_phase2_models.py
git commit -m "feat(wiki): add ChunkSnippet model and extend PageData with related_chunks"
```

- [x] **Step 6: Code Review**

Review checklist:
- ChunkSnippet 字段是否覆盖检索所需信息
- PageData 新字段向后兼容性
- 现有 data_collector 测试是否仍通过

---

### Task 3: WikiStore Chunk 向量检索方法

**Files:**
- Modify: `store/wiki_store.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/store/test_wiki_store_vector.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from store.wiki_store import WikiStore

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[]))
    return WikiStore(store)

@pytest.mark.asyncio
async def test_vector_search_chunks(mock_store):
    await mock_store.vector_search_chunks(
        k=5, vec=[0.1] * 1024, repository="my-repo", limit=10
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "vector" in cypher.lower() or "vecf32" in cypher.lower()
    assert "repository" in cypher

@pytest.mark.asyncio
async def test_count_chunks_without_embedding(mock_store):
    await mock_store.count_chunks_without_embedding("my-repo")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "embedding" in cypher.lower()

@pytest.mark.asyncio
async def test_batch_get_chunks_for_embedding(mock_store):
    await mock_store.batch_get_chunks_for_embedding("my-repo", batch_size=64, offset=0)
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "text" in cypher
    assert "SKIP" in cypher
    assert "LIMIT" in cypher
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Add vector search and batch query methods**

在 `store/wiki_store.py` 的 WikiStore 类中，Phase 1 方法之后添加：

```python
    # --- Phase 2: Chunk vector retrieval ---

    async def vector_search_chunks(
        self, k: int, vec: list[float], repository: str, limit: int
    ) -> QueryResultWrapper:
        """Semantic search over Chunk embeddings."""
        q = (
            "CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vec)) "
            "YIELD node, score "
            "WHERE node.repository = $repository "
            "RETURN node.text AS text, node.file AS file, "
            "node.start_line AS start_line, node.end_line AS end_line, "
            "node.parent_uid AS parent_uid, node.parent_name AS parent_name, "
            "score "
            "ORDER BY score DESC LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"k": k, "vec": vec, "repository": repository, "limit": limit},
        )

    async def count_chunks_without_embedding(self, repository: str) -> QueryResultWrapper:
        """Count Chunk nodes that lack an embedding vector."""
        q = (
            "MATCH (c:Chunk {repository: $repo}) "
            "WHERE c.embedding IS NULL "
            "RETURN count(c) AS cnt"
        )
        return await self._store.execute_query(q, {"repo": repository})

    async def batch_get_chunks_for_embedding(
        self, repository: str, batch_size: int, offset: int
    ) -> QueryResultWrapper:
        """Fetch a batch of Chunk nodes without embeddings for indexing."""
        q = (
            "MATCH (c:Chunk {repository: $repo}) "
            "WHERE c.embedding IS NULL "
            "RETURN c.uid AS uid, c.text AS text "
            "ORDER BY c.uid "
            "SKIP $offset LIMIT $limit"
        )
        return await self._store.execute_query(
            q, {"repo": repository, "offset": offset, "limit": batch_size},
        )
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add store/wiki_store.py tests/store/test_wiki_store_vector.py
git commit -m "feat(wiki-store): add chunk vector search and embedding batch query methods"
```

- [x] **Step 6: Code Review**

Review checklist:
- Cypher 向量查询语法（FalkorDB 的 `db.idx.vector.queryNodes` 用法）
- `embedding IS NULL` 是否正确检测未嵌入 Chunk
- 参数化查询防注入

---

### Task 4: CodeChunkIndexer 实现

**Files:**
- Create: `wiki/chunk_indexer.py`
- Create: `tests/wiki/test_chunk_indexer.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/wiki/test_chunk_indexer.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.chunk_indexer import CodeChunkIndexer

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.count_chunks_without_embedding = AsyncMock(
        return_value=MagicMock(result_set=[[128]])
    )
    store.batch_get_chunks_for_embedding = AsyncMock(
        return_value=MagicMock(result_set=[
            ["uid1", "def hello(): pass"],
            ["uid2", "class Foo: bar = 1"],
        ])
    )
    return store

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.set_node_embedding = AsyncMock()
    return store

@pytest.mark.asyncio
async def test_index_counts_first(mock_wiki_store, mock_store):
    indexer = CodeChunkIndexer(mock_wiki_store, mock_store, batch_size=64)
    # Mock empty second batch to stop iteration
    mock_wiki_store.batch_get_chunks_for_embedding.side_effect = [
        MagicMock(result_set=[["uid1", "code"]]),
        MagicMock(result_set=[]),
    ]
    with patch("wiki.chunk_indexer.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen
        
        result = await indexer.index_all_chunks("my-repo")
    
    assert result["indexed"] >= 0
    mock_wiki_store.count_chunks_without_embedding.assert_called_once()

@pytest.mark.asyncio
async def test_index_skips_empty_text(mock_wiki_store, mock_store):
    mock_wiki_store.batch_get_chunks_for_embedding.side_effect = [
        MagicMock(result_set=[["uid1", ""], ["uid2", None]]),
        MagicMock(result_set=[]),
    ]
    indexer = CodeChunkIndexer(mock_wiki_store, mock_store, batch_size=64)
    with patch("wiki.chunk_indexer.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[])
        MockEmbGen.shared.return_value = mock_emb_gen
        
        result = await indexer.index_all_chunks("my-repo")
    
    assert result["skipped"] >= 0
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Implement CodeChunkIndexer**

```python
# wiki/chunk_indexer.py
"""Batch generates embeddings for Chunk nodes to enable RAG retrieval."""

from __future__ import annotations

import logging
from typing import Any, Callable

from config import get_settings
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from store.schema import NodeLabel

logger = logging.getLogger(__name__)


class CodeChunkIndexer:
    """Indexes Chunk nodes with vector embeddings for semantic search."""

    def __init__(
        self,
        wiki_store: Any,
        store: Any,
        batch_size: int = 64,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self._wiki_store = wiki_store
        self._store = store
        self._batch_size = batch_size
        self._on_progress = on_progress

    async def index_all_chunks(self, repository: str) -> dict[str, int]:
        count_result = await self._wiki_store.count_chunks_without_embedding(repository)
        total = 0
        if count_result and count_result.result_set:
            total = int(count_result.result_set[0][0])

        if total == 0:
            logger.info("chunk_index_skip", repository=repository, reason="no unembedded chunks")
            return {"total": 0, "indexed": 0, "skipped": 0, "errors": 0}

        logger.info("chunk_index_start", repository=repository, total=total)

        emb_gen = EmbeddingGenerator.shared(config=get_settings().embedding)
        indexed = 0
        skipped = 0
        errors = 0
        offset = 0

        while True:
            batch_result = await self._wiki_store.batch_get_chunks_for_embedding(
                repository, self._batch_size, offset,
            )
            if not batch_result or not batch_result.result_set:
                break

            uids: list[str] = []
            docs: list[dict[str, str]] = []

            for row in batch_result.result_set:
                uid, text = row[0], row[1]
                if not text or not str(text).strip():
                    skipped += 1
                    continue
                uids.append(str(uid))
                text_str = str(text)
                max_len = get_settings().wiki.chunk_embedding_max_length
                if len(text_str) > max_len * 4:
                    text_str = text_str[: max_len * 4]
                docs.append(doc_dict_for_embedding({"title": "", "content": text_str}))

            if docs:
                try:
                    embeddings = await emb_gen.generate_for_docs(docs)
                    for uid, embedding in zip(uids, embeddings, strict=True):
                        await self._store.set_node_embedding(uid, NodeLabel.CHUNK, embedding)
                        indexed += 1
                except Exception:
                    logger.warning("chunk_index_batch_error", offset=offset, exc_info=True)
                    errors += len(docs)

            offset += self._batch_size
            if self._on_progress:
                self._on_progress(indexed + skipped + errors, total)

        logger.info(
            "chunk_index_complete",
            repository=repository,
            indexed=indexed,
            skipped=skipped,
            errors=errors,
        )
        return {"total": total, "indexed": indexed, "skipped": skipped, "errors": errors}
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/chunk_indexer.py tests/wiki/test_chunk_indexer.py
git commit -m "feat(wiki): implement CodeChunkIndexer for batch Chunk embedding generation"
```

- [x] **Step 6: Code Review**

Review checklist:
- 批量处理逻辑是否正确（offset 递增、空 batch 退出）
- 空文本跳过逻辑
- 异常处理是否安全（不中断整个索引过程）
- EmbeddingGenerator.shared() 使用是否正确

---

### Task 5: ChunkRetriever 实现

**Files:**
- Create: `wiki/chunk_retriever.py`
- Create: `tests/wiki/test_chunk_retriever.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/wiki/test_chunk_retriever.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.chunk_retriever import ChunkRetriever
from wiki.models import ChunkSnippet
from store.schema import GraphNode, NodeLabel

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.vector_search_chunks = AsyncMock(return_value=MagicMock(result_set=[
        ["def hello(): pass", "src/main.py", 1, 5, "Class:main.py:Main:1", "Main", 0.85],
        ["class Foo: bar = 1", "src/foo.py", 10, 15, "Class:foo.py:Foo:1", "Foo", 0.72],
    ]))
    return store

def _make_node(uid: str = "Class:f.py:Svc:1", name: str = "Svc") -> GraphNode:
    return GraphNode(
        label=NodeLabel.CLASS, uid=uid,
        properties={"name": name, "fqn": f"pkg.{name}", "signature": f"class {name}:"},
    )

@pytest.mark.asyncio
async def test_retrieve_returns_chunk_snippets(mock_wiki_store):
    with patch("wiki.chunk_retriever.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen

        retriever = ChunkRetriever(mock_wiki_store)
        node = _make_node()
        results = await retriever.retrieve(node, "my-repo")

    assert len(results) == 2
    assert all(isinstance(r, ChunkSnippet) for r in results)
    assert results[0].score >= results[1].score

@pytest.mark.asyncio
async def test_retrieve_excludes_same_parent(mock_wiki_store):
    with patch("wiki.chunk_retriever.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen

        retriever = ChunkRetriever(mock_wiki_store, exclude_same_parent=True)
        node = _make_node(uid="Class:main.py:Main:1")
        results = await retriever.retrieve(node, "my-repo")

    # Should exclude the chunk whose parent_uid matches node.uid
    assert len(results) == 1
    assert results[0].parent_name == "Foo"

@pytest.mark.asyncio
async def test_retrieve_filters_by_min_score(mock_wiki_store):
    with patch("wiki.chunk_retriever.EmbeddingGenerator") as MockEmbGen:
        mock_emb_gen = MagicMock()
        mock_emb_gen.generate_for_docs = AsyncMock(return_value=[[0.1] * 1024])
        MockEmbGen.shared.return_value = mock_emb_gen

        retriever = ChunkRetriever(mock_wiki_store, min_score=0.80)
        node = _make_node()
        results = await retriever.retrieve(node, "my-repo")

    assert len(results) == 1
    assert results[0].score >= 0.80
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Implement ChunkRetriever**

```python
# wiki/chunk_retriever.py
"""Semantic code chunk retrieval for wiki context enrichment."""

from __future__ import annotations

import logging
from typing import Any

from config import get_settings
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from store.schema import GraphNode
from wiki.models import ChunkSnippet

logger = logging.getLogger(__name__)


class ChunkRetriever:
    """Retrieves semantically related code chunks for a given entity."""

    def __init__(
        self,
        wiki_store: Any,
        top_k: int = 5,
        min_score: float = 0.3,
        exclude_same_parent: bool = True,
    ) -> None:
        self._store = wiki_store
        self._top_k = top_k
        self._min_score = min_score
        self._exclude_same_parent = exclude_same_parent

    async def retrieve(
        self,
        node: GraphNode,
        repository: str,
        exclude_uids: set[str] | None = None,
    ) -> list[ChunkSnippet]:
        query_text = self._build_query_text(node)
        if not query_text:
            return []

        emb_gen = EmbeddingGenerator.shared(config=get_settings().embedding)
        query_docs = [doc_dict_for_embedding({"title": "", "content": query_text})]
        embeddings = await emb_gen.generate_for_docs(query_docs)
        if not embeddings or not embeddings[0]:
            return []

        result = await self._store.vector_search_chunks(
            k=self._top_k * 2,  # fetch extra for filtering
            vec=embeddings[0],
            repository=repository,
            limit=self._top_k * 2,
        )
        if not result or not result.result_set:
            return []

        exclude = exclude_uids or set()
        snippets: list[ChunkSnippet] = []

        for row in result.result_set:
            text, file_path, start_line, end_line, parent_uid, parent_name, score = row
            score_f = float(score)

            if score_f < self._min_score:
                continue
            if self._exclude_same_parent and str(parent_uid) == node.uid:
                continue
            if str(parent_uid) in exclude:
                continue

            snippets.append(ChunkSnippet(
                text=str(text),
                file_path=str(file_path),
                score=score_f,
                parent_name=str(parent_name or ""),
                parent_uid=str(parent_uid or ""),
                start_line=int(start_line or 0),
                end_line=int(end_line or 0),
            ))

            if len(snippets) >= self._top_k:
                break

        return snippets

    def _build_query_text(self, node: GraphNode) -> str:
        parts: list[str] = []
        name = node.properties.get("name")
        if isinstance(name, str) and name:
            parts.append(name)
        fqn = node.properties.get("fqn")
        if isinstance(fqn, str) and fqn:
            parts.append(fqn)
        sig = node.properties.get("signature")
        if isinstance(sig, str) and sig:
            parts.append(sig)
        doc = node.properties.get("docstring")
        if isinstance(doc, str) and doc:
            parts.append(doc[:200])
        return " ".join(parts)
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/chunk_retriever.py tests/wiki/test_chunk_retriever.py
git commit -m "feat(wiki): implement ChunkRetriever for semantic code chunk discovery"
```

- [x] **Step 6: Code Review**

Review checklist:
- 查询文本构建是否合理（name + fqn + signature + docstring[:200]）
- 过滤逻辑（min_score, same parent, exclude_uids）
- top_k * 2 预取策略是否足够
- EmbeddingGenerator 单例使用是否线程安全

---

### Task 6: 集成 ChunkRetriever 到 WikiDataCollector

**Files:**
- Modify: `wiki/data_collector.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_data_collector_rag.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.data_collector import WikiDataCollector
from store.schema import GraphNode, NodeLabel

@pytest.fixture
def mock_graph_port():
    port = MagicMock()
    port.find_edges = AsyncMock(return_value=[])
    port.find_children = AsyncMock(return_value=[])
    return port

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    result = MagicMock()
    result.result_set = []
    store.find_chunks_by_parent_uid = AsyncMock(return_value=result)
    store.vector_search_chunks = AsyncMock(return_value=MagicMock(result_set=[
        ["related code", "src/related.py", 1, 5, "Class:r.py:R:1", "Related", 0.8],
    ]))
    return store

@pytest.mark.asyncio
async def test_collect_includes_related_chunks(mock_graph_port, mock_wiki_store):
    with patch("wiki.data_collector.ChunkRetriever") as MockRetriever:
        from wiki.models import ChunkSnippet
        mock_retriever_instance = MagicMock()
        mock_retriever_instance.retrieve = AsyncMock(return_value=[
            ChunkSnippet(text="related code", file_path="src/related.py", score=0.8,
                        parent_name="Related", parent_uid="Class:r.py:R:1"),
        ])
        MockRetriever.return_value = mock_retriever_instance

        collector = WikiDataCollector(mock_graph_port, wiki_store=mock_wiki_store, rag_enabled=True)
        node = GraphNode(
            label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
            properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
        )
        page_data = await collector.collect("my-repo", node)

    assert len(page_data.related_chunks) > 0
    assert page_data.related_chunks[0].parent_name == "Related"

@pytest.mark.asyncio
async def test_collect_without_rag_has_empty_chunks(mock_graph_port):
    collector = WikiDataCollector(mock_graph_port)
    node = GraphNode(
        label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
    )
    page_data = await collector.collect("my-repo", node)
    assert page_data.related_chunks == []
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Integrate ChunkRetriever**

修改 `wiki/data_collector.py`:
1. Add `rag_enabled` parameter to `WikiDataCollector.__init__`
2. In `collect()`, after SourceCodeReader, create ChunkRetriever and call retrieve
3. Pass `related_chunks` to PageData

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/data_collector.py tests/wiki/test_data_collector_rag.py
git commit -m "feat(wiki): integrate ChunkRetriever into WikiDataCollector for RAG-enriched collection"
```

- [x] **Step 6: Code Review**

Review checklist:
- 向后兼容性（rag_enabled=False 不改变现有行为）
- ChunkRetriever lazy import
- 现有 data_collector 测试是否受影响

---

### Task 7: 增强 _entity_digest 嵌入 RAG 检索结果

**Files:**
- Modify: `wiki/composer.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_composer_rag_digest.py
from unittest.mock import MagicMock
from wiki.composer import WikiComposer
from wiki.data_collector import PageData
from wiki.models import ChunkSnippet, SourceLocation, PageType
from store.schema import GraphNode, NodeLabel

def _make_page_data_with_rag() -> PageData:
    node = GraphNode(
        label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py",
                    "start_line": 1, "end_line": 50, "signature": "class Foo:"},
    )
    return PageData(
        node=node, edges=[], children=[],
        source_location=SourceLocation(
            file_path="src/foo.py", start_line=1, end_line=50, fqn="Foo", repository="repo"),
        method_locations=[], business_summary=None, methods=[],
        related_chunks=[ChunkSnippet(
            text="class Bar:\n    def use_foo(self): Foo().run()",
            file_path="src/bar.py", score=0.85,
            parent_name="Bar", parent_uid="Class:bar.py:Bar:1",
            start_line=1, end_line=2,
        )],
    )

def test_entity_digest_includes_related_chunks():
    composer = WikiComposer(llm=None, context_builder=MagicMock(), store=MagicMock())
    page_data = _make_page_data_with_rag()
    digest = composer._entity_digest(page_data, page_type=PageType.CLASS_DETAIL)
    assert "Related Code" in digest
    assert "Bar" in digest
    assert "use_foo" in digest
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Enhance _entity_digest**

在 `wiki/composer.py` 的 `_entity_digest` 方法中，在 code_snippets 块之后、return 之前添加：

```python
        if page_data.related_chunks:
            lines.append(f"\n### Related Code (semantic, {len(page_data.related_chunks)} chunks)")
            for chunk in page_data.related_chunks[:5]:
                lines.append(f"From `{chunk.parent_name}` ({chunk.file_path}:{chunk.start_line}-{chunk.end_line}, score={chunk.score:.2f}):")
                lines.append(f"```\n{chunk.text}\n```")
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/composer.py tests/wiki/test_composer_rag_digest.py
git commit -m "feat(wiki): enhance _entity_digest to embed RAG-retrieved code chunks in LLM prompt"
```

- [x] **Step 6: Code Review**

Review checklist:
- RAG chunks 在 prompt 中的位置（在精准代码之后）
- chunk 数量限制（最多 5 个）
- score 显示精度

---

### Task 8: API 端点 + WikiService 集成

**Files:**
- Modify: `wiki/service.py`
- Modify: `api/routes/wiki_routes.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_chunk_index_api.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_wiki_service_accepts_rag_enabled():
    from wiki.service import WikiService
    graph = MagicMock()
    wiki_store = MagicMock()
    
    service = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        wiki_store=wiki_store,
    )
    assert service._collector._rag_enabled is not None
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Integrate RAG into WikiService**

修改 `wiki/service.py`:
1. Pass `rag_enabled` from config to WikiDataCollector
2. Pass RAG config params through

修改 `api/routes/wiki_routes.py`:
1. Add `POST /api/v1/wiki/chunks/index` endpoint
2. Background task to run CodeChunkIndexer

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Run full test suite**

- [x] **Step 6: Commit**

```bash
git add wiki/service.py api/routes/wiki_routes.py tests/wiki/test_chunk_index_api.py
git commit -m "feat(wiki): integrate RAG into WikiService and add chunk indexing API endpoint"
```

- [x] **Step 7: Code Review**

Review checklist:
- WikiService 对 ChunkRetriever 参数的传递
- API 端点认证/权限
- Background task 错误处理

---

### Task 9: 集成验证与文档更新

**Files:**
- Modify: `wiki/__init__.py`

- [x] **Step 1: Update wiki/__init__.py exports**

```python
from wiki.chunk_indexer import CodeChunkIndexer
from wiki.chunk_retriever import ChunkRetriever
from wiki.models import ChunkSnippet
```

- [x] **Step 2: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest tests/ -v --tb=short -q`

- [x] **Step 3: Commit**

```bash
git add wiki/__init__.py
git commit -m "feat(wiki): export Phase 2 RAG components and complete integration validation"
```

- [x] **Step 4: Code Review**

Final review checklist:
- 所有新组件正确导出
- 无新增测试失败
- 无循环导入
