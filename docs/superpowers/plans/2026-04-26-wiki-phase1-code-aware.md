# Wiki 代码感知层（Phase 1）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LLM 在生成 wiki 时能看到实际代码内容，通过 SourceCodeReader 读取 Chunk 代码文本，通过 ImportanceScorer 对实体重要度评分分层，并将代码片段嵌入到 LLM prompt 中，大幅提升 wiki 生成质量。

**Architecture:** 新增 SourceCodeReader 组件从 Chunk 节点读取代码（降级路径：Chunk.text → 文件读取 → signature）。新增 ImportanceScorer 通过单次 Cypher 查询计算实体度数，按百分位分为 core/standard/skeleton 三层。扩展 PageData 携带 code_snippets 和 importance_tier。增强 _entity_digest 在 LLM prompt 中嵌入关键代码。所有新功能通过 `WIKI__CODE_BUDGET_ENABLED` 开关控制，关闭时保持现有行为。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB (Cypher), dataclasses, pytest

**Spec:** [2026-04-24-wiki-enhancement-design.md](../specs/2026-04-24-wiki-enhancement-design.md) Phase 1 章节

**Code Review 要求:** 每个 Task 完成后必须进行 code review，确认代码质量和测试覆盖后再进入下一个 Task。

**计划范围:** 本文档仅覆盖 Phase 1（代码感知层）。Phase 2（RAG 检索层）和 Phase 3（百科分层生成）的实施计划将在 Phase 1 完成后单独编写。

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `config.py` | WikiConfig 新增代码预算和重要度分层配置 |
| Modify | `wiki/models.py` | 新增 CodeSnippet、ImportanceTier；扩展 PageData |
| Modify | `store/wiki_store.py` | 新增 Chunk 查询和节点度数统计 Cypher |
| Create | `wiki/source_code_reader.py` | SourceCodeReader 代码读取组件 |
| Create | `wiki/importance_scorer.py` | ImportanceScorer 实体重要度评分 |
| Modify | `wiki/data_collector.py` | 集成 SourceCodeReader，扩展 PageData 填充 |
| Modify | `wiki/composer.py` | 增强 _entity_digest 嵌入代码片段 |
| Modify | `wiki/service.py` | 集成 ImportanceScorer，传递 importance_tier |
| Create | `tests/test_config_phase1.py` | 配置测试 |
| Create | `tests/wiki/test_source_code_reader.py` | SourceCodeReader 单元测试 |
| Create | `tests/wiki/test_importance_scorer.py` | ImportanceScorer 单元测试 |
| Create | `tests/store/test_wiki_store_chunk.py` | Chunk 查询和度数统计测试 |

---

### Task 1: 扩展 WikiConfig 配置（Phase 1 字段）

**Files:**
- Modify: `config.py`

- [x] **Step 1: Write the failing test**

```python
# tests/test_config_phase1.py
from config import Settings

def test_wiki_code_budget_config_defaults():
    s = Settings(falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.code_budget_enabled is True
    assert s.wiki.core_code_budget == 20000
    assert s.wiki.standard_code_budget == 8000
    assert s.wiki.skeleton_code_budget == 1000

def test_wiki_importance_config_defaults():
    s = Settings(falkordb={"host": "localhost", "port": 6379})
    assert s.wiki.importance_core_percentile == 80
    assert s.wiki.importance_standard_percentile == 30
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/test_config_phase1.py -v`
Expected: FAIL with `AttributeError`

- [x] **Step 3: Add Phase 1 config fields to WikiConfig**

在 `config.py` 的 `WikiConfig` 类中，在 Phase 0 字段之后添加：

```python
    # Phase 1: Code-aware generation
    code_budget_enabled: bool = True
    core_code_budget: int = 20000
    standard_code_budget: int = 8000
    skeleton_code_budget: int = 1000
    importance_core_percentile: int = 80
    importance_standard_percentile: int = 30
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add config.py tests/test_config_phase1.py
git commit -m "feat(config): add Phase 1 code budget and importance scoring config fields"
```

- [x] **Step 6: Code Review**

Review checklist:
- 配置字段命名是否遵循项目既有风格
- 默认值是否与设计文档一致
- 环境变量 `WIKI__CODE_BUDGET_ENABLED` 等是否可正常工作

