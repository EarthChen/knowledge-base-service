# 语义搜索增强 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 knowledge-base-service 构建多层次业务语义搜索体系，包含 LLM 代码 enrichment、业务流程图谱、搜索引擎增强和 Dashboard LLM 增强搜索。

**Architecture:** 在现有 FalkorDB 图数据库上扩展业务语义层（BusinessFlow、BusinessConcept 节点），通过 LLM enrichment pipeline 自动生成业务摘要和流程关联，搜索引擎增加 cross-encoder reranking 和 6 类向量搜索，Dashboard 提供 LLM 增强的深度搜索。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB, BAAI/bge-m3 (embedding), BAAI/bge-reranker-v2-m3 (reranking), OpenAI-compatible LLM API, httpx (async HTTP), tenacity (retry)

**Design Spec:** `docs/superpowers/specs/2026-04-10-semantic-search-enhancement-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `llm/__init__.py` | Package init |
| `llm/provider.py` | LLM 兼容层 — OpenAI 协议 Provider，支持 acp-gateway 和直连 |
| `indexer/enrichment.py` | 代码摘要生成器 — 批量为 Function/Class 生成 business_summary |
| `indexer/business_flow_inferencer.py` | 业务流程推断器 — 从调用链推断 BusinessFlow |
| `indexer/concept_extractor.py` | 文档概念提取器 — 从文档提取 BusinessConcept |
| `query/reranker.py` | Cross-encoder reranking 模块 |
| `query/deep_search.py` | Dashboard LLM 增强搜索引擎 |
| `tests/test_llm_provider.py` | LLM Provider 测试 |
| `tests/test_enrichment.py` | Enrichment 测试 |
| `tests/test_business_flow_inferencer.py` | 流程推断测试 |
| `tests/test_concept_extractor.py` | 概念提取测试 |
| `tests/test_reranker.py` | Reranker 测试 |
| `tests/test_deep_search.py` | Deep search 测试 |

### Modified files

| File | Changes |
|------|---------|
| `config.py` | 新增 `LLMConfig`, `RerankConfig` 嵌套配置 |
| `store/schema.py` | 新增 `BUSINESS_FLOW`, `BUSINESS_CONCEPT` NodeLabel 和 4 种 EdgeType |
| `store/falkordb_store.py` | 新增向量索引配置，支持新节点类型的 CRUD |
| `indexer/embedding_generator.py` | 修改 `_format_code_text` 支持 business_summary 优先 |
| `indexer/incremental_indexer.py` | 集成 enrichment 流程，全量/增量索引时触发 |
| `query/semantic_query.py` | 扩展 `search_all` 支持 6 类向量搜索 |
| `query/graph_query.py` | 新增业务流程查询方法 |
| `query/hybrid_query.py` | 集成 reranking，扩展图扩展含业务流程上下文 |
| `api/mcp_server.py` | 扩展 MCP_TOOLS_MANIFEST，新增 rag_business_search 工具 |
| `service.py` | 注入新组件（LLMProvider, Reranker, DeepSearchEngine） |
| `main.py` | 新增 `/api/v1/deep-search` 路由，新增 `/api/v1/business/search` 路由 |

---

## Phase 1: LLM 基础 + 代码 Enrichment

### Task 1: LLM 兼容层

**Files:**
- Create: `llm/__init__.py`
- Create: `llm/provider.py`
- Modify: `config.py`
- Test: `tests/test_llm_provider.py`

- [ ] **Step 1: 新增 LLM 配置到 config.py**

在 `config.py` 中 `Settings` 类之前添加 `LLMConfig`：

```python
class LLMConfig(BaseModel):
    """Configuration for LLM provider (OpenAI-compatible protocol)."""
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    deep_search_model: str = "gpt-4o"
    max_concurrent: int = 10
    timeout: int = 30
    retry_count: int = 3
    temperature: float = 0.1
```

在 `Settings` 类中添加字段：

```python
llm: LLMConfig = LLMConfig()
```

- [ ] **Step 2: 编写 LLM Provider 测试**

创建 `tests/test_llm_provider.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from config import LLMConfig


@pytest.fixture
def llm_config():
    return LLMConfig(
        enabled=True,
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-4o-mini",
    )


class TestLLMProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_string(self, llm_config):
        from llm.provider import LLMProvider

        provider = LLMProvider(llm_config)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }
        with patch.object(provider, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider.complete([{"role": "user", "content": "hello"}])
        assert result == "test response"

    @pytest.mark.asyncio
    async def test_complete_json_returns_dict(self, llm_config):
        from llm.provider import LLMProvider

        provider = LLMProvider(llm_config)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"name": "test"}'}}]
        }
        with patch.object(provider, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result = await provider.complete_json(
                [{"role": "user", "content": "hello"}],
                schema={"type": "object"},
            )
        assert result == {"name": "test"}

    @pytest.mark.asyncio
    async def test_complete_retries_on_failure(self, llm_config):
        from llm.provider import LLMProvider

        llm_config.retry_count = 2
        provider = LLMProvider(llm_config)
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.raise_for_status = MagicMock(side_effect=Exception("Server Error"))
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        with patch.object(provider, "_client") as mock_client:
            mock_client.post = AsyncMock(side_effect=[fail_resp, ok_resp])
            result = await provider.complete([{"role": "user", "content": "hi"}])
        assert result == "ok"
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd knowledge-base-service && uv run pytest tests/test_llm_provider.py -v
```

Expected: FAIL（`llm/provider.py` 不存在）

- [ ] **Step 4: 实现 LLM Provider**

创建 `llm/__init__.py`：

```python
from llm.provider import LLMProvider

__all__ = ["LLMProvider"]
```

创建 `llm/provider.py`：

```python
"""OpenAI-compatible LLM provider with retry and concurrency control."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import LLMConfig

logger = logging.getLogger(__name__)


class LLMProvider:
    """Unified LLM provider supporting OpenAI API and acp-gateway."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(config.timeout),
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            **kwargs,
        }
        data = await self._request(body)
        return data["choices"][0]["message"]["content"]

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "response_format": {"type": "json_object"},
            **kwargs,
        }
        data = await self._request(body)
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        async with self._semaphore:
            resp = await self._client.post("/chat/completions", json=body)
            resp.raise_for_status()
            return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd knowledge-base-service && uv run pytest tests/test_llm_provider.py -v
```

Expected: 3 tests PASS

- [ ] **Step 6: 提交**

```bash
git add llm/ tests/test_llm_provider.py config.py
git commit -m "feat(llm): add OpenAI-compatible LLM provider with retry and concurrency"
```

---

### Task 2: 代码摘要生成器 (Code Summary Enricher)

**Files:**
- Create: `indexer/enrichment.py`
- Test: `tests/test_enrichment.py`

- [ ] **Step 1: 编写 Enricher 测试**

创建 `tests/test_enrichment.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from config import LLMConfig


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider

    llm = MagicMock(spec=LLMProvider)
    llm.complete = AsyncMock(return_value="此函数处理用户登录验证，属于用户认证业务领域。")
    return llm


