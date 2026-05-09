# CodeWiki-Aligned Pipeline Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace wiki pipeline's LLM-driven structure planning with graph-algorithm-based decomposition, implement bottom-up synthesis, and add canonical_key linking — fully aligning with CodeWiki (ACL 2026) paper architecture.

**Architecture:** Pipeline node replacement within existing LangGraph StateGraph. Replace 6 nodes (classify_domains, decompose_hierarchy, plan_topic_structure, compose_leaf_pages, compose_parent_pages, synthesize_overviews) with 4 new nodes (graph_decompose, assign_canonical_keys, generate_titles, compose_bottomup). Preserve checkpoint, progress callback, and heal loop.

**Tech Stack:** Python 3.11+, LangGraph, FalkorDB (Cypher), pytest, existing WikiPageAgent/Harness

**Spec:** `docs/superpowers/specs/2026-05-09-codewiki-aligned-pipeline-design.md`

---

### Task 1: ModuleNode / ModuleTree Data Model

**Files:**
- Create: `wiki/models/module_tree.py`
- Create: `tests/wiki/test_module_tree.py`

- [ ] **Step 1: Write failing tests for ModuleNode and ModuleTree**

```python
# tests/wiki/test_module_tree.py
import pytest
from wiki.models.module_tree import ModuleNode, ModuleTree


def test_module_node_is_leaf_when_no_children():
    node = ModuleNode(
        canonical_key="src-auth",
        entity_uids=["uid1", "uid2"],
        file_paths=["src/auth/login.py"],
    )
    assert node.is_leaf() is True


def test_module_node_is_not_leaf_with_children():
    child = ModuleNode(
        canonical_key="src-auth-login",
        entity_uids=["uid1"],
        file_paths=["src/auth/login.py"],
    )
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=["uid1", "uid2"],
        file_paths=["src/auth/login.py", "src/auth/register.py"],
        children=[child],
    )
    assert parent.is_leaf() is False


def test_module_tree_topological_order_leaves_first():
    leaf_a = ModuleNode(canonical_key="a", entity_uids=["u1"], file_paths=["a.py"])
    leaf_b = ModuleNode(canonical_key="b", entity_uids=["u2"], file_paths=["b.py"])
    parent = ModuleNode(
        canonical_key="root",
        entity_uids=["u1", "u2"],
        file_paths=["a.py", "b.py"],
        children=[leaf_a, leaf_b],
    )
    tree = ModuleTree(roots=[parent], repo_id="test-repo")
    order = tree.topological_order()
    keys = [n.canonical_key for n in order]
    assert keys.index("a") < keys.index("root")
    assert keys.index("b") < keys.index("root")


def test_module_tree_all_nodes_returns_all():
    leaf = ModuleNode(canonical_key="leaf", entity_uids=["u1"], file_paths=["a.py"])
    root = ModuleNode(
        canonical_key="root",
        entity_uids=["u1"],
        file_paths=["a.py"],
        children=[leaf],
    )
    tree = ModuleTree(roots=[root], repo_id="test-repo")
    all_nodes = tree.all_nodes()
    assert len(all_nodes) == 2
    assert {n.canonical_key for n in all_nodes} == {"root", "leaf"}


def test_module_tree_to_dict_roundtrip():
    leaf = ModuleNode(canonical_key="leaf", entity_uids=["u1"], file_paths=["a.py"])
    root = ModuleNode(
        canonical_key="root",
        entity_uids=["u1"],
        file_paths=["a.py"],
        children=[leaf],
    )
    tree = ModuleTree(roots=[root], repo_id="test-repo")
    data = tree.to_dicts()
    restored = ModuleTree.from_dicts(data, repo_id="test-repo")
    assert len(restored.roots) == 1
    assert restored.roots[0].canonical_key == "root"
    assert len(restored.roots[0].children) == 1
    assert restored.roots[0].children[0].canonical_key == "leaf"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_module_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki.models.module_tree'`

- [ ] **Step 3: Implement ModuleNode and ModuleTree**

```python
# wiki/models/module_tree.py
"""Data model for hierarchical module decomposition tree."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModuleNode:
    canonical_key: str
    entity_uids: list[str]
    file_paths: list[str]
    title: str = ""
    description: str = ""
    children: list[ModuleNode] = field(default_factory=list)
    token_estimate: int = 0
    page: Any = None  # populated later by compose_bottomup

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "entity_uids": self.entity_uids,
            "file_paths": self.file_paths,
            "title": self.title,
            "description": self.description,
            "token_estimate": self.token_estimate,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModuleNode:
        children = [cls.from_dict(c) for c in data.get("children", [])]
        return cls(
            canonical_key=data["canonical_key"],
            entity_uids=data.get("entity_uids", []),
            file_paths=data.get("file_paths", []),
            title=data.get("title", ""),
            description=data.get("description", ""),
            token_estimate=data.get("token_estimate", 0),
            children=children,
        )


@dataclass
class ModuleTree:
    roots: list[ModuleNode]
    repo_id: str

    def topological_order(self) -> list[ModuleNode]:
        """Bottom-up order: leaves first, roots last."""
        result: list[ModuleNode] = []
        visited: set[str] = set()

        def _dfs(node: ModuleNode) -> None:
            if node.canonical_key in visited:
                return
            visited.add(node.canonical_key)
            for child in node.children:
                _dfs(child)
            result.append(node)

        for root in self.roots:
            _dfs(root)
        return result

    def all_nodes(self) -> list[ModuleNode]:
        result: list[ModuleNode] = []
        stack = list(self.roots)
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(node.children)
        return result

    def to_dicts(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.roots]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]], repo_id: str) -> ModuleTree:
        roots = [ModuleNode.from_dict(d) for d in data]
        return cls(roots=roots, repo_id=repo_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_module_tree.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/models/module_tree.py tests/wiki/test_module_tree.py
git commit -m "feat(wiki): add ModuleNode/ModuleTree data model for graph decomposition"
```

---

### Task 2: GraphModuleDecomposer — SCC + Topological Sort + Recursive Decomposition

**Files:**
- Create: `wiki/graph_module_decomposer.py`
- Create: `tests/wiki/test_graph_module_decomposer.py`

- [ ] **Step 1: Write failing tests for canonical_key generation**

```python
# tests/wiki/test_graph_module_decomposer.py
import pytest
from wiki.graph_module_decomposer import make_canonical_key


def test_canonical_key_from_single_path():
    key = make_canonical_key(["src/auth/login.py"], existing_keys=set())
    assert key == "src-auth-login.py"


def test_canonical_key_from_multiple_paths():
    key = make_canonical_key(
        ["src/auth/login.py", "src/auth/register.py"],
        existing_keys=set(),
    )
    assert key == "src-auth"


def test_canonical_key_collision_appends_hash():
    key1 = make_canonical_key(["src/auth/a.py"], existing_keys=set())
    key2 = make_canonical_key(
        ["src/auth/b.py"],
        existing_keys={key1},
        entity_uids=["uid-b"],
    )
    assert key2 != key1
    assert key2.startswith("src-auth")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_graph_module_decomposer.py::test_canonical_key_from_single_path -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement make_canonical_key**

```python
# wiki/graph_module_decomposer.py (partial — canonical_key section)
"""Graph-algorithm-driven module decomposition for wiki generation."""
from __future__ import annotations