---

### Task 2: 新增 CodeSnippet、ImportanceTier 数据模型

**Files:**
- Modify: `wiki/models.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_phase1_models.py
from wiki.models import CodeSnippet, ImportanceTier

def test_code_snippet_creation():
    snippet = CodeSnippet(
        source="def hello():\n    print('hello')",
        file_path="src/main.py",
        start_line=1,
        end_line=2,
        origin="chunk",
    )
    assert snippet.origin == "chunk"
    assert snippet.start_line == 1

def test_code_snippet_origin_values():
    for origin in ("chunk", "file", "signature"):
        snippet = CodeSnippet(
            source="code", file_path="f.py",
            start_line=1, end_line=1, origin=origin,
        )
        assert snippet.origin == origin

def test_importance_tier_values():
    assert ImportanceTier.CORE == "core"
    assert ImportanceTier.STANDARD == "standard"
    assert ImportanceTier.SKELETON == "skeleton"

def test_importance_tier_ordering():
    tiers = [ImportanceTier.SKELETON, ImportanceTier.CORE, ImportanceTier.STANDARD]
    assert ImportanceTier.CORE in tiers
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_phase1_models.py -v`
Expected: FAIL with `ImportError`

- [x] **Step 3: Add new models to wiki/models.py**

在 `wiki/models.py` 中添加：

```python
class ImportanceTier(StrEnum):
    CORE = "core"
    STANDARD = "standard"
    SKELETON = "skeleton"


@dataclass
class CodeSnippet:
    source: str
    file_path: str
    start_line: int
    end_line: int
    origin: str  # "chunk" | "file" | "signature"
```

在 `PageData` 的 `methods` 字段之后添加新字段（使用 `field(default_factory=list)` 和 `None` 默认值保持向后兼容）：

```python
@dataclass
class PageData:
    node: GraphNode
    edges: list[GraphEdge]
    children: list[GraphNode]
    source_location: SourceLocation
    method_locations: list[SourceLocation]
    business_summary: str | None
    methods: list[GraphNode]
    code_snippets: list[CodeSnippet] = field(default_factory=list)
    importance_tier: ImportanceTier | None = None
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/models.py tests/wiki/test_phase1_models.py
git commit -m "feat(wiki): add CodeSnippet, ImportanceTier models and extend PageData"
```

- [x] **Step 6: Code Review**

Review checklist:
- PageData 新增字段是否向后兼容（现有代码不传这些字段仍能正常工作）
- CodeSnippet 的 origin 字段是否应使用 StrEnum 替代 str
- ImportanceTier 命名与设计文档一致性

---

### Task 3: WikiStore 扩展 — Chunk 查询和度数统计