class TestCodeSummaryEnricher:
    @pytest.mark.asyncio
    async def test_enrich_single_function(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher

        enricher = CodeSummaryEnricher(llm=mock_llm)
        items = [
            {
                "name": "authenticate",
                "signature": "def authenticate(username, password)",
                "docstring": "Authenticate user",
                "code_snippet": "def authenticate(username, password): ...",
                "file": "auth/service.py",
            }
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 1
        assert "登录" in results[0] or "认证" in results[0] or len(results[0]) > 0

    @pytest.mark.asyncio
    async def test_enrich_batch_groups_by_file(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher

        enricher = CodeSummaryEnricher(llm=mock_llm)
        items = [
            {"name": "func_a", "signature": "", "docstring": "", "code_snippet": "", "file": "a.py"},
            {"name": "func_b", "signature": "", "docstring": "", "code_snippet": "", "file": "a.py"},
            {"name": "func_c", "signature": "", "docstring": "", "code_snippet": "", "file": "b.py"},
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 3
        assert mock_llm.complete.call_count >= 1

    @pytest.mark.asyncio
    async def test_enrich_handles_llm_failure(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher

        mock_llm.complete = AsyncMock(side_effect=Exception("LLM error"))
        enricher = CodeSummaryEnricher(llm=mock_llm)
        items = [
            {"name": "func_a", "signature": "", "docstring": "", "code_snippet": "", "file": "a.py"},
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 1
        assert results[0] == ""
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd knowledge-base-service && uv run pytest tests/test_enrichment.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 CodeSummaryEnricher**

创建 `indexer/enrichment.py`：

```python
"""Code summary enrichment — generates business_summary via LLM."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """你是一个代码分析专家。请为以下代码生成一个简洁的业务语义描述。
要求：
1. 用自然语言描述这个函数/类的业务用途（而非技术实现）
2. 包含它属于哪个业务领域
3. 它在业务流程中扮演的角色
4. 不超过 200 字

代码信息:
文件: {file}
名称: {name}
签名: {signature}
文档: {docstring}
代码片段: {code_snippet}"""


class CodeSummaryEnricher:
    """Batch-generates business summaries for code entities using LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def enrich_batch(self, items: list[dict[str, str]]) -> list[str]:
        """Generate business_summary for each item. Returns list of summaries (same order as input).

        On LLM failure, returns empty string for that item.
        """
        results: list[str] = [""] * len(items)

        groups: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
        for idx, item in enumerate(items):
            groups[item.get("file", "unknown")].append((idx, item))

        tasks = [
            self._enrich_file_group(file_path, group, results)
            for file_path, group in groups.items()
        ]
        await asyncio.gather(*tasks)
        return results

    async def _enrich_file_group(
        self,
        file_path: str,
        group: list[tuple[int, dict[str, str]]],
        results: list[str],
    ) -> None:
        for idx, item in group:
            try:
                prompt = _SUMMARY_PROMPT.format(
                    file=file_path,
                    name=item.get("name", ""),
                    signature=item.get("signature", ""),
                    docstring=item.get("docstring", "")[:500],
                    code_snippet=item.get("code_snippet", "")[:1000],
                )
                summary = await self._llm.complete(
                    [{"role": "user", "content": prompt}]
                )
                results[idx] = summary.strip()
            except Exception:
                logger.warning("Failed to enrich %s in %s", item.get("name"), file_path, exc_info=True)
                results[idx] = ""

    async def enrich_single(self, item: dict[str, str]) -> str:
        """Generate business_summary for a single item."""
        summaries = await self.enrich_batch([item])
        return summaries[0]
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd knowledge-base-service && uv run pytest tests/test_enrichment.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: 提交**

```bash
git add indexer/enrichment.py tests/test_enrichment.py
git commit -m "feat(enrichment): add CodeSummaryEnricher for LLM business summary generation"
```

---

### Task 3: Embedding 生成增强

**Files:**
- Modify: `indexer/embedding_generator.py` (修改 `_format_code_text`)
- Modify: `indexer/incremental_indexer.py` (在 `_generate_and_store_embeddings` 中传递 `business_summary`)

- [ ] **Step 1: 修改 `_format_code_text` 支持 business_summary**

在 `indexer/embedding_generator.py` 中修改 `_format_code_text`：

```python
def _format_code_text(
    name: str,
    signature: str,
    docstring: str,
    code_snippet: str,
    business_summary: str = "",
) -> str:
    """Build a concise textual representation for embedding."""
    parts = []
    if business_summary:
        parts.append(f"Business: {business_summary}")
    if name:
        parts.append(f"Name: {name}")
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring and not business_summary:
        parts.append(f"Description: {docstring[:500]}")
    if code_snippet:
        parts.append(f"Code: {code_snippet[:1000]}")
    return "\n".join(parts)
```

- [ ] **Step 2: 修改 `generate_for_code` 传递 business_summary**

在 `indexer/embedding_generator.py` 的 `generate_for_code` 方法中：

```python
async def generate_for_code(self, items: list[dict[str, str]]) -> list[list[float]]:
    texts = [
        _format_code_text(
            item.get("name", ""),
            item.get("signature", ""),
            item.get("docstring", ""),
            item.get("code_snippet", ""),
            item.get("business_summary", ""),
        )
        for item in items
    ]
    return await self.generate(texts)
```

- [ ] **Step 3: 修改 `_generate_and_store_embeddings` 中的 items 构建**

在 `indexer/incremental_indexer.py` 的 `_generate_and_store_embeddings` 方法中，items 列表添加 `business_summary`：

```python
items = [
    {
        "name": n.properties.get("name", ""),
        "signature": n.properties.get("signature", ""),
        "docstring": n.properties.get("docstring", ""),
        "code_snippet": n.properties.get("code_snippet", n.properties.get("content", "")),
        "business_summary": n.properties.get("business_summary", ""),
    }
    for n in embeddable
]
```

- [ ] **Step 4: 运行现有测试确保不破坏**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

Expected: 所有现有测试 PASS（新参数有默认值，向后兼容）

- [ ] **Step 5: 提交**

```bash
git add indexer/embedding_generator.py indexer/incremental_indexer.py
git commit -m "feat(embedding): enhance _format_code_text to prioritize business_summary"
```

---

### Task 4: Enrichment 集成到索引流水线

**Files:**
- Modify: `indexer/incremental_indexer.py`
- Modify: `service.py`
- Modify: `config.py` (如果需要)

- [ ] **Step 1: 在 IncrementalIndexer 中添加 enrichment 支持**

在 `indexer/incremental_indexer.py` 的 `__init__` 中添加可选的 enricher 参数：

```python
def __init__(
    self,
    store: FalkorDBStore,
    graph_builder: CodeGraphBuilder,
    embedding_gen: EmbeddingGenerator,
    doc_indexer: DocumentIndexer | None = None,
    enricher: "CodeSummaryEnricher | None" = None,
) -> None:
    # ... existing init ...
    self._enricher = enricher
```

- [ ] **Step 2: 在 `_generate_and_store_embeddings` 之前添加 enrichment 步骤**

在 `_generate_and_store_embeddings` 方法开始处，如果 enricher 存在，先批量生成 business_summary：

```python
async def _generate_and_store_embeddings(self, nodes: list, progress_callback=None) -> int:
    embeddable = [n for n in nodes if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS, NodeLabel.DOCUMENT)]
    if not embeddable:
        return 0

    if self._enricher:
        code_nodes = [n for n in embeddable if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS)]
        if code_nodes:
            items_for_enrich = [
                {
                    "name": n.properties.get("name", ""),
                    "signature": n.properties.get("signature", ""),
                    "docstring": n.properties.get("docstring", ""),
                    "code_snippet": n.properties.get("code_snippet", ""),
                    "file": n.properties.get("file", ""),
                }
                for n in code_nodes
            ]
            summaries = await self._enricher.enrich_batch(items_for_enrich)
            for node, summary in zip(code_nodes, summaries):
                if summary:
                    node.properties["business_summary"] = summary
                    await self._store.update_node_property(
                        node.label, node.uid, "business_summary", summary
                    )

    # ... rest of existing embedding logic ...
```

- [ ] **Step 3: 在 `FalkorDBStore` 中添加 `update_node_property` 方法**

在 `store/falkordb_store.py` 中添加：

```python
async def update_node_property(
    self, label: NodeLabel, uid: str, prop: str, value: object
) -> None:
    loop = asyncio.get_running_loop()
    query = f"MATCH (n:{label} {{uid: $uid}}) SET n.{prop} = $value"
    await loop.run_in_executor(
        None, lambda: self._graph.query(query, {"uid": uid, "value": value})
    )
```

- [ ] **Step 4: 在 service.py 中注入 enricher**

在 `service.py` 的 `_init_components` 中：

```python
def _init_components(self, settings: Settings) -> None:
    self._embedding = EmbeddingGenerator.shared(config=settings.embedding)

    self._llm_provider = None
    self._enricher = None
    if settings.llm.enabled:
        from llm.provider import LLMProvider
        from indexer.enrichment import CodeSummaryEnricher
        self._llm_provider = LLMProvider(settings.llm)
        self._enricher = CodeSummaryEnricher(llm=self._llm_provider)

    # ... existing components ...

    self._incremental_indexer = IncrementalIndexer(
        store=self._store,
        graph_builder=self._graph_builder,
        embedding_gen=self._embedding,
        doc_indexer=self._doc_indexer,
        enricher=self._enricher,
    )
```

- [ ] **Step 5: 运行全部测试**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

Expected: 所有测试 PASS

- [ ] **Step 6: 提交**

```bash
git add indexer/incremental_indexer.py store/falkordb_store.py service.py
git commit -m "feat(indexer): integrate CodeSummaryEnricher into indexing pipeline"
```

---

### Task 5: 添加 httpx 和 tenacity 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加依赖**

在 `pyproject.toml` 的 `dependencies` 列表中添加：

```toml
"httpx>=0.27",
"tenacity>=8.2",
```

- [ ] **Step 2: 安装依赖**

```bash
cd knowledge-base-service && uv pip install httpx tenacity
```

- [ ] **Step 3: 运行全部测试确认**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

- [ ] **Step 4: 提交**

```bash
git add pyproject.toml
git commit -m "chore: add httpx and tenacity dependencies for LLM provider"
```

---

## Phase 2: 业务语义图谱层

### Task 6: Schema 扩展

**Files:**
- Modify: `store/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: 在 `NodeLabel` 中新增业务节点**

在 `store/schema.py` 中：

```python
class NodeLabel(StrEnum):
    FUNCTION = "Function"
    CLASS = "Class"
    MODULE = "Module"
    DOCUMENT = "Document"
    BUSINESS_FLOW = "BusinessFlow"
    BUSINESS_CONCEPT = "BusinessConcept"
```

- [ ] **Step 2: 在 `EdgeType` 中新增边类型**

```python
class EdgeType(StrEnum):
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPORTS = "IMPORTS"
    CONTAINS = "CONTAINS"
    USES_TYPE = "USES_TYPE"
    REFERENCES = "REFERENCES"
    IMPLEMENTS = "IMPLEMENTS"
    RELATES_TO = "RELATES_TO"
    PART_OF = "PART_OF"
    CONCEPT_IN = "CONCEPT_IN"
```

- [ ] **Step 3: 扩展 `VECTOR_INDEX_CONFIGS`**

```python
VECTOR_INDEX_CONFIGS = [
    {"label": NodeLabel.FUNCTION, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.CLASS, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.DOCUMENT, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.BUSINESS_FLOW, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.BUSINESS_CONCEPT, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.MODULE, "attribute": "embedding", "similarity": "cosine"},
]
```

- [ ] **Step 4: 运行 schema 测试**

```bash
cd knowledge-base-service && uv run pytest tests/test_schema.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add store/schema.py
git commit -m "feat(schema): add BusinessFlow, BusinessConcept nodes and IMPLEMENTS, RELATES_TO, PART_OF, CONCEPT_IN edges"
```

---

### Task 7: 业务流程推断器

**Files:**
- Create: `indexer/business_flow_inferencer.py`
- Test: `tests/test_business_flow_inferencer.py`

- [ ] **Step 1: 编写测试**

创建 `tests/test_business_flow_inferencer.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
import json


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider

    llm = MagicMock(spec=LLMProvider)
    llm.complete_json = AsyncMock(return_value={
        "flow_name": "用户下单",
        "description": "处理用户创建订单的完整流程",
        "category": "交易",
        "steps": [
            {"function": "createOrder", "role": "entry_point", "order": 1},
            {"function": "validateStock", "role": "validator", "order": 2},
            {"function": "processPayment", "role": "processor", "order": 3},
        ],
        "sub_flows": [],
    })
    return llm


@pytest.fixture
def mock_store():
    from store.falkordb_store import FalkorDBStore

    store = MagicMock(spec=FalkorDBStore)
    return store


class TestBusinessFlowInferencer:
    @pytest.mark.asyncio
    async def test_infer_from_call_chain(self, mock_llm, mock_store):
        from indexer.business_flow_inferencer import BusinessFlowInferencer

        inferencer = BusinessFlowInferencer(llm=mock_llm, store=mock_store)
        chain = [
            {"name": "createOrder", "business_summary": "创建订单入口", "file": "order.py"},
            {"name": "validateStock", "business_summary": "验证库存", "file": "stock.py"},
            {"name": "processPayment", "business_summary": "处理支付", "file": "pay.py"},
        ]
        result = await inferencer.infer_from_chain(chain)
        assert result["flow_name"] == "用户下单"
        assert len(result["steps"]) == 3

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_llm, mock_store):
        from indexer.business_flow_inferencer import BusinessFlowInferencer

        mock_llm.complete_json = AsyncMock(side_effect=Exception("LLM error"))
        inferencer = BusinessFlowInferencer(llm=mock_llm, store=mock_store)
        chain = [{"name": "func", "business_summary": "test", "file": "a.py"}]
        result = await inferencer.infer_from_chain(chain)
        assert result is None
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd knowledge-base-service && uv run pytest tests/test_business_flow_inferencer.py -v
```

- [ ] **Step 3: 实现 BusinessFlowInferencer**

创建 `indexer/business_flow_inferencer.py`：

```python
"""Business flow inference — identifies business flows from call chains using LLM."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from llm.provider import LLMProvider
    from store.falkordb_store import FalkorDBStore

logger = logging.getLogger(__name__)

_FLOW_INFERENCE_PROMPT = """以下是一条代码调用链。请分析它实现的业务流程。

调用链:
{chain_text}

请输出 JSON:
{{
  "flow_name": "业务流程名称",
  "description": "流程描述",
  "category": "分类（如交易、用户、内容、系统）",
  "steps": [
    {{"function": "函数名", "role": "entry_point|processor|validator|notifier|persistence|external_call", "order": 1}}
  ],
  "sub_flows": [
    {{"name": "子流程名", "description": "描述", "steps": [...]}}
  ]
}}"""


class BusinessFlowInferencer:
    """Infers business flows from code call chains."""

    def __init__(self, llm: LLMProvider, store: FalkorDBStore) -> None:
        self._llm = llm
        self._store = store

    async def infer_from_chain(self, chain: list[dict[str, str]]) -> dict[str, Any] | None:
        """Infer a business flow from a call chain.

        Args:
            chain: List of dicts with 'name', 'business_summary', 'file' keys.

        Returns:
            Flow dict with flow_name, description, category, steps, sub_flows.
            None if inference fails.
        """
        chain_text = "\n".join(
            f"  {'→ ' if i > 0 else ''}{item['name']} ({item.get('business_summary', 'N/A')}) [{item.get('file', '')}]"
            for i, item in enumerate(chain)
        )
        prompt = _FLOW_INFERENCE_PROMPT.format(chain_text=chain_text)
        try:
            result = await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
            )
            return result
        except Exception:
            logger.warning("Failed to infer business flow from chain starting with %s", chain[0].get("name"), exc_info=True)
            return None

    async def find_entry_points(self) -> list[dict[str, Any]]:
        """Find entry point functions in the graph.

        Entry points are:
        1. Strong: Functions with HTTP/RPC/Kafka annotations (@MoaProvider, @RequestMapping, @KafkaListener)
        2. Weak: Functions with no CALLS inbound edges but having CALLS outbound edges
        """
        import asyncio

        loop = asyncio.get_running_loop()

        strong_query = """
        MATCH (f:Function)
        WHERE f.signature CONTAINS '@RequestMapping'
           OR f.signature CONTAINS '@GetMapping'
           OR f.signature CONTAINS '@PostMapping'
           OR f.signature CONTAINS '@MoaProvider'
           OR f.signature CONTAINS '@KafkaListener'
           OR f.signature CONTAINS '@app.route'
           OR f.signature CONTAINS '@Scheduled'
        RETURN f
        """

        weak_query = """
        MATCH (f:Function)-[:CALLS]->()
        WHERE NOT ()-[:CALLS]->(f)
        RETURN f
        """

        strong_result = await loop.run_in_executor(
            None, lambda: self._store._graph.query(strong_query)
        )
        weak_result = await loop.run_in_executor(
            None, lambda: self._store._graph.query(weak_query)
        )

        entries = []
        seen = set()
        for row in (strong_result.result_set or []):
            node = row[0]
            uid = node.properties.get("uid", node.properties.get("name"))
            if uid not in seen:
                seen.add(uid)
                entries.append({**node.properties, "_entry_type": "strong"})

        for row in (weak_result.result_set or []):
            node = row[0]
            uid = node.properties.get("uid", node.properties.get("name"))
            if uid not in seen:
                seen.add(uid)
                entries.append({**node.properties, "_entry_type": "weak"})

        return entries
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd knowledge-base-service && uv run pytest tests/test_business_flow_inferencer.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add indexer/business_flow_inferencer.py tests/test_business_flow_inferencer.py
git commit -m "feat(inferencer): add BusinessFlowInferencer for call chain analysis"
```

---

### Task 8: 文档概念提取器

**Files:**
- Create: `indexer/concept_extractor.py`
- Test: `tests/test_concept_extractor.py`

- [ ] **Step 1: 编写测试**

创建 `tests/test_concept_extractor.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider

    llm = MagicMock(spec=LLMProvider)
    llm.complete_json = AsyncMock(return_value={
        "concepts": [
            {"name": "私信", "description": "用户间的即时消息", "aliases": ["IM消息", "direct_message"], "category": "社交"},
        ],
        "flows": [
            {"name": "发送私信", "description": "用户发送私信给另一个用户", "category": "社交"},
        ],
    })
    return llm


class TestConceptExtractor:
    @pytest.mark.asyncio
    async def test_extract_from_document(self, mock_llm):
        from indexer.concept_extractor import ConceptExtractor

        extractor = ConceptExtractor(llm=mock_llm)
        result = await extractor.extract("# 私信系统\n用户可以通过私信功能发送即时消息...")
        assert len(result["concepts"]) == 1
        assert result["concepts"][0]["name"] == "私信"
        assert "IM消息" in result["concepts"][0]["aliases"]

    @pytest.mark.asyncio
    async def test_handles_empty_document(self, mock_llm):
        from indexer.concept_extractor import ConceptExtractor

        mock_llm.complete_json = AsyncMock(return_value={"concepts": [], "flows": []})
        extractor = ConceptExtractor(llm=mock_llm)
        result = await extractor.extract("")
        assert len(result["concepts"]) == 0
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd knowledge-base-service && uv run pytest tests/test_concept_extractor.py -v
```

- [ ] **Step 3: 实现 ConceptExtractor**

创建 `indexer/concept_extractor.py`：

```python
"""Document concept extraction — extracts business concepts from documents using LLM."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """以下是项目文档。请提取其中的业务概念和业务流程。

文档内容:
{content}

请输出 JSON:
{{
  "concepts": [
    {{"name": "概念名称", "description": "概念描述", "aliases": ["别名1", "别名2"], "category": "分类"}}
  ],
  "flows": [
    {{"name": "流程名称", "description": "流程描述", "category": "分类"}}
  ]
}}

如果文档中没有明确的业务概念或流程，返回空列表。"""


class ConceptExtractor:
    """Extracts business concepts and flow descriptions from documents."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def extract(self, content: str) -> dict[str, list[dict[str, Any]]]:
        """Extract concepts and flows from document content.

        Returns dict with 'concepts' and 'flows' lists.
        """
        if not content or not content.strip():
            return {"concepts": [], "flows": []}

        prompt = _EXTRACT_PROMPT.format(content=content[:3000])
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
            )
        except Exception:
            logger.warning("Failed to extract concepts from document", exc_info=True)
            return {"concepts": [], "flows": []}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd knowledge-base-service && uv run pytest tests/test_concept_extractor.py -v
```

- [ ] **Step 5: 提交**

```bash
git add indexer/concept_extractor.py tests/test_concept_extractor.py
git commit -m "feat(extractor): add ConceptExtractor for document business concept extraction"
```

---

### Task 9: 业务流程图查询

**Files:**
- Modify: `query/graph_query.py`

- [ ] **Step 1: 新增业务流程查询方法到 GraphQueryService**

在 `query/graph_query.py` 的 `GraphQueryService` 类中添加：

```python
async def find_business_flow(self, name: str, k: int = 10) -> QueryResult:
    """Find a business flow and its implementing functions/classes."""
    query = (
        "MATCH (bf:BusinessFlow)-[r:IMPLEMENTS]->(n) "
        "WHERE bf.name CONTAINS $name "
        "RETURN bf, r, n ORDER BY r.step_order LIMIT $k"
    )
    return await self._execute("find_business_flow", query, {"name": name, "k": k})

async def find_flows_for_function(self, function_name: str) -> QueryResult:
    """Reverse lookup: find business flows that a function belongs to."""
    params = _make_params(function_name)
    where = _where_name("f", params)
    query = (
        f"MATCH (bf:BusinessFlow)-[:IMPLEMENTS]->(f:Function) "
        f"WHERE {where} RETURN bf, f"
    )
    return await self._execute("find_flows_for_function", query, params)

async def find_related_concepts(self, entity_name: str) -> QueryResult:
    """Find business concepts related to a given entity."""
    query = (
        "MATCH (bc:BusinessConcept)-[r:RELATES_TO]->(n) "
        "WHERE n.name = $name "
        "RETURN bc, r, n ORDER BY r.relevance_score DESC"
    )
    return await self._execute("find_related_concepts", query, {"name": entity_name})

async def explore_business_domain(self, category: str) -> QueryResult:
    """Explore all flows and concepts in a business domain."""
    query = (
        "MATCH (bf:BusinessFlow) WHERE bf.category = $category "
        "OPTIONAL MATCH (bf)-[:IMPLEMENTS]->(f) "
        "RETURN bf, collect(f) AS functions"
    )
    return await self._execute("explore_business_domain", query, {"category": category})

async def find_flow_dependencies(self, flow_name: str) -> QueryResult:
    """Find parent/child flow relationships."""
    query = (
        "MATCH path=(bf:BusinessFlow)-[:PART_OF*0..3]->(parent:BusinessFlow) "
        "WHERE bf.name CONTAINS $name "
        "RETURN bf, parent, length(path) AS depth ORDER BY depth"
    )
    return await self._execute("find_flow_dependencies", query, {"name": flow_name})
```

- [ ] **Step 2: 添加通用执行方法（如果不存在）**

检查是否已有 `_execute` 方法，如果没有则添加：

```python
async def _execute(self, op: str, query: str, params: dict) -> QueryResult:
    import asyncio

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: self._store._graph.query(query, params)
    )
    return QueryResult(
        data=[list(row) for row in (result.result_set or [])],
        query=query,
        params=params,
    )
```

- [ ] **Step 3: 运行测试**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

- [ ] **Step 4: 提交**

```bash
git add query/graph_query.py
git commit -m "feat(graph): add business flow query methods to GraphQueryService"
```

---

## Phase 3: 搜索引擎增强

### Task 10: Cross-Encoder Reranking 模块

**Files:**
- Create: `query/reranker.py`
- Modify: `config.py` (添加 RerankConfig)
- Test: `tests/test_reranker.py`

- [ ] **Step 1: 添加 RerankConfig**

在 `config.py` 中：

```python
class RerankConfig(BaseModel):
    """Configuration for cross-encoder reranking."""
    enabled: bool = False
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"
    batch_size: int = 32
    top_n: int = 30
```

在 `Settings` 中添加：

```python
rerank: RerankConfig = RerankConfig()
```

- [ ] **Step 2: 编写 Reranker 测试**

创建 `tests/test_reranker.py`：

```python
import pytest
from unittest.mock import MagicMock, patch
from config import RerankConfig


@pytest.fixture
def rerank_config():
    return RerankConfig(enabled=True, model_name="BAAI/bge-reranker-v2-m3")


class TestReranker:
    def test_rerank_sorts_by_score(self, rerank_config):
        from query.reranker import Reranker

        reranker = Reranker(rerank_config)
        with patch.object(reranker, "_compute_scores", return_value=[0.1, 0.9, 0.5]):
            candidates = [
                {"name": "a", "text": "low relevance"},
                {"name": "b", "text": "high relevance"},
                {"name": "c", "text": "medium relevance"},
            ]
            result = reranker.rerank("test query", candidates, top_k=2)
        assert result[0]["name"] == "b"
        assert result[1]["name"] == "c"
        assert len(result) == 2

    def test_rerank_disabled_returns_original(self):
        from query.reranker import Reranker

        config = RerankConfig(enabled=False)
        reranker = Reranker(config)
        candidates = [{"name": "a"}, {"name": "b"}]
        result = reranker.rerank("query", candidates, top_k=2)
        assert result == candidates
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd knowledge-base-service && uv run pytest tests/test_reranker.py -v
```

- [ ] **Step 4: 实现 Reranker**

创建 `query/reranker.py`：

```python
"""Cross-encoder reranking module for search result refinement."""

from __future__ import annotations

import logging
from typing import Any

from config import RerankConfig

logger = logging.getLogger(__name__)


class Reranker:
    """Cross-encoder reranker using a lightweight model (not LLM)."""

    def __init__(self, config: RerankConfig) -> None:
        self._config = config
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None or not self._config.enabled:
            return
        try:
            from sentence_transformers import CrossEncoder

            device = self._config.device
            if device == "auto":
                import torch
                device = "mps" if torch.backends.mps.is_available() else (
                    "cuda" if torch.cuda.is_available() else "cpu"
                )
            self._model = CrossEncoder(self._config.model_name, device=device)
            logger.info("Loaded reranker model: %s on %s", self._config.model_name, device)
        except Exception:
            logger.warning("Failed to load reranker model, disabling reranking", exc_info=True)
            self._config.enabled = False

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not self._config.enabled or not candidates:
            return candidates[:top_k]

        self._ensure_model()
        if self._model is None:
            return candidates[:top_k]

        texts = [self._candidate_text(c) for c in candidates]
        scores = self._compute_scores(query, texts)

        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored[:top_k]]

    def _compute_scores(self, query: str, texts: list[str]) -> list[float]:
        pairs = [(query, t) for t in texts]
        return self._model.predict(pairs, batch_size=self._config.batch_size).tolist()

    @staticmethod
    def _candidate_text(candidate: dict[str, Any]) -> str:
        parts = []
        if candidate.get("business_summary"):
            parts.append(candidate["business_summary"])
        if candidate.get("name"):
            parts.append(candidate["name"])
        if candidate.get("signature"):
            parts.append(candidate["signature"])
        if candidate.get("docstring"):
            parts.append(candidate["docstring"][:200])
        if candidate.get("description"):
            parts.append(candidate["description"][:200])
        return " ".join(parts) if parts else candidate.get("name", "")
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd knowledge-base-service && uv run pytest tests/test_reranker.py -v
```

- [ ] **Step 6: 提交**

```bash
git add query/reranker.py config.py tests/test_reranker.py
git commit -m "feat(reranker): add cross-encoder reranking module with bge-reranker-v2-m3"
```

---

### Task 11: 扩展语义搜索到 6 类

**Files:**
- Modify: `query/semantic_query.py`

- [ ] **Step 1: 扩展 search_all 方法**

在 `query/semantic_query.py` 中修改 `search_all`：

```python
async def search_all(self, query_text: str, k: int = 10) -> SemanticResult:
    """Search across all 6 vector-indexed node types."""
    results = await asyncio.gather(
        self._search_by_label(query_text, NodeLabel.FUNCTION, k),
        self._search_by_label(query_text, NodeLabel.CLASS, k),
        self._search_by_label(query_text, NodeLabel.DOCUMENT, k),
        self._search_by_label(query_text, NodeLabel.BUSINESS_FLOW, k),
        self._search_by_label(query_text, NodeLabel.BUSINESS_CONCEPT, k),
        self._search_by_label(query_text, NodeLabel.MODULE, k),
    )
    all_matches = []
    for sr in results:
        all_matches.extend(sr.matches)
    all_matches.sort(key=lambda m: m.get("score", 0), reverse=True)
    return SemanticResult(
        matches=all_matches[:k],
        query_text=query_text,
        total=sum(sr.total for sr in results),
    )
```

添加新的单类型搜索方法：

```python
async def search_business_flows(self, query_text: str, k: int = 10) -> SemanticResult:
    return await self._search_by_label(query_text, NodeLabel.BUSINESS_FLOW, k)

async def search_business_concepts(self, query_text: str, k: int = 10) -> SemanticResult:
    return await self._search_by_label(query_text, NodeLabel.BUSINESS_CONCEPT, k)

async def search_modules(self, query_text: str, k: int = 10) -> SemanticResult:
    return await self._search_by_label(query_text, NodeLabel.MODULE, k)
```

- [ ] **Step 2: 需要添加 asyncio import（如果不存在）**

确认 `import asyncio` 在文件顶部。

- [ ] **Step 3: 运行测试**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

- [ ] **Step 4: 提交**

```bash
git add query/semantic_query.py
git commit -m "feat(search): extend semantic search to 6 vector-indexed types"
```

---

### Task 12: 增强 Hybrid Search

**Files:**
- Modify: `query/hybrid_query.py`
- Modify: `service.py`

- [ ] **Step 1: 在 HybridQueryService 中注入 Reranker**

修改 `query/hybrid_query.py` 的 `__init__`：

```python
def __init__(
    self,
    store: FalkorDBStore,
    semantic_svc: SemanticQueryService,
    graph_svc: GraphQueryService,
    reranker: "Reranker | None" = None,
) -> None:
    self._store = store
    self._semantic = semantic_svc
    self._graph = graph_svc
    self._reranker = reranker
```

- [ ] **Step 2: 在 search_with_context 中添加 reranking 步骤**

在 `search_with_context` 方法中，fusion 之后、graph expansion 之前插入 reranking：

```python
merged = self._fuse_results(keyword_hits, semantic_result.matches, k * 3)

if self._reranker:
    merged = self._reranker.rerank(query_text, merged, top_k=k)
else:
    merged = merged[:k]

graph_context = await self._expand_graph(merged, expand_depth, include_callers, include_callees)
```

- [ ] **Step 3: 在图扩展中添加业务流程上下文**

在 `_expand_graph` 方法末尾添加业务流程关联查询：

```python
for match in matches:
    name = match.get("name", "")
    if not name:
        continue
    try:
        flows_result = await self._graph.find_flows_for_function(name)
        if flows_result.data:
            for row in flows_result.data:
                context.append({
                    "type": "business_flow",
                    "flow": row[0].properties if hasattr(row[0], "properties") else row[0],
                    "related_function": name,
                })
    except Exception:
        pass
```

- [ ] **Step 4: 在 service.py 中注入 reranker**

```python
from query.reranker import Reranker

# in _init_components:
self._reranker = Reranker(settings.rerank) if settings.rerank.enabled else None

self._hybrid_query = HybridQueryService(
    store=self._store,
    semantic_svc=self._semantic_query,
    graph_svc=self._graph_query,
    reranker=self._reranker,
)
```

- [ ] **Step 5: 运行测试**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

- [ ] **Step 6: 提交**

```bash
git add query/hybrid_query.py service.py
git commit -m "feat(hybrid): integrate cross-encoder reranking and business flow context into hybrid search"
```

---

### Task 13: 扩展 MCP 工具

**Files:**
- Modify: `api/mcp_server.py`

- [ ] **Step 1: 在 MCP_TOOLS_MANIFEST 中添加 rag_business_search**

在 `api/mcp_server.py` 的 `MCP_TOOLS_MANIFEST` 列表中添加：

```python
{
    "name": "rag_business_search",
    "description": "搜索业务流程和业务概念，支持自然语言查询。可以搜索业务流程（如'用户下单'）、业务概念（如'私信'），并返回关联的代码位置。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "业务语义查询（自然语言）",
            },
            "search_type": {
                "type": "string",
                "enum": ["flow", "concept", "all"],
                "default": "all",
                "description": "搜索类型：flow=业务流程, concept=业务概念, all=全部",
            },
            "k": {
                "type": "integer",
                "default": 5,
                "description": "返回结果数量",
            },
            "include_code": {
                "type": "boolean",
                "default": True,
                "description": "是否包含关联的代码位置",
            },
        },
        "required": ["query"],
    },
},
```

- [ ] **Step 2: 在 rag_graph 工具中扩展 query_type**

在 `rag_graph` 的 `inputSchema` 中，给 `query_type` 的 enum 添加新选项：

```python
"enum": [
    "call_chain", "inheritance_tree", "class_methods",
    "module_dependencies", "reverse_dependencies",
    "find_entity", "file_entities", "graph_stats", "raw_cypher",
    "business_flow", "flows_for_function", "related_concepts",
    "explore_domain", "flow_dependencies",
],
```

- [ ] **Step 3: 在 KnowledgeBaseMCPHandler 中实现处理方法**

添加 `handle_rag_business_search` 方法和扩展 `handle_rag_graph`：

```python
async def handle_rag_business_search(self, arguments: dict) -> dict:
    query = arguments["query"]
    search_type = arguments.get("search_type", "all")
    k = arguments.get("k", 5)
    include_code = arguments.get("include_code", True)

    results = {}
    if search_type in ("flow", "all"):
        flow_result = await self._hybrid_svc._semantic.search_business_flows(query, k)
        results["flows"] = flow_result.matches
    if search_type in ("concept", "all"):
        concept_result = await self._hybrid_svc._semantic.search_business_concepts(query, k)
        results["concepts"] = concept_result.matches

    if include_code:
        for flow in results.get("flows", []):
            name = flow.get("name", "")
            if name:
                code_result = await self._graph_svc.find_business_flow(name, k=5)
                flow["code_locations"] = code_result.data

    return {"status": "success", "results": results}
```

在 `handle_tool_call` dispatch 中添加：

```python
if tool_name == "rag_business_search":
    return await self.handle_rag_business_search(arguments)
```

- [ ] **Step 4: 扩展 handle_rag_graph 支持新的 query_type**

在 `handle_rag_graph` 方法的 dispatch 逻辑中添加：

```python
elif query_type == "business_flow":
    result = await self._graph_svc.find_business_flow(name, k=depth or 10)
elif query_type == "flows_for_function":
    result = await self._graph_svc.find_flows_for_function(name)
elif query_type == "related_concepts":
    result = await self._graph_svc.find_related_concepts(name)
elif query_type == "explore_domain":
    result = await self._graph_svc.explore_business_domain(name)
elif query_type == "flow_dependencies":
    result = await self._graph_svc.find_flow_dependencies(name)
```

- [ ] **Step 5: 运行测试**

```bash
cd knowledge-base-service && uv run pytest tests/test_mcp_server.py -v
```

- [ ] **Step 6: 提交**

```bash
git add api/mcp_server.py
git commit -m "feat(mcp): add rag_business_search tool and extend rag_graph with business flow queries"
```

---

## Phase 4: Dashboard LLM 增强搜索

### Task 14: Deep Search Engine

**Files:**
- Create: `query/deep_search.py`
- Test: `tests/test_deep_search.py`

- [ ] **Step 1: 编写测试**

创建 `tests/test_deep_search.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider

    llm = MagicMock(spec=LLMProvider)
    llm.complete_json = AsyncMock(side_effect=[
        {
            "intent": "impact_analysis",
            "sub_queries": [
                {"type": "rag_query", "query": "支付回调处理"},
                {"type": "rag_graph", "query_type": "business_flow", "name": "支付"},
            ],
        },
        {
            "sufficient": True,
            "analysis": "支付回调失败会影响订单状态更新和退款流程。",
            "business_flows": [{"name": "订单支付", "impact": "订单状态无法更新为已支付"}],
            "code_locations": [{"file": "payment/callback.py", "function": "handle_callback"}],
        },
    ])
    return llm


@pytest.fixture
def mock_hybrid():
    from query.hybrid_query import HybridQueryService, HybridResult

    svc = MagicMock(spec=HybridQueryService)
    svc.search_with_context = AsyncMock(return_value=HybridResult(
        semantic_matches=[{"name": "handle_callback", "file": "payment/callback.py"}],
        graph_context=[],
        query_text="支付回调",
        total=1,
    ))
    return svc


@pytest.fixture
def mock_graph():
    from query.graph_query import GraphQueryService, QueryResult

    svc = MagicMock(spec=GraphQueryService)
    svc.find_business_flow = AsyncMock(return_value=QueryResult(data=[], query="", params={}))
    return svc


class TestDeepSearchEngine:
    @pytest.mark.asyncio
    async def test_deep_search_returns_analysis(self, mock_llm, mock_hybrid, mock_graph):
        from query.deep_search import DeepSearchEngine

        engine = DeepSearchEngine(llm=mock_llm, hybrid_svc=mock_hybrid, graph_svc=mock_graph)
        result = await engine.search("支付回调失败可能影响哪些业务？")
        assert "analysis" in result
        assert "search_trace" in result
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd knowledge-base-service && uv run pytest tests/test_deep_search.py -v
```

- [ ] **Step 3: 实现 DeepSearchEngine**

创建 `query/deep_search.py`：

```python
"""Dashboard LLM-enhanced deep search engine."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from llm.provider import LLMProvider
    from query.hybrid_query import HybridQueryService
    from query.graph_query import GraphQueryService

logger = logging.getLogger(__name__)

_PLAN_PROMPT = """你是一个代码知识库搜索助手。用户的查询是：

"{query}"

请分析查询意图并生成搜索计划。输出 JSON：
{{
  "intent": "查询意图类型（search/impact_analysis/flow_query/concept_query）",
  "sub_queries": [
    {{"type": "rag_query|rag_graph", "query": "搜索词", "query_type": "可选的图查询类型", "name": "可选的实体名"}}
  ]
}}"""

_SYNTHESIZE_PROMPT = """你是一个代码知识库搜索助手。基于以下搜索结果，回答用户的查询。

用户查询: "{query}"

搜索结果:
{results_text}

请输出 JSON:
{{
  "sufficient": true/false,
  "analysis": "综合分析（Markdown 格式）",
  "business_flows": [{{"name": "流程名", "impact": "影响描述"}}],
  "code_locations": [{{"file": "文件路径", "function": "函数名", "relevance": "相关性说明"}}],
  "follow_up_queries": []
}}

如果 sufficient 为 false，在 follow_up_queries 中提供追加查询。"""


class DeepSearchEngine:
    """LLM-enhanced search engine for Dashboard users."""

    def __init__(
        self,
        llm: LLMProvider,
        hybrid_svc: HybridQueryService,
        graph_svc: GraphQueryService,
    ) -> None:
        self._llm = llm
        self._hybrid = hybrid_svc
        self._graph = graph_svc

    async def search(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        include_code: bool = True,
        model: str | None = None,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []

        plan = await self._plan_search(query, model=model)
        trace.append({"step": "plan", "result": plan})

        all_results: list[dict[str, Any]] = []
        for iteration in range(max_iterations):
            sub_queries = plan.get("sub_queries", []) if iteration == 0 else (
                synthesis.get("follow_up_queries", []) if "synthesis" in dir() else []
            )
            if not sub_queries:
                break

            results = await self._execute_sub_queries(sub_queries)
            all_results.extend(results)
            trace.append({"step": f"search_iter_{iteration}", "queries": sub_queries, "result_count": len(results)})

            synthesis = await self._synthesize(query, all_results, model=model)
            trace.append({"step": f"synthesize_iter_{iteration}", "sufficient": synthesis.get("sufficient")})

            if synthesis.get("sufficient", True):
                break

        return {
            "analysis": synthesis.get("analysis", "") if "synthesis" in dir() else "",
            "business_flows": synthesis.get("business_flows", []) if "synthesis" in dir() else [],
            "code_locations": synthesis.get("code_locations", []) if "synthesis" in dir() else [],
            "search_trace": trace,
        }

    async def _plan_search(self, query: str, *, model: str | None = None) -> dict[str, Any]:
        prompt = _PLAN_PROMPT.format(query=query)
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
                model=model,
            )
        except Exception:
            logger.warning("Failed to plan search", exc_info=True)
            return {"intent": "search", "sub_queries": [{"type": "rag_query", "query": query}]}

    async def _execute_sub_queries(self, sub_queries: list[dict]) -> list[dict[str, Any]]:
        import asyncio

        results = []
        tasks = [self._execute_single(sq) for sq in sub_queries]
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning("Sub-query failed: %s", result)
            elif result:
                results.append(result)
        return results

    async def _execute_single(self, sub_query: dict) -> dict[str, Any] | None:
        q_type = sub_query.get("type", "rag_query")
        if q_type == "rag_query":
            result = await self._hybrid.search_with_context(sub_query.get("query", ""), k=5)
            return {"type": "hybrid", "matches": result.semantic_matches, "context": result.graph_context}
        elif q_type == "rag_graph":
            query_type = sub_query.get("query_type", "business_flow")
            name = sub_query.get("name", "")
            if query_type == "business_flow" and name:
                result = await self._graph.find_business_flow(name)
                return {"type": "graph", "data": result.data}
        return None

    async def _synthesize(self, query: str, results: list[dict], *, model: str | None = None) -> dict[str, Any]:
        import json

        results_text = json.dumps(results, ensure_ascii=False, default=str)[:4000]
        prompt = _SYNTHESIZE_PROMPT.format(query=query, results_text=results_text)
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
                model=model,
            )
        except Exception:
            logger.warning("Failed to synthesize results", exc_info=True)
            return {"sufficient": True, "analysis": "搜索结果汇总失败", "business_flows": [], "code_locations": []}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd knowledge-base-service && uv run pytest tests/test_deep_search.py -v
```

- [ ] **Step 5: 提交**

```bash
git add query/deep_search.py tests/test_deep_search.py
git commit -m "feat(deep-search): add LLM-enhanced DeepSearchEngine for Dashboard users"
```

---

### Task 15: 添加 Deep Search 路由

**Files:**
- Modify: `main.py`
- Modify: `service.py`

- [ ] **Step 1: 在 service.py 中创建 DeepSearchEngine**

在 `_init_components` 中添加：

```python
self._deep_search = None
if settings.llm.enabled:
    from query.deep_search import DeepSearchEngine
    self._deep_search = DeepSearchEngine(
        llm=self._llm_provider,
        hybrid_svc=self._hybrid_query,
        graph_svc=self._graph_query,
    )
```

添加 property：

```python
@property
def deep_search(self) -> "DeepSearchEngine | None":
    return self._deep_search
```

- [ ] **Step 2: 在 main.py 中添加 deep-search 路由**

在 `viewer_router` 中添加：

```python
class DeepSearchRequest(BaseModel):
    query: str
    max_iterations: int = 3
    include_code: bool = True

@viewer_router.post("/api/v1/deep-search")
async def deep_search(request: DeepSearchRequest, service=Depends(_get_service)):
    if not service.deep_search:
        raise HTTPException(status_code=501, detail="LLM not configured, deep search unavailable")
    result = await service.deep_search.search(
        request.query,
        max_iterations=request.max_iterations,
        include_code=request.include_code,
        model=service._settings.llm.deep_search_model,
    )
    return result
```

- [ ] **Step 3: 在 main.py 中添加 business search 路由**

```python
class BusinessSearchRequest(BaseModel):
    query: str
    search_type: str = "all"
    k: int = 5
    include_code: bool = True

@viewer_router.post("/api/v1/business/search")
async def business_search(request: BusinessSearchRequest, service=Depends(_get_service)):
    results = {}
    if request.search_type in ("flow", "all"):
        flow_result = await service.semantic_query.search_business_flows(request.query, request.k)
        results["flows"] = flow_result.matches
    if request.search_type in ("concept", "all"):
        concept_result = await service.semantic_query.search_business_concepts(request.query, request.k)
        results["concepts"] = concept_result.matches
    return {"status": "success", "results": results}
```

- [ ] **Step 4: 运行测试**

```bash
cd knowledge-base-service && uv run pytest tests/ -v
```

- [ ] **Step 5: 提交**

```bash
git add main.py service.py
git commit -m "feat(api): add /deep-search and /business/search HTTP routes"
```

---

### Task 16: 更新 acp-gateway rag_router

**Files:**
- Modify: `../acp-gateway/src/api/rag_router.py`
- Modify: `../acp-gateway/src/task/rag_prompt_injector.py`

- [ ] **Step 1: 在 rag_router.py 中添加 deep-search 代理**

在 `rag_router.py` 中添加：

```python
@router.post("/deep-search")
async def deep_search(request: Request, ...):
    """Proxy deep-search to knowledge-base-service (Dashboard use only)."""
    return await _proxy_to_kb("deep-search", request, ...)
```

- [ ] **Step 2: 在 rag_router.py 中添加 business search 代理**

```python
@router.post("/business/search")
async def business_search(request: Request, ...):
    """Proxy business search to knowledge-base-service."""
    return await _proxy_to_kb("business/search", request, ...)
```

- [ ] **Step 3: 更新 RagPromptInjector 工具说明**

在 `rag_prompt_injector.py` 的提示文本中添加 `rag_business_search` 工具说明：

```
### rag_business_search — 业务语义搜索
搜索业务流程和业务概念，支持自然语言查询。
参数: query (必选), search_type (flow/concept/all), k, include_code
示例: rag_business_search --query "用户下单" --search_type flow
```

- [ ] **Step 4: 提交**

```bash
cd ../acp-gateway
git add src/api/rag_router.py src/task/rag_prompt_injector.py
git commit -m "feat(rag): add deep-search and business-search proxy routes, update prompt injector"
```

---

## 完成检查

- [ ] **所有 Phase 测试通过**: `cd knowledge-base-service && uv run pytest tests/ -v`
- [ ] **lint 检查通过**: `cd knowledge-base-service && uv run ruff check .`
- [ ] **设计 spec 与实现对齐**: 对照 `docs/superpowers/specs/2026-04-10-semantic-search-enhancement-design.md` 检查