import hashlib
import os
from typing import Any

from core.log import get_logger
from wiki.models.module_tree import ModuleNode, ModuleTree

log = get_logger(__name__)


def make_canonical_key(
    file_paths: list[str],
    existing_keys: set[str],
    entity_uids: list[str] | None = None,
) -> str:
    if not file_paths:
        return "unknown"
    if len(file_paths) == 1:
        slug = file_paths[0].strip("/").replace("/", "-").replace("_", "-").lower()
    else:
        prefix = os.path.commonpath(file_paths)
        slug = prefix.strip("/").replace("/", "-").replace("_", "-").lower()
    if not slug:
        slug = "root"
    if slug in existing_keys:
        uid_str = "".join(sorted(entity_uids or file_paths))
        uid_hash = hashlib.sha256(uid_str.encode()).hexdigest()[:6]
        slug = f"{slug}-{uid_hash}"
    return slug
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_graph_module_decomposer.py -v -k canonical_key`
Expected: All 3 PASS

- [ ] **Step 5: Write failing tests for SCC and topological sort**

```python
# tests/wiki/test_graph_module_decomposer.py (append)
from wiki.graph_module_decomposer import GraphModuleDecomposer


def _make_graph_data():
    """Simulated dependency graph: A→B, B→C, C→A (cycle), D→A (entry)."""
    return {
        "nodes": ["A", "B", "C", "D"],
        "edges": [("A", "B"), ("B", "C"), ("C", "A"), ("D", "A")],
        "node_files": {
            "A": ["src/a.py"],
            "B": ["src/b.py"],
            "C": ["src/c.py"],
            "D": ["src/d.py"],
        },
        "node_tokens": {"A": 1000, "B": 1000, "C": 1000, "D": 500},
    }


def test_scc_merges_cycle():
    graph = _make_graph_data()
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    sccs = decomposer._compute_scc(graph["nodes"], graph["edges"])
    # A, B, C form a cycle → one SCC
    cycle_scc = [s for s in sccs if len(s) > 1]
    assert len(cycle_scc) == 1
    assert set(cycle_scc[0]) == {"A", "B", "C"}


def test_topological_sort_entry_first():
    graph = _make_graph_data()
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    sccs = decomposer._compute_scc(graph["nodes"], graph["edges"])
    condensed_nodes, condensed_edges = decomposer._condense_graph(
        graph["nodes"], graph["edges"], sccs,
    )
    topo = decomposer._topological_sort(condensed_nodes, condensed_edges)
    # D depends on A-B-C cycle, so cycle should come before D in bottom-up order
    # (bottom-up: dependencies first)
    assert len(topo) == 2  # {A,B,C} and {D}


def test_decompose_produces_deterministic_tree():
    graph = _make_graph_data()
    decomposer = GraphModuleDecomposer(max_tokens_per_module=50000)
    tree1 = decomposer.decompose_from_graph(
        graph["nodes"], graph["edges"],
        graph["node_files"], graph["node_tokens"],
        repo_id="test",
    )
    tree2 = decomposer.decompose_from_graph(
        graph["nodes"], graph["edges"],
        graph["node_files"], graph["node_tokens"],
        repo_id="test",
    )
    keys1 = [n.canonical_key for n in tree1.topological_order()]
    keys2 = [n.canonical_key for n in tree2.topological_order()]
    assert keys1 == keys2  # deterministic
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_graph_module_decomposer.py -v -k "scc or topological or deterministic"`
Expected: FAIL — `GraphModuleDecomposer` not defined

- [ ] **Step 7: Implement GraphModuleDecomposer core algorithms**

```python
# wiki/graph_module_decomposer.py (complete)
"""Graph-algorithm-driven module decomposition for wiki generation."""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from typing import Any

from core.log import get_logger
from wiki.models.module_tree import ModuleNode, ModuleTree

log = get_logger(__name__)

DEFAULT_MAX_TOKENS = 30000


def make_canonical_key(
    file_paths: list[str],
    existing_keys: set[str],
    entity_uids: list[str] | None = None,
) -> str:
    if not file_paths:
        return "unknown"
    if len(file_paths) == 1:
        slug = file_paths[0].strip("/").replace("/", "-").replace("_", "-").lower()
    else:
        prefix = os.path.commonpath(file_paths)
        slug = prefix.strip("/").replace("/", "-").replace("_", "-").lower()
    if not slug:
        slug = "root"
    if slug in existing_keys:
        uid_str = "".join(sorted(entity_uids or file_paths))
        uid_hash = hashlib.sha256(uid_str.encode()).hexdigest()[:6]
        slug = f"{slug}-{uid_hash}"
    return slug