**Files:**
- Modify: `store/wiki_store.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/store/test_wiki_store_chunk.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from store.wiki_store import WikiStore

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[]))
    return WikiStore(store)

@pytest.mark.asyncio
async def test_find_chunks_by_parent_uid(mock_store):
    await mock_store.find_chunks_by_parent_uid("Function:src/main.py:hello:1")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "Chunk" in cypher
    assert "PART_OF" in cypher
    assert "parent_uid" in cypher

@pytest.mark.asyncio
async def test_score_all_entities(mock_store):
    await mock_store.score_all_entities("my-repo")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "repository" in cypher
    assert "in_deg" in cypher or "in_degree" in cypher
    assert "out_deg" in cypher or "out_degree" in cypher
    assert "children" in cypher
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Add Chunk query and scoring methods**

在 `store/wiki_store.py` 的 WikiStore 类中添加：

```python
    # --- Phase 1: Code-aware queries ---

    async def find_chunks_by_parent_uid(self, parent_uid: str) -> QueryResultWrapper:
        """Find all Chunk nodes linked to a parent via PART_OF edge, ordered by chunk_index."""
        q = (
            "MATCH (c:Chunk)-[:PART_OF]->(p) "
            "WHERE p.uid = $parent_uid "
            "RETURN c.text AS text, c.file AS file, "
            "c.start_line AS start_line, c.end_line AS end_line, "
            "coalesce(c.chunk_index, 0) AS chunk_index "
            "ORDER BY chunk_index"
        )
        return await self._store.execute_query(q, {"parent_uid": parent_uid})

    async def score_all_entities(self, repository: str) -> QueryResultWrapper:
        """Single Cypher query to get degree data for all MODULE/CLASS nodes in a repository."""
        q = (
            "MATCH (n) WHERE n.repository = $repo AND (n:Module OR n:Class) "
            "OPTIONAL MATCH (n)<-[in_e]-() "
            "OPTIONAL MATCH (n)-[out_e]->() "
            "OPTIONAL MATCH (n)-[:CONTAINS]->(child) "
            "RETURN n.uid AS uid, labels(n)[0] AS label, "
            "coalesce(n.start_line, 0) AS start_line, "
            "coalesce(n.end_line, 0) AS end_line, "
            "count(DISTINCT in_e) AS in_degree, "
            "count(DISTINCT out_e) AS out_degree, "
            "count(DISTINCT child) AS children_count"
        )
        return await self._store.execute_query(q, {"repo": repository})
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add store/wiki_store.py tests/store/test_wiki_store_chunk.py
git commit -m "feat(wiki-store): add find_chunks_by_parent_uid and score_all_entities queries"
```

- [x] **Step 6: Code Review**

Review checklist:
- Cypher 查询语法正确性
- PART_OF 边方向是否正确（Chunk -[:PART_OF]-> parent）
- score_all_entities 的 OPTIONAL MATCH 是否会导致笛卡尔积性能问题
- 参数化查询防注入

---

### Task 4: SourceCodeReader 实现

**Files:**
- Create: `wiki/source_code_reader.py`
- Create: `tests/wiki/test_source_code_reader.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/wiki/test_source_code_reader.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.source_code_reader import SourceCodeReader
from wiki.models import CodeSnippet
from store.schema import GraphNode, NodeLabel

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.find_chunks_by_parent_uid = AsyncMock()
    return store

def _make_node(label: str = "Class", uid: str = "Class:f.py:Foo:1",
               name: str = "Foo", file: str = "src/foo.py",
               start_line: int = 1, end_line: int = 50,
               signature: str = "class Foo:", docstring: str = "A foo class.") -> GraphNode:
    return GraphNode(
        label=NodeLabel(label),
        uid=uid,
        properties={
            "name": name, "file": file,
            "start_line": start_line, "end_line": end_line,
            "signature": signature, "docstring": docstring,
        },
    )

@pytest.mark.asyncio
async def test_read_from_chunks(mock_wiki_store):
    """When Chunk data is available, code comes from chunks."""
    result = MagicMock()
    result.result_set = [
        ["def hello():\n    pass", "src/foo.py", 1, 5, 0],
        ["def world():\n    pass", "src/foo.py", 6, 10, 1],
    ]
    mock_wiki_store.find_chunks_by_parent_uid.return_value = result

    reader = SourceCodeReader(mock_wiki_store)
    node = _make_node()
    snippets = await reader.read(node, budget_tokens=8000)

    assert len(snippets) >= 1
    assert snippets[0].origin == "chunk"
    assert "def hello" in snippets[0].source

@pytest.mark.asyncio
async def test_fallback_to_signature(mock_wiki_store):
    """When no chunks and no repo_path, fall back to signature+docstring."""
    result = MagicMock()
    result.result_set = []
    mock_wiki_store.find_chunks_by_parent_uid.return_value = result

    reader = SourceCodeReader(mock_wiki_store)
    node = _make_node(signature="class Foo:", docstring="A foo class.")
    snippets = await reader.read(node, budget_tokens=8000)

    assert len(snippets) == 1
    assert snippets[0].origin == "signature"
    assert "class Foo:" in snippets[0].source

@pytest.mark.asyncio
async def test_token_budget_truncation(mock_wiki_store):
    """Code exceeding budget is truncated."""
    long_code = "x = 1\n" * 5000  # ~30000 chars ~7500 tokens
    result = MagicMock()
    result.result_set = [[long_code, "src/foo.py", 1, 5000, 0]]
    mock_wiki_store.find_chunks_by_parent_uid.return_value = result

    reader = SourceCodeReader(mock_wiki_store)
    node = _make_node()
    snippets = await reader.read(node, budget_tokens=1000)

    total_chars = sum(len(s.source) for s in snippets)
    assert total_chars < 1000 * 4 + 200  # budget * 4 chars/token + margin

def test_estimate_tokens():
    reader = SourceCodeReader(MagicMock())
    assert reader.estimate_tokens("hello world") == 2  # 11 chars / 4 ≈ 2

def test_truncate_code():
    reader = SourceCodeReader(MagicMock())
    code = "\n".join(f"line {i}" for i in range(100))
    truncated = reader.truncate_code(code, max_tokens=50)
    assert "[truncated" in truncated
    assert len(truncated) < len(code)
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Implement SourceCodeReader**

```python
# wiki/source_code_reader.py
"""Reads actual source code for wiki page generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from store.schema import GraphNode
from wiki.models import CodeSnippet

logger = logging.getLogger(__name__)


class SourceCodeReader:
    """Reads code from Chunk nodes, file fallback, or signature degradation."""

    def __init__(self, wiki_store: Any) -> None:
        self._store = wiki_store

    async def read(
        self,
        node: GraphNode,
        budget_tokens: int = 8000,
        repo_path: str | None = None,
    ) -> list[CodeSnippet]:
        snippets = await self._read_from_chunks(node)
        if not snippets and repo_path:
            snippets = self._read_from_file(node, repo_path)
        if not snippets:
            snippets = self._fallback_to_signature(node)

        return self._apply_budget(snippets, budget_tokens)

    async def _read_from_chunks(self, node: GraphNode) -> list[CodeSnippet]:
        result = await self._store.find_chunks_by_parent_uid(node.uid)
        if not result or not result.result_set:
            return []

        texts: list[tuple[str, str, int, int]] = []
        for row in result.result_set:
            text, file_path, start_line, end_line, _idx = row
            if text:
                texts.append((str(text), str(file_path), int(start_line), int(end_line)))

        if not texts:
            return []

        merged_source = "\n".join(t[0] for t in texts)
        file_path = texts[0][1]
        start_line = texts[0][2]
        end_line = texts[-1][3]

        return [CodeSnippet(
            source=merged_source,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            origin="chunk",
        )]

    def _read_from_file(self, node: GraphNode, repo_path: str) -> list[CodeSnippet]:
        file_rel = str(node.properties.get("file", ""))
        start_line = int(node.properties.get("start_line", 0))
        end_line = int(node.properties.get("end_line", 0))

        if not file_rel or start_line <= 0:
            return []

        full_path = Path(repo_path) / file_rel
        if not full_path.is_file():
            logger.debug("File not found for code read: %s", full_path)
            return []

        try:
            lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[max(0, start_line - 1):end_line]
            source = "\n".join(selected)
            return [CodeSnippet(
                source=source,
                file_path=file_rel,
                start_line=start_line,
                end_line=end_line,
                origin="file",
            )]
        except OSError:
            logger.debug("Failed to read file: %s", full_path, exc_info=True)
            return []

    def _fallback_to_signature(self, node: GraphNode) -> list[CodeSnippet]:
        sig = str(node.properties.get("signature", ""))
        doc = str(node.properties.get("docstring", ""))
        file_path = str(node.properties.get("file", ""))
        start_line = int(node.properties.get("start_line", 0))
        end_line = int(node.properties.get("end_line", 0))

        parts = [p for p in [sig, doc] if p]
        if not parts:
            return []

        return [CodeSnippet(
            source="\n".join(parts),
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            origin="signature",
        )]

    def _apply_budget(self, snippets: list[CodeSnippet], budget_tokens: int) -> list[CodeSnippet]:
        result = []
        remaining = budget_tokens
        for snippet in snippets:
            tokens = self.estimate_tokens(snippet.source)
            if tokens <= remaining:
                result.append(snippet)
                remaining -= tokens
            else:
                truncated_source = self.truncate_code(snippet.source, remaining)
                result.append(CodeSnippet(
                    source=truncated_source,
                    file_path=snippet.file_path,
                    start_line=snippet.start_line,
                    end_line=snippet.end_line,
                    origin=snippet.origin,
                ))
                break
        return result

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def truncate_code(self, code: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        if len(code) <= max_chars:
            return code
        lines = code.splitlines()
        total_lines = len(lines)
        head_budget = int(max_chars * 0.6)
        tail_budget = max_chars - head_budget - 80  # reserve for truncation marker

        head_lines: list[str] = []
        head_chars = 0
        for line in lines:
            if head_chars + len(line) + 1 > head_budget:
                break
            head_lines.append(line)
            head_chars += len(line) + 1

        tail_lines: list[str] = []
        tail_chars = 0
        for line in reversed(lines):
            if tail_chars + len(line) + 1 > tail_budget:
                break
            tail_lines.insert(0, line)
            tail_chars += len(line) + 1

        skipped = total_lines - len(head_lines) - len(tail_lines)
        marker = f"\n... [truncated {skipped} lines] ...\n"

        return "\n".join(head_lines) + marker + "\n".join(tail_lines)
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/source_code_reader.py tests/wiki/test_source_code_reader.py
git commit -m "feat(wiki): implement SourceCodeReader with chunk/file/signature fallback and token budget"
```