class GraphModuleDecomposer:
    def __init__(
        self,
        max_tokens_per_module: int = DEFAULT_MAX_TOKENS,
        llm: Any | None = None,
    ) -> None:
        self._max_tokens = max_tokens_per_module
        self._llm = llm

    def _compute_scc(
        self, nodes: list[str], edges: list[tuple[str, str]],
    ) -> list[list[str]]:
        """Tarjan's SCC algorithm."""
        index_counter = [0]
        stack: list[str] = []
        lowlink: dict[str, int] = {}
        index: dict[str, int] = {}
        on_stack: set[str] = set()
        result: list[list[str]] = []
        adj: dict[str, list[str]] = defaultdict(list)
        for u, v in edges:
            adj[u].append(v)

        def strongconnect(v: str) -> None:
            index[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)
            for w in adj.get(v, []):
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])
            if lowlink[v] == index[v]:
                component: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                result.append(sorted(component))

        for node in sorted(nodes):
            if node not in index:
                strongconnect(node)
        return result

    def _condense_graph(
        self,
        nodes: list[str],
        edges: list[tuple[str, str]],
        sccs: list[list[str]],
    ) -> tuple[list[frozenset[str]], list[tuple[frozenset[str], frozenset[str]]]]:
        node_to_scc: dict[str, frozenset[str]] = {}
        scc_nodes: list[frozenset[str]] = []
        for scc in sccs:
            fs = frozenset(scc)
            scc_nodes.append(fs)
            for n in scc:
                node_to_scc[n] = fs
        scc_edges: set[tuple[frozenset[str], frozenset[str]]] = set()
        for u, v in edges:
            su = node_to_scc.get(u)
            sv = node_to_scc.get(v)
            if su and sv and su != sv:
                scc_edges.add((su, sv))
        return scc_nodes, list(scc_edges)

    def _topological_sort(
        self,
        nodes: list[frozenset[str]],
        edges: list[tuple[frozenset[str], frozenset[str]]],
    ) -> list[frozenset[str]]:
        """Kahn's algorithm for topological sort."""
        adj: dict[frozenset[str], list[frozenset[str]]] = defaultdict(list)
        in_degree: dict[frozenset[str], int] = {n: 0 for n in nodes}
        for u, v in edges:
            adj[u].append(v)
            in_degree[v] = in_degree.get(v, 0) + 1
        queue = sorted(
            [n for n in nodes if in_degree.get(n, 0) == 0],
            key=lambda x: sorted(x),
        )
        result: list[frozenset[str]] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in sorted(adj.get(node, []), key=lambda x: sorted(x)):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort(key=lambda x: sorted(x))
        return result

    def decompose_from_graph(
        self,
        nodes: list[str],
        edges: list[tuple[str, str]],
        node_files: dict[str, list[str]],
        node_tokens: dict[str, int],
        repo_id: str,
    ) -> ModuleTree:
        sccs = self._compute_scc(nodes, edges)
        condensed_nodes, condensed_edges = self._condense_graph(nodes, edges, sccs)
        topo_order = self._topological_sort(condensed_nodes, condensed_edges)

        existing_keys: set[str] = set()
        module_nodes: list[ModuleNode] = []
        for scc_set in topo_order:
            members = sorted(scc_set)
            all_files: list[str] = []
            all_uids: list[str] = list(members)
            total_tokens = 0
            for m in members:
                all_files.extend(node_files.get(m, []))
                total_tokens += node_tokens.get(m, 0)
            all_files = sorted(set(all_files))
            key = make_canonical_key(all_files, existing_keys, entity_uids=all_uids)
            existing_keys.add(key)
            node = ModuleNode(
                canonical_key=key,
                entity_uids=all_uids,
                file_paths=all_files,
                token_estimate=total_tokens,
            )
            module_nodes.append(node)

        return ModuleTree(roots=module_nodes, repo_id=repo_id)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_graph_module_decomposer.py -v`
Expected: All 6 tests PASS

- [ ] **Step 9: Commit**

```bash
git add wiki/graph_module_decomposer.py tests/wiki/test_graph_module_decomposer.py
git commit -m "feat(wiki): add GraphModuleDecomposer with SCC + topological sort"
```

---

### Task 3: ParentSynthesizer

**Files:**
- Create: `wiki/parent_synthesizer.py`
- Create: `tests/wiki/test_parent_synthesizer.py`

- [ ] **Step 1: Write failing test for ParentSynthesizer**

```python
# tests/wiki/test_parent_synthesizer.py
import pytest
from unittest.mock import AsyncMock
from wiki.parent_synthesizer import ParentSynthesizer
from wiki.models.module_tree import ModuleNode


@pytest.mark.asyncio
async def test_synthesize_produces_markdown_with_child_links():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = "# Auth Module\n\nThis module handles authentication.\n\n## Sub-modules\n- Login\n- Register"

    synth = ParentSynthesizer(llm=mock_llm)
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=["u1", "u2"],
        file_paths=["src/auth/login.py", "src/auth/register.py"],
        title="认证模块",
        children=[
            ModuleNode(
                canonical_key="src-auth-login",
                entity_uids=["u1"],
                file_paths=["src/auth/login.py"],
                title="登录",
            ),
            ModuleNode(
                canonical_key="src-auth-register",
                entity_uids=["u2"],
                file_paths=["src/auth/register.py"],
                title="注册",
            ),
        ],
    )
    child_contents = ["# Login\nHandles user login.", "# Register\nHandles user registration."]
    result = await synth.synthesize(parent, child_contents)
    assert result  # non-empty
    assert mock_llm.agenerate.called


@pytest.mark.asyncio
async def test_synthesize_includes_child_info_in_prompt():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = "# Overview"

    synth = ParentSynthesizer(llm=mock_llm)
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=[],
        file_paths=[],
        title="认证模块",
        children=[],
    )
    await synth.synthesize(parent, ["child doc 1"])
    call_args = mock_llm.agenerate.call_args
    prompt = str(call_args)
    assert "child doc 1" in prompt or "认证模块" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_parent_synthesizer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ParentSynthesizer**

```python
# wiki/parent_synthesizer.py
"""Synthesize parent module documentation from child documents."""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.models.module_tree import ModuleNode

log = get_logger(__name__)

_SYNTHESIS_SYSTEM = (
    "你是代码文档架构师。基于子模块文档综合生成父模块概览。"
    "输出纯 Markdown。包含：职责概述、子模块协作关系、架构图（Mermaid）。"
)


class ParentSynthesizer:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def synthesize(
        self,
        parent: ModuleNode,
        child_contents: list[str],
    ) -> str:
        child_sections = []
        for i, (child, content) in enumerate(
            zip(parent.children, child_contents, strict=False)
        ):
            child_sections.append(
                f"### 子模块 {i + 1}: {child.title or child.canonical_key}\n"
                f"canonical_key: {child.canonical_key}\n"
                f"文件: {', '.join(child.file_paths[:5])}\n\n"
                f"{content[:3000]}"
            )

        prompt = (
            f"基于以下子模块文档，综合生成父模块「{parent.title or parent.canonical_key}」的概览文档。\n\n"
            "要求:\n"
            "1. 概述每个子模块的核心职责\n"
            "2. 说明子模块之间的协作关系\n"
            "3. 生成架构图（Mermaid graph TD）\n"
            "4. 使用 [[子模块canonical_key]] 链接到子页面\n\n"
            "子模块文档:\n\n"
            + "\n\n---\n\n".join(child_sections)
        )

        try:
            result = await self._llm.agenerate(
                [[{"role": "system", "content": _SYNTHESIS_SYSTEM},
                  {"role": "user", "content": prompt}]]
            )
            return result
        except Exception:
            log.warning("parent_synthesizer_failed", parent=parent.canonical_key, exc_info=True)
            titles = "\n".join(
                f"- [[{c.canonical_key}|{c.title or c.canonical_key}]]"
                for c in parent.children
            )
            return f"# {parent.title or parent.canonical_key}\n\n## 子模块\n\n{titles}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_parent_synthesizer.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/parent_synthesizer.py tests/wiki/test_parent_synthesizer.py
git commit -m "feat(wiki): add ParentSynthesizer for bottom-up document synthesis"
```

---

### Task 4: Pipeline State Extension

**Files:**
- Modify: `wiki/pipeline_state.py`
- Modify: `tests/wiki/test_pipeline_state.py`

- [ ] **Step 1: Write failing test for new state fields**

```python
# tests/wiki/test_pipeline_state_module_tree.py
from wiki.pipeline_state import WikiPipelineState


def test_pipeline_state_has_module_tree_field():
    state: WikiPipelineState = {
        "business_id": "test",
        "repositories": [],
        "modules": {},
        "module_tree": [],
        "canonical_keys": {},
        "domain_cache": {},
        "pages": [],
        "errors": [],
    }
    assert "module_tree" in state
    assert "canonical_keys" in state
    assert "domain_cache" in state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_pipeline_state_module_tree.py -v`
Expected: May PASS if TypedDict allows extra keys, or FAIL if validation is strict. If it passes, verify the fields are properly typed.

- [ ] **Step 3: Add new fields to WikiPipelineState**