- [x] **Step 6: Code Review**

Review checklist:
- Chunk 拼接逻辑是否正确处理多个 Chunk
- 文件读取异常处理是否安全（不抛出未处理异常）
- Token 估算精度是否足够（len/4 vs tiktoken）
- 截断策略是否保留首尾最有价值的代码

---

### Task 5: ImportanceScorer 实现

**Files:**
- Create: `wiki/importance_scorer.py`
- Create: `tests/wiki/test_importance_scorer.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/wiki/test_importance_scorer.py
import pytest
import math
from unittest.mock import AsyncMock, MagicMock
from wiki.importance_scorer import ImportanceScorer
from wiki.models import ImportanceTier

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.score_all_entities = AsyncMock()
    return store

def test_compute_score_class():
    scorer = ImportanceScorer(MagicMock(), core_percentile=80, standard_percentile=30)
    score = scorer.compute_score(
        label="Class", in_degree=10, out_degree=5,
        children_count=3, code_lines=100, has_subclasses=True,
    )
    expected = (10 * 3) + (5 * 1) + (3 * 2) + math.log2(101) * 2 + 3
    assert abs(score - expected) < 0.01

def test_compute_score_module():
    scorer = ImportanceScorer(MagicMock(), core_percentile=80, standard_percentile=30)
    score = scorer.compute_score(
        label="Module", in_degree=5, out_degree=2,
        children_count=10, code_lines=500, has_subclasses=False,
    )
    expected = (5 * 3) + (2 * 1) + (10 * 2) + math.log2(501) * 2 + 5
    assert abs(score - expected) < 0.01

def test_classify_by_percentile():
    scorer = ImportanceScorer(MagicMock(), core_percentile=80, standard_percentile=30)
    scores = {"a": 100, "b": 80, "c": 60, "d": 40, "e": 20}
    result = scorer.classify_by_percentile(scores)
    assert result["a"] == ImportanceTier.CORE
    assert result["e"] == ImportanceTier.SKELETON

@pytest.mark.asyncio
async def test_score_all(mock_wiki_store):
    result = MagicMock()
    result.result_set = [
        ["uid1", "Class", 1, 100, 10, 5, 3],
        ["uid2", "Module", 1, 500, 5, 2, 10],
        ["uid3", "Class", 1, 20, 1, 1, 0],
    ]
    mock_wiki_store.score_all_entities.return_value = result

    scorer = ImportanceScorer(mock_wiki_store, core_percentile=80, standard_percentile=30)
    tiers = await scorer.score_all("my-repo")

    assert isinstance(tiers, dict)
    assert all(isinstance(v, ImportanceTier) for v in tiers.values())
    assert len(tiers) == 3
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Implement ImportanceScorer**

```python
# wiki/importance_scorer.py
"""Entity importance scoring for tiered wiki generation."""

from __future__ import annotations

import logging
import math
from typing import Any

from wiki.models import ImportanceTier

logger = logging.getLogger(__name__)


class ImportanceScorer:
    """Scores entities by graph metrics and classifies into importance tiers."""

    def __init__(
        self,
        wiki_store: Any,
        core_percentile: int = 80,
        standard_percentile: int = 30,
    ) -> None:
        self._store = wiki_store
        self._core_pct = core_percentile
        self._standard_pct = standard_percentile

    async def score_all(self, repository: str) -> dict[str, ImportanceTier]:
        result = await self._store.score_all_entities(repository)
        if not result or not result.result_set:
            return {}

        scores: dict[str, float] = {}
        for row in result.result_set:
            uid, label, start_line, end_line, in_deg, out_deg, children = row
            code_lines = max(0, int(end_line) - int(start_line))
            has_subclasses = str(label) == "Class" and int(children) > 0
            scores[str(uid)] = self.compute_score(
                label=str(label),
                in_degree=int(in_deg),
                out_degree=int(out_deg),
                children_count=int(children),
                code_lines=code_lines,
                has_subclasses=has_subclasses,
            )

        return self.classify_by_percentile(scores)

    def compute_score(
        self,
        label: str,
        in_degree: int,
        out_degree: int,
        children_count: int,
        code_lines: int,
        has_subclasses: bool,
    ) -> float:
        score = (
            (in_degree * 3)
            + (out_degree * 1)
            + (children_count * 2)
            + math.log2(code_lines + 1) * 2
        )
        if label == "Module":
            score += 5
        if label == "Class" and has_subclasses:
            score += 3
        return score

    def classify_by_percentile(self, scores: dict[str, float]) -> dict[str, ImportanceTier]:
        if not scores:
            return {}
        sorted_scores = sorted(scores.values())
        n = len(sorted_scores)

        core_threshold = sorted_scores[max(0, int(n * self._core_pct / 100) - 1)]
        standard_threshold = sorted_scores[max(0, int(n * self._standard_pct / 100) - 1)]

        result: dict[str, ImportanceTier] = {}
        for uid, score in scores.items():
            if score >= core_threshold:
                result[uid] = ImportanceTier.CORE
            elif score >= standard_threshold:
                result[uid] = ImportanceTier.STANDARD
            else:
                result[uid] = ImportanceTier.SKELETON
        return result
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/importance_scorer.py tests/wiki/test_importance_scorer.py
git commit -m "feat(wiki): implement ImportanceScorer with graph-based scoring and percentile classification"
```

- [x] **Step 6: Code Review**

Review checklist:
- 评分公式是否与设计文档一致
- 百分位阈值计算的边界条件（空集、单元素、所有相同分数）
- has_subclasses 判断逻辑是否准确（children 包含方法和子类，应只计子类）
- 单次 Cypher 查询性能是否可接受

---

### Task 6: 集成 SourceCodeReader 到 WikiDataCollector

**Files:**
- Modify: `wiki/data_collector.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_data_collector_code.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.data_collector import WikiDataCollector, PageData
from store.schema import GraphNode, GraphEdge, NodeLabel

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
    result.result_set = [["print('hello')", "src/main.py", 1, 5, 0]]
    store.find_chunks_by_parent_uid = AsyncMock(return_value=result)
    return store

@pytest.mark.asyncio
async def test_collect_includes_code_snippets(mock_graph_port, mock_wiki_store):
    collector = WikiDataCollector(mock_graph_port, wiki_store=mock_wiki_store)
    node = GraphNode(
        label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
    )
    page_data = await collector.collect("my-repo", node)

    assert hasattr(page_data, "code_snippets")
    assert len(page_data.code_snippets) > 0
    assert page_data.code_snippets[0].origin == "chunk"

@pytest.mark.asyncio
async def test_collect_without_wiki_store_has_empty_snippets(mock_graph_port):
    """When wiki_store is None (backward compatible), code_snippets is empty."""
    collector = WikiDataCollector(mock_graph_port)
    node = GraphNode(
        label=NodeLabel.CLASS, uid="Class:f.py:Foo:1",
        properties={"name": "Foo", "file": "src/foo.py", "start_line": 1, "end_line": 50},
    )
    page_data = await collector.collect("my-repo", node)

    assert page_data.code_snippets == []
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Integrate SourceCodeReader into WikiDataCollector**

修改 `wiki/data_collector.py`：