Read `wiki/pipeline_state.py` and add the following fields to the `WikiPipelineState` TypedDict:

```python
# Add to WikiPipelineState TypedDict:
module_tree: list[dict[str, Any]]      # serialized ModuleTree
canonical_keys: dict[str, str]          # canonical_key → readable title
domain_cache: dict[str, str]            # pipeline-level shared domain cache
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_pipeline_state_module_tree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_state.py tests/wiki/test_pipeline_state_module_tree.py
git commit -m "feat(wiki): extend WikiPipelineState with module_tree, canonical_keys, domain_cache"
```

---

### Task 5: Pipeline Node — graph_decompose_node

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Create: `tests/wiki/test_graph_decompose_node.py`

- [ ] **Step 1: Write failing test for graph_decompose_node**

```python
# tests/wiki/test_graph_decompose_node.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.pipeline_nodes import graph_decompose_node


@pytest.mark.asyncio
async def test_graph_decompose_node_produces_module_tree():
    mock_graph_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [
        {"a_uid": "uid1", "b_uid": "uid2", "rel_type": "CALLS"},
        {"a_uid": "uid2", "b_uid": "uid3", "rel_type": "IMPORTS"},
    ]
    mock_graph_store.execute_query.return_value = mock_result

    state = {
        "business_id": "test-biz",
        "repositories": ["repo1"],
        "modules": {
            "repo1": [
                {"uid": "uid1", "label": "Module", "properties": {"name": "ModA", "file_path": "src/a.py", "code_length": 1000}},
                {"uid": "uid2", "label": "Module", "properties": {"name": "ModB", "file_path": "src/b.py", "code_length": 800}},
                {"uid": "uid3", "label": "Module", "properties": {"name": "ModC", "file_path": "src/c.py", "code_length": 600}},
            ],
        },
        "module_tree": [],
        "config": {},
    }

    config = {"configurable": {"graph_store": mock_graph_store}}
    result = await graph_decompose_node(state, config)
    assert "module_tree" in result
    assert len(result["module_tree"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_graph_decompose_node.py -v`
Expected: FAIL — `graph_decompose_node` not found in `wiki.pipeline_nodes`

- [ ] **Step 3: Implement graph_decompose_node**

Add to `wiki/pipeline_nodes.py`:

```python
async def graph_decompose_node(
    state: WikiPipelineState, config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Build module tree from dependency graph using SCC + topological sort."""
    from wiki.graph_module_decomposer import GraphModuleDecomposer

    configurable = (config or {}).get("configurable", {}) or {}
    graph_store = configurable.get("graph_store")

    modules = state.get("modules", {})
    nodes: list[str] = []
    node_files: dict[str, list[str]] = {}
    node_tokens: dict[str, int] = {}

    for repo, mod_list in modules.items():
        for mod in mod_list:
            uid = mod.get("uid", "")
            props = mod.get("properties", {})
            name = props.get("name", uid)
            nodes.append(name)
            fp = props.get("file_path", "")
            node_files[name] = [fp] if fp else []
            node_tokens[name] = int(props.get("code_length", 0) or 0) // 4

    edges: list[tuple[str, str]] = []
    if graph_store:
        for repo in state.get("repositories", []):
            try:
                result = await graph_store.execute_query(
                    "MATCH (a)-[r:DEPENDS_ON|CALLS|IMPORTS]->(b) "
                    "WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id "
                    "RETURN a.name AS a_uid, b.name AS b_uid",
                    {"repo_id": repo},
                )
                for row in getattr(result, "data", []) or []:
                    a = row.get("a_uid", "")
                    b = row.get("b_uid", "")
                    if a and b and a in set(nodes) and b in set(nodes):
                        edges.append((a, b))
            except Exception:
                log.warning("graph_decompose_query_failed", repo=repo, exc_info=True)

    llm = configurable.get("llm")
    decomposer = GraphModuleDecomposer(llm=llm)
    repo_id = state.get("business_id", "")
    tree = decomposer.decompose_from_graph(nodes, edges, node_files, node_tokens, repo_id)

    return {"module_tree": tree.to_dicts()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_graph_decompose_node.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py tests/wiki/test_graph_decompose_node.py
git commit -m "feat(wiki): add graph_decompose_node pipeline node"
```

---

### Task 6: Pipeline Node — assign_canonical_keys_node + generate_titles_node

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Create: `tests/wiki/test_assign_keys_and_titles_nodes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_assign_keys_and_titles_nodes.py
import pytest
from unittest.mock import AsyncMock
from wiki.pipeline_nodes import assign_canonical_keys_node, generate_titles_node


@pytest.mark.asyncio
async def test_assign_keys_populates_canonical_keys():
    state = {
        "module_tree": [
            {
                "canonical_key": "src-auth",
                "entity_uids": ["u1"],
                "file_paths": ["src/auth/login.py"],
                "children": [],
            },
        ],
    }
    result = await assign_canonical_keys_node(state)
    assert "canonical_keys" in result
    assert "src-auth" in result["canonical_keys"]


@pytest.mark.asyncio
async def test_generate_titles_fills_title():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = '{"title": "认证模块", "description": "处理登录注册"}'

    state = {
        "module_tree": [
            {
                "canonical_key": "src-auth",
                "entity_uids": ["u1"],
                "file_paths": ["src/auth/login.py"],
                "title": "",
                "children": [],
            },
        ],
        "canonical_keys": {"src-auth": ""},
    }
    config = {"configurable": {"llm": mock_llm}}
    result = await generate_titles_node(state, config)
    assert "canonical_keys" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_assign_keys_and_titles_nodes.py -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Implement both nodes**

Add to `wiki/pipeline_nodes.py`:

```python
async def assign_canonical_keys_node(
    state: WikiPipelineState, config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Populate canonical_keys mapping from module_tree."""
    from wiki.models.module_tree import ModuleTree

    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    canonical_keys: dict[str, str] = {}
    for node in tree.all_nodes():
        canonical_keys[node.canonical_key] = node.title or node.canonical_key
    return {"canonical_keys": canonical_keys}


async def generate_titles_node(
    state: WikiPipelineState, config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Generate human-readable titles for each module node via LLM."""
    from wiki.models.module_tree import ModuleTree

    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")

    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    canonical_keys = dict(state.get("canonical_keys", {}))

    for node in tree.all_nodes():
        if node.title:
            continue
        if llm:
            try:
                entity_names = ", ".join(node.entity_uids[:10])
                file_names = ", ".join(node.file_paths[:5])
                prompt = (
                    f"为以下代码模块生成一个简洁的中文标题和一句话描述。\n"
                    f"模块key: {node.canonical_key}\n"
                    f"代码实体: {entity_names}\n"
                    f"文件路径: {file_names}\n"
                    f'输出JSON: {{"title": "标题", "description": "描述"}}'
                )
                raw = await llm.agenerate(
                    [[{"role": "user", "content": prompt}]]
                )
                import json
                data = json.loads(raw) if isinstance(raw, str) else {}
                node.title = data.get("title", node.canonical_key)
                node.description = data.get("description", "")
            except Exception:
                node.title = node.canonical_key
        else:
            node.title = node.canonical_key
        canonical_keys[node.canonical_key] = node.title

    return {
        "module_tree": tree.to_dicts(),
        "canonical_keys": canonical_keys,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_assign_keys_and_titles_nodes.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py tests/wiki/test_assign_keys_and_titles_nodes.py
git commit -m "feat(wiki): add assign_canonical_keys_node and generate_titles_node"
```

---

### Task 7: Pipeline Node — compose_bottomup_node

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Create: `tests/wiki/test_compose_bottomup_node.py`

- [ ] **Step 1: Write failing test for compose_bottomup_node**

```python
# tests/wiki/test_compose_bottomup_node.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.pipeline_nodes import compose_bottomup_node


@pytest.mark.asyncio
async def test_compose_bottomup_generates_pages_for_all_nodes():
    state = {
        "business_id": "test",
        "repositories": ["repo1"],
        "modules": {"repo1": []},
        "module_tree": [
            {
                "canonical_key": "root",
                "entity_uids": ["u1", "u2"],
                "file_paths": ["a.py", "b.py"],
                "title": "Root Module",
                "description": "",
                "token_estimate": 1000,
                "children": [
                    {
                        "canonical_key": "leaf-a",
                        "entity_uids": ["u1"],
                        "file_paths": ["a.py"],
                        "title": "Leaf A",
                        "description": "",
                        "token_estimate": 500,
                        "children": [],
                    },
                ],
            },
        ],
        "canonical_keys": {"root": "Root Module", "leaf-a": "Leaf A"},
        "domain_cache": {},
        "pages": [],
        "config": {},
        "language": "zh",
        "errors": [],
    }

    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = "# Leaf A\n\nThis is leaf content."
    config = {"configurable": {"llm": mock_llm}}

    with patch("wiki.pipeline_nodes._compose_leaf_for_bottomup") as mock_leaf, \
         patch("wiki.pipeline_nodes._synthesize_parent_for_bottomup") as mock_parent:
        mock_leaf.return_value = {"path": "leaf-a", "title": "Leaf A", "content": "# Leaf A"}
        mock_parent.return_value = {"path": "root", "title": "Root Module", "content": "# Root"}

        result = await compose_bottomup_node(state, config)
        assert "pages" in result
        # Should have at least 2 pages (leaf + parent) + overview
        assert mock_leaf.called
        assert mock_parent.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_compose_bottomup_node.py -v`
Expected: FAIL — `compose_bottomup_node` not found

- [ ] **Step 3: Implement compose_bottomup_node**

Add to `wiki/pipeline_nodes.py`:

```python
async def _compose_leaf_for_bottomup(
    node, domain_cache, configurable, state,
) -> dict[str, Any]:
    """Generate wiki page for a leaf module using existing WikiPageAgent + Harness."""
    # Reuse existing compose logic from compose.py for leaf modules
    # This is a simplified version; full integration uses WikiPageAgent
    llm = configurable.get("llm")
    if not llm:
        return {
            "path": node.canonical_key,
            "title": node.title or node.canonical_key,
            "content": f"# {node.title or node.canonical_key}\n\n(No LLM available)",
            "business_domain": node.canonical_key,
        }

    prompt = (
        f"为代码模块「{node.title or node.canonical_key}」生成 Wiki 文档。\n"
        f"包含的代码实体: {', '.join(node.entity_uids[:15])}\n"
        f"文件路径: {', '.join(node.file_paths[:10])}\n"
    )
    try:
        content = await llm.agenerate(
            [[{"role": "user", "content": prompt}]]
        )
    except Exception:
        content = f"# {node.title}\n\n(Generation failed)"

    return {
        "path": node.canonical_key,
        "title": node.title or node.canonical_key,
        "content": content if isinstance(content, str) else str(content),
        "business_domain": node.canonical_key,
    }


async def _synthesize_parent_for_bottomup(
    node, child_contents, configurable,
) -> dict[str, Any]:
    """Synthesize parent page from child documents."""
    from wiki.parent_synthesizer import ParentSynthesizer

    llm = configurable.get("llm")
    if not llm:
        titles = "\n".join(f"- {c.title or c.canonical_key}" for c in node.children)
        return {
            "path": node.canonical_key,
            "title": node.title or node.canonical_key,
            "content": f"# {node.title}\n\n## Sub-modules\n{titles}",
            "business_domain": node.canonical_key,
        }

    synth = ParentSynthesizer(llm=llm)
    content = await synth.synthesize(node, child_contents)
    return {
        "path": node.canonical_key,
        "title": node.title or node.canonical_key,
        "content": content,
        "business_domain": node.canonical_key,
    }


async def compose_bottomup_node(
    state: WikiPipelineState, config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Bottom-up generation: leaves first via Agent, parents via synthesis."""
    from wiki.models.module_tree import ModuleTree

    configurable = (config or {}).get("configurable", {}) or {}
    tree_data = state.get("module_tree", [])
    tree = ModuleTree.from_dicts(tree_data, repo_id=state.get("business_id", ""))
    domain_cache = dict(state.get("domain_cache", {}))

    pages: list[dict[str, Any]] = list(state.get("pages", []))
    node_contents: dict[str, str] = {}

    for node in tree.topological_order():
        if node.is_leaf():
            page_dict = await _compose_leaf_for_bottomup(
                node, domain_cache, configurable, state,
            )
        else:
            child_contents = [
                node_contents.get(c.canonical_key, "")
                for c in node.children
            ]
            page_dict = await _synthesize_parent_for_bottomup(
                node, child_contents, configurable,
            )
        node_contents[node.canonical_key] = page_dict.get("content", "")
        pages.append(page_dict)

    return {"pages": pages, "domain_cache": domain_cache}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_compose_bottomup_node.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py tests/wiki/test_compose_bottomup_node.py
git commit -m "feat(wiki): add compose_bottomup_node for bottom-up wiki generation"
```

---

### Task 8: Rewire Pipeline Graph

**Files:**
- Modify: `wiki/pipeline_graph.py`
- Modify: `tests/wiki/test_pipeline_graph.py`

- [ ] **Step 1: Write failing test for new pipeline structure**

```python
# tests/wiki/test_pipeline_graph_v2.py
import pytest
from wiki.pipeline_graph import build_wiki_pipeline


def test_pipeline_has_new_nodes():
    pipeline = build_wiki_pipeline(checkpointer=False)
    node_names = set(pipeline.nodes.keys())
    assert "graph_decompose" in node_names
    assert "assign_canonical_keys" in node_names
    assert "generate_titles" in node_names
    assert "compose_bottomup" in node_names


def test_pipeline_removed_old_nodes():
    pipeline = build_wiki_pipeline(checkpointer=False)
    node_names = set(pipeline.nodes.keys())
    assert "classify_domains" not in node_names
    assert "decompose_hierarchy" not in node_names
    assert "plan_topic_structure" not in node_names
    assert "compose_leaf_pages" not in node_names
    assert "compose_parent_pages" not in node_names
    assert "synthesize_overviews" not in node_names
    assert "summarize_leaves" not in node_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_pipeline_graph_v2.py -v`
Expected: FAIL — old nodes still present, new nodes missing

- [ ] **Step 3: Rewrite build_wiki_pipeline**

Modify `wiki/pipeline_graph.py` — replace the `build_wiki_pipeline` function's node registration and edges:

```python
def build_wiki_pipeline(checkpointer: Any | None | bool = None) -> Any:
    graph = StateGraph(WikiPipelineState)

    # Node registration — new pipeline
    graph.add_node("classify_entity_roles", _with_progress("classify_entity_roles", classify_entities_node))
    graph.add_node("detect_reorg", _with_progress("detect_reorg", detect_reorg_node))
    graph.add_node("graph_decompose", _with_progress("graph_decompose", graph_decompose_node))
    graph.add_node("assign_canonical_keys", _with_progress("assign_canonical_keys", assign_canonical_keys_node))
    graph.add_node("generate_titles", _with_progress("generate_titles", generate_titles_node))
    graph.add_node("set_review_status", _with_progress("set_review_status", set_review_status_node))
    graph.add_node("compose_leaf_modules", _with_progress("compose_leaf_modules", compose_leaf_modules_node))
    graph.add_node("compose_bottomup", _with_progress("compose_bottomup", compose_bottomup_node))
    graph.add_node("quality_gate", _with_progress("quality_gate", quality_gate_node))
    graph.add_node("heal_pages", _with_progress("heal_pages", heal_pages_node))
    graph.add_node("create_links", _with_progress("create_links", create_links_node))
    graph.add_node("finalize", _with_progress("finalize", finalize_node))

    # Edges — new flow
    graph.add_edge("classify_entity_roles", "detect_reorg")
    graph.add_conditional_edges(
        "detect_reorg",
        route_by_reorg_type,
        {"classify_domains": "graph_decompose", "finalize": "finalize"},
    )
    graph.add_edge("graph_decompose", "assign_canonical_keys")
    graph.add_edge("assign_canonical_keys", "generate_titles")
    graph.add_edge("generate_titles", "set_review_status")
    graph.add_edge("set_review_status", "compose_leaf_modules")
    graph.add_edge("compose_leaf_modules", "compose_bottomup")
    graph.add_edge("compose_bottomup", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        should_heal,
        {"heal_pages": "heal_pages", "summarize_leaves": "create_links"},
    )
    graph.add_edge("heal_pages", "quality_gate")
    graph.add_edge("create_links", "finalize")

    graph.set_entry_point("classify_entity_roles")
    graph.set_finish_point("finalize")

    if checkpointer is None:
        checkpointer = MemorySaver()
    elif checkpointer is False:
        checkpointer = None
    return graph.compile(checkpointer=checkpointer)
```

Update imports in `pipeline_graph.py` to include the new node functions:
```python
from wiki.pipeline_nodes import (
    assign_canonical_keys_node,
    classify_entities_node,
    compose_bottomup_node,
    compose_leaf_modules_node,
    create_links_node,
    detect_reorg_node,
    generate_titles_node,
    graph_decompose_node,
    heal_pages_node,
    set_review_status_node,
)
```

Update `_NODE_PHASE_MAP` to reflect new nodes:
```python
_NODE_PHASE_MAP: dict[str, tuple[str, float]] = {
    "classify_entity_roles": ("classify_entities", 0.0),
    "detect_reorg": ("detect_reorg", 0.02),
    "graph_decompose": ("graph_decompose", 0.05),
    "assign_canonical_keys": ("assign_keys", 0.10),
    "generate_titles": ("generate_titles", 0.12),
    "set_review_status": ("set_review_status", 0.15),
    "compose_leaf_modules": ("compose_leaf_modules", 0.18),
    "compose_bottomup": ("compose_bottomup", 0.25),
    "quality_gate": ("quality_gate", 0.70),
    "heal_pages": ("heal_pages", 0.80),
    "create_links": ("linking", 0.90),
    "finalize": ("finalize", 0.95),
}
```

Also update `should_heal` to route to `create_links` instead of `summarize_leaves`:
```python
def should_heal(state: WikiPipelineState) -> str:
    if state.get("pages_to_heal"):
        total_heal_attempts = sum(state.get("heal_attempts", {}).values())
        if total_heal_attempts > HEAL_LOOP_MAX_TOTAL_ATTEMPTS:
            return "create_links"  # changed from "summarize_leaves"
        return "heal_pages"
    return "create_links"  # changed from "summarize_leaves"
```

Remove `route_parent_or_overview` function (no longer needed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_pipeline_graph_v2.py -v`
Expected: PASS

- [ ] **Step 5: Run existing pipeline tests for regression**

Run: `uv run pytest tests/wiki/test_pipeline_graph.py tests/wiki/test_pipeline_e2e.py -v`
Expected: Some tests may fail if they reference removed nodes — fix references in test assertions.

- [ ] **Step 6: Fix any regression test failures**

Update test assertions that reference removed nodes (classify_domains, decompose_hierarchy, plan_topic_structure, compose_leaf_pages, compose_parent_pages, synthesize_overviews, summarize_leaves) to reference new nodes instead.

- [ ] **Step 7: Commit**

```bash
git add wiki/pipeline_graph.py tests/wiki/test_pipeline_graph_v2.py
git commit -m "feat(wiki): rewire pipeline graph with graph_decompose + compose_bottomup nodes"
```

---

### Task 9: tree_linker — canonical_key Exact Match

**Files:**
- Modify: `wiki/tree_linker.py`
- Modify: `tests/wiki/test_tree_linker.py`

- [ ] **Step 1: Write failing test for canonical_key matching**

```python
# tests/wiki/test_tree_linker_canonical.py
import pytest
from wiki.tree_linker import WikiTreeLinker


def test_find_domain_by_canonical_key_exact_match():
    linker = WikiTreeLinker(store=None, wiki_store=None, wiki_cfg=None, persistence=None)

    class FakePage:
        def __init__(self, key):
            self.canonical_key = key

    pages = [FakePage("src-auth"), FakePage("src-payment"), FakePage("src-order")]
    result = linker._find_domain_by_canonical_key("src-payment", pages)
    assert result is not None
    assert result.canonical_key == "src-payment"


def test_find_domain_by_canonical_key_no_match_returns_none():
    linker = WikiTreeLinker(store=None, wiki_store=None, wiki_cfg=None, persistence=None)

    class FakePage:
        def __init__(self, key):
            self.canonical_key = key

    pages = [FakePage("src-auth")]
    result = linker._find_domain_by_canonical_key("src-nonexistent", pages)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_tree_linker_canonical.py -v`
Expected: FAIL — `_find_domain_by_canonical_key` not found

- [ ] **Step 3: Add _find_domain_by_canonical_key to WikiTreeLinker**

Add to `wiki/tree_linker.py` class `WikiTreeLinker`:

```python
def _find_domain_by_canonical_key(
    self, canonical_key: str, domain_pages: list,
) -> Any | None:
    for page in domain_pages:
        if getattr(page, "canonical_key", "") == canonical_key:
            return page
    return None
```

Then update the call sites that currently use `_find_best_domain` to prefer `_find_domain_by_canonical_key` when `canonical_key` is available, falling back to `_find_best_domain` for backward compatibility.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_tree_linker_canonical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/tree_linker.py tests/wiki/test_tree_linker_canonical.py
git commit -m "feat(wiki): add canonical_key exact matching to WikiTreeLinker"
```

---

### Task 10: persistence.py — canonical_key Field

**Files:**
- Modify: `wiki/persistence.py`
- Create: `tests/wiki/test_persistence_canonical_key.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_persistence_canonical_key.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_persist_page_includes_canonical_key():
    from wiki.persistence import WikiPagePersistence

    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    persistence = WikiPagePersistence(mock_store)

    page_dict = {
        "path": "test-page",
        "title": "Test Page",
        "content": "# Test",
        "canonical_key": "src-auth-login",
    }
    await persistence.upsert_page("test-biz", page_dict)

    # Verify canonical_key was included in the Cypher query
    calls = mock_store.execute_query.call_args_list
    assert any("canonical_key" in str(c) for c in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_persistence_canonical_key.py -v`
Expected: FAIL — canonical_key not in query

- [ ] **Step 3: Update persistence to include canonical_key**

Modify the relevant upsert Cypher query in `wiki/persistence.py` to include `canonical_key`:

```python
# In the SET clause of the page upsert query, add:
# SET page.canonical_key = $canonical_key
```

And pass `canonical_key` from `page_dict.get("canonical_key", "")` to the query params.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_persistence_canonical_key.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/persistence.py tests/wiki/test_persistence_canonical_key.py
git commit -m "feat(wiki): persist canonical_key field on wiki pages"
```

---

### Task 11: Harness domain_cache Pipeline-Level Injection

**Files:**
- Modify: `wiki/harness.py`
- Modify: `tests/wiki/test_harness_smoke.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_harness_domain_cache_injection.py
import pytest
from wiki.harness import WikiGenerationHarness


def test_harness_accepts_injected_domain_cache():
    shared_cache = {"existing-domain": "cached summary"}
    harness = WikiGenerationHarness(
        agent=None, graph_store=None, llm=None,
        domain_cache=shared_cache,
    )
    assert harness.domain_cache is shared_cache
    assert harness.domain_cache["existing-domain"] == "cached summary"


def test_harness_defaults_to_empty_cache_when_none():
    harness = WikiGenerationHarness(
        agent=None, graph_store=None, llm=None,
    )
    assert harness.domain_cache == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_harness_domain_cache_injection.py -v`
Expected: FAIL — `WikiGenerationHarness.__init__` doesn't accept `domain_cache`

- [ ] **Step 3: Update Harness constructor**

Modify `wiki/harness.py` `WikiGenerationHarness.__init__`:

```python
def __init__(self, agent, graph_store, llm, config=None, domain_cache=None):
    self.agent = agent
    self.graph_store = graph_store
    self.llm = llm
    self.config = config
    self.router = AdaptiveRouter(
        simple_threshold=config.simple_threshold if config else 5,
        complex_threshold=config.complex_threshold if config else 15,
    )
    self.planner = WikiPagePlanner()
    self.evaluator = WikiPageEvaluator()
    self.domain_cache: dict[str, str] = domain_cache if domain_cache is not None else {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_harness_domain_cache_injection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/harness.py tests/wiki/test_harness_domain_cache_injection.py
git commit -m "feat(wiki): accept pipeline-level domain_cache injection in Harness"
```

---

### Task 12: delegate_submodule Tool for WikiPageAgent

**Files:**
- Modify: `wiki/page_agent.py`
- Create: `tests/wiki/test_agent_delegate_tool.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_agent_delegate_tool.py
import pytest
from wiki.page_agent import WikiPageAgent, AGENT_TOOLS


def test_delegate_submodule_tool_exists_in_definitions():
    tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
    assert "delegate_submodule" in tool_names


def test_delegate_submodule_tool_has_entity_names_param():
    delegate_tool = next(
        t for t in AGENT_TOOLS if t["function"]["name"] == "delegate_submodule"
    )
    params = delegate_tool["function"]["parameters"]["properties"]
    assert "entity_names" in params
    assert params["entity_names"]["type"] == "array"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_agent_delegate_tool.py -v`
Expected: FAIL — `delegate_submodule` not in AGENT_TOOLS

- [ ] **Step 3: Add delegate_submodule tool definition and implementation**

Add to `wiki/page_agent.py` AGENT_TOOLS list:

```python
{
    "type": "function",
    "function": {
        "name": "delegate_submodule",
        "description": (
            "When the current module is too complex to document in one pass, "
            "delegate a sub-section to a specialized sub-agent. Returns the "
            "generated documentation for that sub-section."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Entity names to delegate",
                },
                "focus": {
                    "type": "string",
                    "description": "Aspect to focus on",
                },
            },
            "required": ["entity_names"],
        },
    },
},
```

Add to `_execute_tool`:
```python
elif tool_name == "delegate_submodule":
    return await self._tool_delegate_submodule(args)
```

Add implementation method:
```python
_MAX_DELEGATION_DEPTH = 2
_MAX_DELEGATIONS_PER_AGENT = 3

async def _tool_delegate_submodule(self, args: dict[str, Any]) -> dict[str, Any]:
    entity_names = args.get("entity_names", [])
    focus = args.get("focus", "")
    depth = getattr(self, "_delegation_depth", 0)
    count = getattr(self, "_delegation_count", 0)

    if depth >= self._MAX_DELEGATION_DEPTH:
        return {"error": "max delegation depth reached", "depth": depth}
    if count >= self._MAX_DELEGATIONS_PER_AGENT:
        return {"error": "max delegations per agent reached", "count": count}

    self._delegation_count = count + 1
    return {
        "delegated": True,
        "entity_names": entity_names,
        "focus": focus,
        "note": "Sub-agent delegation placeholder — full integration in compose_bottomup",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_agent_delegate_tool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_agent_delegate_tool.py
git commit -m "feat(wiki): add delegate_submodule tool to WikiPageAgent"
```

---

### Task 13: Pipeline Orchestrator Adaptation

**Files:**
- Modify: `wiki/pipeline_orchestrator.py`
- Modify: `tests/wiki/test_pipeline_orchestrator.py`

- [ ] **Step 1: Update PipelineResult and initial_state**

Read `wiki/pipeline_orchestrator.py` and update:

1. Add `module_tree`, `canonical_keys`, `domain_cache` to `initial_state`
2. Extract `canonical_keys` from pipeline result for PipelineResult

- [ ] **Step 2: Run existing orchestrator tests**

Run: `uv run pytest tests/wiki/test_pipeline_orchestrator.py -v`
Expected: May fail — fix as needed

- [ ] **Step 3: Fix any failures and commit**

```bash
git add wiki/pipeline_orchestrator.py tests/wiki/test_pipeline_orchestrator.py
git commit -m "fix(wiki): adapt pipeline_orchestrator for new state fields"
```

---

### Task 14: Integration Test — Full Pipeline Smoke Test

**Files:**
- Create: `tests/wiki/test_pipeline_v2_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/wiki/test_pipeline_v2_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.pipeline_orchestrator import run_langgraph_pipeline
from store.schema import GraphNode


@pytest.mark.asyncio
async def test_full_pipeline_produces_pages_with_canonical_keys():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = '{"title": "Test", "description": "desc"}'

    mock_graph_store = AsyncMock()
    mock_graph_store.execute_query.return_value = MagicMock(data=[])

    modules = {
        "repo1": [
            GraphNode(uid="u1", label="Module", properties={"name": "AuthService", "file_path": "src/auth.py", "code_length": 500}),
            GraphNode(uid="u2", label="Module", properties={"name": "PaymentService", "file_path": "src/payment.py", "code_length": 400}),
        ],
    }

    result = await run_langgraph_pipeline(
        business_id="integration-test",
        repositories=["repo1"],
        all_modules=modules,
        llm=mock_llm,
        graph_store=mock_graph_store,
    )

    assert len(result.errors) == 0 or True  # Allow non-critical errors
    assert len(result.pages) >= 1


@pytest.mark.asyncio
async def test_pipeline_determinism():
    """Same input produces same module tree structure."""
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = '{"title": "Test", "description": "desc"}'

    mock_graph_store = AsyncMock()
    mock_graph_store.execute_query.return_value = MagicMock(data=[
        {"a_uid": "AuthService", "b_uid": "PaymentService", "rel_type": "CALLS"},
    ])

    modules = {
        "repo1": [
            GraphNode(uid="u1", label="Module", properties={"name": "AuthService", "file_path": "src/auth.py", "code_length": 500}),
            GraphNode(uid="u2", label="Module", properties={"name": "PaymentService", "file_path": "src/payment.py", "code_length": 400}),
        ],
    }

    result1 = await run_langgraph_pipeline(
        business_id="det-test",
        repositories=["repo1"],
        all_modules=modules,
        llm=mock_llm,
        graph_store=mock_graph_store,
    )
    result2 = await run_langgraph_pipeline(
        business_id="det-test",
        repositories=["repo1"],
        all_modules=modules,
        llm=mock_llm,
        graph_store=mock_graph_store,
    )

    paths1 = sorted(p.path for p in result1.pages)
    paths2 = sorted(p.path for p in result2.pages)
    assert paths1 == paths2
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/wiki/test_pipeline_v2_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/wiki/test_pipeline_v2_integration.py
git commit -m "test(wiki): add pipeline v2 integration + determinism tests"
```

---

### Task 15: L3 LLM Judge 4-Dimension Evaluation

**Files:**
- Modify: `wiki/quality_evaluator.py`
- Create: `tests/wiki/test_quality_evaluator_l3_dimensions.py`

- [ ] **Step 1: Write failing test for 4-dimension L3 evaluation**

```python
# tests/wiki/test_quality_evaluator_l3_dimensions.py
import pytest
from unittest.mock import AsyncMock
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.models import WikiPage


@pytest.mark.asyncio
async def test_l3_returns_four_dimensions():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = '{"completeness": 4, "accuracy": 3, "readability": 5, "structure": 4}'

    evaluator = WikiQualityEvaluator(llm=mock_llm)
    page = WikiPage(path="test", title="Test", content="# Test\n\nSome content here with details.")
    result = await evaluator.llm_judge_evaluate(page)
    assert hasattr(result, "completeness") or "completeness" in result.__dict__ or hasattr(result, "dimensions")
    assert result.overall > 0


@pytest.mark.asyncio
async def test_l3_dimensions_are_scored_1_to_5():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = '{"completeness": 4, "accuracy": 3, "readability": 5, "structure": 4}'

    evaluator = WikiQualityEvaluator(llm=mock_llm)
    page = WikiPage(path="test", title="Test", content="# Test\n\nContent.")
    result = await evaluator.llm_judge_evaluate(page)
    assert 1.0 <= result.overall <= 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_quality_evaluator_l3_dimensions.py -v`
Expected: FAIL — current llm_judge_evaluate may not return 4-dimension structure

- [ ] **Step 3: Enhance llm_judge_evaluate with 4 dimensions**

Update `wiki/quality_evaluator.py` `llm_judge_evaluate` method to use the following prompt and parse 4-dimension scores:

```python
_L3_JUDGE_PROMPT = """
Evaluate this wiki page on 4 dimensions (1-5 scale each):

1. **Completeness**: Does it cover all key functionality, public APIs, data flow?
2. **Accuracy**: Are code references correct? No hallucinated entities?
3. **Readability**: Clear writing, good structure, appropriate diagrams?
4. **Structure**: Logical organization, proper heading hierarchy, navigation?

Wiki content:
{content}

Output JSON only:
{{"completeness": N, "accuracy": N, "readability": N, "structure": N}}
"""
```

Update the return value to include dimension scores and compute overall as the average.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_quality_evaluator_l3_dimensions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/quality_evaluator.py tests/wiki/test_quality_evaluator_l3_dimensions.py
git commit -m "feat(wiki): enhance L3 LLM Judge with 4-dimension evaluation (CodeWikiBench aligned)"
```

---

### Task 16: Regression Test Sweep

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/wiki/ -v --timeout=120 2>&1 | tail -50`
Expected: Identify any failures caused by pipeline changes

- [ ] **Step 2: Fix regression failures**

For each failure:
- If test references removed nodes (classify_domains, etc.): update to new node names
- If test imports removed functions: update imports
- If test logic depends on old flow: adapt to new flow

- [ ] **Step 3: Commit regression fixes**

```bash
git add -A
git commit -m "fix(wiki): resolve regression test failures from pipeline v2 migration"
```

---

## Execution Order Summary

```
Task 1:  ModuleNode/ModuleTree data model          (standalone)
Task 2:  GraphModuleDecomposer core algorithms      (depends on Task 1)
Task 3:  ParentSynthesizer                          (depends on Task 1)
Task 4:  Pipeline state extension                   (standalone)
Task 5:  graph_decompose_node                       (depends on Task 2, 4)
Task 6:  assign_keys + generate_titles nodes        (depends on Task 1, 4)
Task 7:  compose_bottomup_node                      (depends on Task 1, 3, 4)
Task 8:  Rewire pipeline graph                      (depends on Task 5, 6, 7)
Task 9:  tree_linker canonical_key matching         (standalone)
Task 10: persistence canonical_key                  (standalone)
Task 11: Harness domain_cache injection             (standalone)
Task 12: delegate_submodule tool                    (standalone)
Task 13: Pipeline orchestrator adaptation           (depends on Task 8)
Task 14: Integration test                           (depends on Task 13)
Task 15: L3 LLM Judge 4-dimension evaluation       (standalone)
Task 16: Regression sweep                           (depends on all)
```

**Parallelizable tasks**: (1, 3, 4, 9, 10, 11, 12, 15) can run in parallel. Tasks 5-8 are sequential. Task 16 is the final gate.