1. 在 `WikiDataCollector.__init__` 中添加可选的 `wiki_store` 参数
2. 在 `collect()` 中调用 SourceCodeReader 读取代码
3. 将 code_snippets 传入 PageData

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/data_collector.py tests/wiki/test_data_collector_code.py
git commit -m "feat(wiki): integrate SourceCodeReader into WikiDataCollector for code-aware collection"
```

- [x] **Step 6: Code Review**

Review checklist:
- WikiDataCollector 的构造函数是否保持向后兼容（wiki_store=None）
- code_budget 参数如何传递（通过 collect 参数还是构造函数配置？）
- 现有 WikiDataCollector 测试是否受影响

---

### Task 7: 增强 _entity_digest 嵌入代码片段

**Files:**
- Modify: `wiki/composer.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_composer_code_digest.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.composer import WikiComposer
from wiki.data_collector import PageData
from wiki.models import CodeSnippet, ImportanceTier
from store.schema import GraphNode, NodeLabel
from wiki.models import SourceLocation, WikiPageMetadata

def _make_page_data_with_code() -> PageData:
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
        code_snippets=[CodeSnippet(
            source="class Foo:\n    def bar(self):\n        return 42",
            file_path="src/foo.py", start_line=1, end_line=3, origin="chunk",
        )],
        importance_tier=ImportanceTier.CORE,
    )

def test_entity_digest_includes_code():
    composer = WikiComposer(store=MagicMock())
    page_data = _make_page_data_with_code()
    digest = composer._entity_digest(page_data)
    assert "class Foo:" in digest
    assert "def bar" in digest
```

- [x] **Step 2: Run test to verify it fails**

- [x] **Step 3: Enhance _entity_digest**

在 `wiki/composer.py` 的 `_entity_digest` 方法末尾，在返回之前添加代码片段部分：

```python
    # Append code snippets if available
    if hasattr(page_data, "code_snippets") and page_data.code_snippets:
        lines.append(f"\n### Source Code ({page_data.code_snippets[0].origin})")
        for snippet in page_data.code_snippets:
            lines.append(f"```\n{snippet.source}\n```")
            lines.append(f"- File: {snippet.file_path}:{snippet.start_line}-{snippet.end_line}")
```

- [x] **Step 4: Run test to verify it passes**

- [x] **Step 5: Commit**

```bash
git add wiki/composer.py tests/wiki/test_composer_code_digest.py
git commit -m "feat(wiki): enhance _entity_digest to embed code snippets in LLM prompt"
```

- [x] **Step 6: Code Review**

Review checklist:
- 代码片段在 prompt 中的位置是否合理（末尾 vs 中间）
- token 预算是否在 _entity_digest 层面再次检查
- hasattr 检查是否必要（PageData 已有默认值时）
- 对现有测试的影响

---

### Task 8: 集成到 WikiService + 集成验证

**Files:**
- Modify: `wiki/service.py`

- [x] **Step 1: Write the failing test**

```python
# tests/wiki/test_service_importance.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.models import ImportanceTier

@pytest.mark.asyncio
async def test_generate_passes_importance_tier_to_persist():
    """Verify that WikiService.generate() calls ImportanceScorer and passes tiers to persist."""
    # This test verifies the integration point — ImportanceScorer is called
    # and importance_tier is included in the page dicts sent to persist_wiki_pages
    from wiki.service import WikiService
    # (mock setup and assertions — detailed implementation depends on service.py structure)
    pass  # Placeholder — implementer fills in based on actual service.py
```

- [x] **Step 2-4: Integrate ImportanceScorer into WikiService.generate()**

在 `wiki/service.py` 的 `generate()` 方法中：

1. 在 `WikiStructurePlanner.plan()` 之后、compose 之前调用 `ImportanceScorer.score_all()`
2. 将 tier 信息传递给 `WikiDataCollector` 和 `WikiComposer`
3. 在 `_persist_pages_to_graph()` 中包含 `importance_tier`

- [x] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest tests/ -v --tb=short -q`

- [x] **Step 6: Update wiki/__init__.py exports**

```python
from wiki.source_code_reader import SourceCodeReader
from wiki.importance_scorer import ImportanceScorer
from wiki.models import CodeSnippet, ImportanceTier
```

- [x] **Step 7: Commit**

```bash
git add wiki/service.py wiki/__init__.py tests/wiki/test_service_importance.py
git commit -m "feat(wiki): integrate ImportanceScorer into WikiService pipeline and export new components"
```

- [x] **Step 8: Code Review**

Review checklist:
- ImportanceScorer 在 generate() 流程中的位置是否正确
- importance_tier 是否正确传递到 persist_wiki_pages
- 向后兼容性（ImportanceScorer 不可用时是否降级）
- generate_stream_events() 是否也需要集成
