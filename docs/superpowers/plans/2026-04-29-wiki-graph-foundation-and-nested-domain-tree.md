# Wiki Graph Foundation & Nested Domain Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Fix cross-file graph edge resolution, enhance Wiki page quality through entity filtering and comment injection, implement LLM-driven nested business domain tree classification, and improve parent/overview page composition.

**Architecture:** Four-layer dependency-driven approach: Layer 0 fixes the graph foundation (cross-file CALLS/INHERITS/IMPLEMENTS), Layer 1 adds quality enhancements (entity filtering, delegation fixes, resume), Layer 2 builds the nested domain tree (dependency graph + LLM decomposition + recursive tree), Layer 3 polishes overview pages and glossary alignment.

**Tech Stack:** Python 3.11+, tree-sitter, FalkorDB (Cypher), LLM (via LLMPort abstraction), pytest, pydantic

**Spec:** `docs/superpowers/specs/2026-04-29-wiki-graph-foundation-and-nested-domain-tree-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `wiki/entity_filter.py` | WikiEntityFilter: classify entities as FULL_PAGE / STANDARD_PAGE / MERGE_TO_PARENT; LargeClassStrategy for method grouping; HubNodeDetector |
| `wiki/dependency_graph.py` | ModuleDependencyGraph: build module-level dependency graph from FalkorDB; identify entry points; ModuleReprBuilder for token-budget-aware module descriptions |
| `tests/test_cross_file_resolution.py` | Integration tests for two-phase graph building |
| `tests/wiki/test_entity_filter.py` | Unit tests for WikiEntityFilter and LargeClassStrategy |
| `tests/wiki/test_dependency_graph.py` | Unit tests for ModuleDependencyGraph and entry point identification |
| `tests/wiki/test_nested_domain_tree.py` | Integration tests for LLM hierarchical decomposition and tree construction |

### Modified Files

| File | Changes |
|------|---------|
| `indexer/tree_sitter_parser.py` | Add `receiver_expr` to ParsedCall; add `symbols` to ParsedImport (rename from `names`); JS/TS arrow function extraction |
| `indexer/code_graph_builder.py` | Add `_build_global_symbol_table`, `_resolve_cross_file_edges`, `_build_import_map`; new `iter_directory_with_cross_file()` method wrapping two-phase build |
| `store/indexer_store.py` | Add `upsert_edges_batch` for batch edge insertion |
| `store/falkordb_store.py` | Add `find_edges_between` Cypher query; add module-level CALLS aggregation Cypher |
| `api/models/wiki_models.py` | Change `BusinessWikiGenerateBody.mode` default from `"structure"` to `"full"` |
| `wiki/service.py` | Call `inject_wikilinks()` in compose pipeline; fix delegation edges; add depth ordering + just_generated cache; TD-3 entity_uid fallback; resume; recursive `_link_pages_to_nested_tree` |
| `wiki/structure_planner.py` | Integrate WikiEntityFilter before creating child page nodes |
| `wiki/composer.py` | Wire CommentFilter into `_entity_digest`; enhance `_PARENT_SYSTEM_PROMPT` to V2 with inter-child edges |
| `wiki/cross_repo_domain_planner.py` | Refactor to use `HierarchicalDecomposer` with dependency graph input |
| `wiki/business_domain_planner.py` | Reuse `HierarchicalDecomposer` for single-repo scope |
| `wiki/domain_overview_composer.py` | Add nested sub-domain navigation, entry point list, module collaboration diagram |
| `store/wiki_tree_store.py` | Multi-level HAS_CHILD traversal Cypher |
| `indexer/comment_filter.py` | Complete `CommentTier` model |
| `wiki/models.py` | Add `EntityStrategy` enum |

---

## Layer 0: Graph Foundation + Quick Fix

> **⏱ Estimated: 7.5 days**
> **🔍 CODE REVIEW CHECKPOINT: Layer 0 完成后进行 Code Review，重点审查跨文件边解析正确性、内存安全性、向后兼容性**

### Task 1: ParsedCall Extension — Add `receiver_expr`

**Files:**
- Modify: `indexer/tree_sitter_parser.py:82-86`
- Test: `tests/test_tree_sitter_parser.py`

- [x] **Step 1: Write failing test for `receiver_expr` in Java method invocation**

```python
# tests/test_tree_sitter_parser.py — append to existing test class

class TestParsedCallReceiverExpr:
    def test_java_method_invocation_has_receiver(self, java_parser):
        code = (
            "public class Controller {\n"
            "    private UserService userService;\n"
            "    public void create() {\n"
            "        userService.save();\n"
            "    }\n"
            "}\n"
        )
        result = java_parser.parse("Controller.java", code)
        calls = [c for c in result.calls if c.callee_name == "save"]
        assert len(calls) == 1
        assert calls[0].receiver_expr == "userService"

    def test_python_method_invocation_has_receiver(self, python_parser):
        code = (
            "class Controller:\n"
            "    def create(self):\n"
            "        self.service.save()\n"
        )
        result = python_parser.parse("controller.py", code)
        calls = [c for c in result.calls if c.callee_name == "save"]
        assert len(calls) == 1
        assert calls[0].receiver_expr == "self.service"

    def test_plain_function_call_has_empty_receiver(self, python_parser):
        code = "def foo():\n    bar()\n"
        result = python_parser.parse("test.py", code)
        calls = [c for c in result.calls if c.callee_name == "bar"]
        assert len(calls) == 1
        assert calls[0].receiver_expr == ""
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py::TestParsedCallReceiverExpr -v`
Expected: FAIL — `ParsedCall` has no `receiver_expr` attribute

- [x] **Step 3: Add `receiver_expr` field to `ParsedCall` dataclass**

In `indexer/tree_sitter_parser.py`, modify:

```python
@dataclass
class ParsedCall:
    caller_name: str
    callee_name: str
    file: str
    line: int
    receiver_expr: str = ""
```

- [x] **Step 4: Update tree-sitter call extraction to capture receiver expression**

In `indexer/tree_sitter_parser.py`, find the method that creates `ParsedCall` instances (the call extraction logic in `_extract_calls` or equivalent). For Java `method_invocation` nodes, capture the `object` child. For Python `call` nodes with `attribute` access, capture the `object` chain.

Java pattern — when extracting calls from `method_invocation`:
```python
# For Java: node type == "method_invocation"
#   child(0) = object/receiver expression
#   child(1) = "."
#   child(2) = name (identifier)
if node.type == "method_invocation":
    name_node = node.child_by_field_name("name")
    object_node = node.child_by_field_name("object")
    callee_name = name_node.text.decode() if name_node else ""
    receiver_expr = object_node.text.decode() if object_node else ""
```

Python pattern — when extracting calls from `call` with `attribute`:
```python
# For Python: node.children[0].type == "attribute"
#   attribute.child_by_field_name("object") = receiver
#   attribute.child_by_field_name("attribute") = method name
func_node = call_node.children[0]
if func_node.type == "attribute":
    obj = func_node.child_by_field_name("object")
    attr = func_node.child_by_field_name("attribute")
    callee_name = attr.text.decode() if attr else ""
    receiver_expr = obj.text.decode() if obj else ""
```

Create `ParsedCall` with `receiver_expr=receiver_expr`.

- [x] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py::TestParsedCallReceiverExpr -v`
Expected: PASS

- [x] **Step 6: Run full parser test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py -v`
Expected: All tests PASS

- [x] **Step 7: Commit**

```bash
git add indexer/tree_sitter_parser.py tests/test_tree_sitter_parser.py
git commit -m "feat(parser): add receiver_expr to ParsedCall for cross-file call resolution"
```

---

### Task 2: ParsedImport Extension — Add `symbols` field

**Files:**
- Modify: `indexer/tree_sitter_parser.py:58-65`
- Test: `tests/test_tree_sitter_parser.py`

- [x] **Step 1: Write failing test for `symbols` extraction**

```python
class TestParsedImportSymbols:
    def test_python_from_import_extracts_symbols(self, python_parser):
        code = "from pkg.module import UserService, OrderDTO\n"
        result = python_parser.parse("test.py", code)
        imp = [i for i in result.imports if i.module == "pkg.module"]
        assert len(imp) == 1
        assert set(imp[0].symbols) == {"UserService", "OrderDTO"}

    def test_java_import_extracts_symbol(self, java_parser):
        code = "import com.example.UserService;\n\npublic class A {}\n"
        result = java_parser.parse("A.java", code)
        imp = [i for i in result.imports if "UserService" in i.module]
        assert len(imp) >= 1
        assert "UserService" in imp[0].symbols

    def test_js_named_import_extracts_symbols(self, js_parser):
        code = "import { UserService, OrderDTO } from './module';\n"
        result = js_parser.parse("test.js", code)
        imp = [i for i in result.imports if i.module == "./module"]
        assert len(imp) == 1
        assert set(imp[0].symbols) >= {"UserService", "OrderDTO"}
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py::TestParsedImportSymbols -v`
Expected: FAIL — `ParsedImport` has no `symbols` attribute

- [x] **Step 3: Add `symbols` field to `ParsedImport`**

```python
@dataclass
class ParsedImport:
    module: str
    names: list[str]       # kept for backward compat
    file: str
    line: int
    language: str
    alias: str = ""
    symbols: list[str] = field(default_factory=list)
```

- [x] **Step 4: Populate `symbols` during import extraction**

In the import extraction methods:
- **Python** `from X import A, B`: set `symbols = ["A", "B"]` (same as `names`)
- **Java** `import com.example.UserService`: set `symbols = ["UserService"]` (last segment of module path)
- **JS/TS** `import { A, B } from './module'`: set `symbols = ["A", "B"]` from named imports

```python
# After building ParsedImport, backfill symbols from names if not set:
if not parsed_import.symbols and parsed_import.names:
    parsed_import.symbols = list(parsed_import.names)
```

For Java single-class imports, extract the simple class name:
```python
if language == "java" and not parsed_import.symbols:
    simple_name = parsed_import.module.rsplit(".", 1)[-1]
    if simple_name and simple_name[0].isupper():
        parsed_import.symbols = [simple_name]
```

- [x] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py::TestParsedImportSymbols -v`
Expected: PASS

- [x] **Step 6: Run full parser test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py -v`
Expected: All tests PASS

- [x] **Step 7: Commit**

```bash
git add indexer/tree_sitter_parser.py tests/test_tree_sitter_parser.py
git commit -m "feat(parser): add symbols field to ParsedImport for cross-file resolution"
```

---

### Task 3: JS/TS Arrow Function Extraction

**Files:**
- Modify: `indexer/tree_sitter_parser.py`
- Test: `tests/test_tree_sitter_parser.py`

- [x] **Step 1: Write failing test for top-level arrow function**

```python
class TestArrowFunctionExtraction:
    def test_module_level_arrow_function(self, ts_parser):
        code = "const fetchUser = async (id: string) => {\n  return db.find(id);\n};\n"
        result = ts_parser.parse("api.ts", code)
        funcs = [f for f in result.functions if f.name == "fetchUser"]
        assert len(funcs) == 1
        assert funcs[0].start_line == 1

    def test_exported_arrow_function(self, ts_parser):
        code = "export const handler = (req: Request) => {\n  return 'ok';\n};\n"
        result = ts_parser.parse("handler.ts", code)
        funcs = [f for f in result.functions if f.name == "handler"]
        assert len(funcs) == 1

    def test_nested_callback_not_extracted(self, ts_parser):
        code = (
            "function main() {\n"
            "  const items = list.map((x) => x + 1);\n"
            "}\n"
        )
        result = ts_parser.parse("test.ts", code)
        func_names = [f.name for f in result.functions]
        assert "main" in func_names
        # The callback `(x) => x + 1` should NOT be extracted as a top-level function
        assert len([f for f in result.functions if f.name not in ("main",)]) == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py::TestArrowFunctionExtraction -v`
Expected: FAIL — arrow functions not detected

- [x] **Step 3: Add arrow function tree-sitter queries for JS/TS**

In the JS/TS parsing section, add queries for `lexical_declaration > variable_declarator > arrow_function` where the parent chain goes to `program` (top-level).

```python
# Query pattern for JS/TS:
_ARROW_FUNC_QUERY = """
(lexical_declaration
  (variable_declarator
    name: (identifier) @func.name
    value: (arrow_function) @func.def))
"""

_EXPORTED_ARROW_FUNC_QUERY = """
(export_statement
  (lexical_declaration
    (variable_declarator
      name: (identifier) @func.name
      value: (arrow_function) @func.def)))
"""
```

When processing matches, verify the `lexical_declaration` node's parent is `program` or its parent is `export_statement` whose parent is `program`:

```python
def _is_module_level(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type == "program":
        return True
    if parent.type == "export_statement" and parent.parent and parent.parent.type == "program":
        return True
    return False
```

Build `ParsedFunction` from matched arrow functions (extract name, start/end lines, signature, etc.).

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_tree_sitter_parser.py::TestArrowFunctionExtraction -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add indexer/tree_sitter_parser.py tests/test_tree_sitter_parser.py
git commit -m "feat(parser): extract module-level JS/TS arrow functions as Function entities"
```

---

### Task 4: Global Symbol Table Builder

**Files:**
- Modify: `indexer/code_graph_builder.py`
- Test: `tests/test_code_graph_builder.py`

- [x] **Step 1: Write failing test for global symbol table construction**

```python
class TestGlobalSymbolTable:
    def test_builds_per_language_table(self, builder: CodeGraphBuilder):
        nodes_file1, _ = builder.build_from_file(
            "com/example/UserService.java",
            content="public class UserService {\n    public void save() {}\n}\n",
        )
        nodes_file2, _ = builder.build_from_file(
            "com/example/UserController.java",
            content="public class UserController {\n    public void create() {}\n}\n",
        )
        all_nodes = nodes_file1 + nodes_file2
        table = builder._build_global_symbol_table(all_nodes)

        assert "java" in table
        java_table = table["java"]
        assert any("UserService" in k for k in java_table)
        assert any("UserController" in k for k in java_table)

    def test_fqn_takes_precedence_over_simple_name(self, builder: CodeGraphBuilder):
        nodes, _ = builder.build_from_file(
            "com/example/UserService.java",
            content="public class UserService {}\n",
        )
        table = builder._build_global_symbol_table(nodes)
        java_table = table.get("java", {})
        class_nodes = [n for n in nodes if n.label == NodeLabel.CLASS]
        assert len(class_nodes) == 1
        uid = class_nodes[0].uid
        # FQN entry should point to the class
        fqn_key = [k for k in java_table if "UserService" in k]
        assert len(fqn_key) >= 1
        assert java_table[fqn_key[0]] == uid
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_code_graph_builder.py::TestGlobalSymbolTable -v`
Expected: FAIL — `_build_global_symbol_table` method does not exist

- [x] **Step 3: Implement `_build_global_symbol_table` in CodeGraphBuilder**

```python
def _build_global_symbol_table(
    self, all_nodes: list[GraphNode],
) -> dict[str, dict[str, str]]:
    """Build per-language {fqn_or_name: node_uid} for all Class and Function nodes."""
    tables: dict[str, dict[str, str]] = {}
    for node in all_nodes:
        lang = node.properties.get("language", "")
        if not lang:
            continue
        if node.label not in (NodeLabel.CLASS, NodeLabel.FUNCTION):
            continue
        fqn = node.properties.get("fqn", "")
        if fqn:
            tables.setdefault(lang, {})[fqn] = node.uid
        name = node.properties.get("name", "")
        if name:
            tables.setdefault(lang, {}).setdefault(name, node.uid)
    return tables
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_code_graph_builder.py::TestGlobalSymbolTable -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add indexer/code_graph_builder.py tests/test_code_graph_builder.py
git commit -m "feat(graph): add per-language global symbol table builder for cross-file resolution"
```

---

### Task 5: Import Map Builder + Cross-File Edge Resolution

**Files:**
- Modify: `indexer/code_graph_builder.py`
- Test: `tests/test_cross_file_resolution.py` (new file)

- [x] **Step 1: Write failing integration test for cross-file CALLS**

```python
"""tests/test_cross_file_resolution.py — Integration tests for two-phase graph building."""
import pytest
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.tree_sitter_parser import TreeSitterParser
from store.schema import EdgeType, NodeLabel


@pytest.fixture
def java_builder():
    parser = TreeSitterParser(supported_languages=["java"])
    return CodeGraphBuilder(parser=parser, file_extensions={"java": [".java"]})


class TestCrossFileCallsJava:
    def test_controller_to_service_call_edge(self, java_builder: CodeGraphBuilder):
        """UserController.create() calls userService.save() → CALLS edge should exist."""
        service_code = (
            "package com.example;\n"
            "public class UserService {\n"
            "    public void save() {}\n"
            "}\n"
        )
        controller_code = (
            "package com.example;\n"
            "import com.example.UserService;\n"
            "public class UserController {\n"
            "    private UserService userService;\n"
            "    public void create() {\n"
            "        userService.save();\n"
            "    }\n"
            "}\n"
        )
        files = {
            "com/example/UserService.java": service_code,
            "com/example/UserController.java": controller_code,
        }
        all_nodes, all_edges = java_builder.build_from_files(files)

        cross_file_calls = [
            e for e in all_edges
            if e.edge_type == EdgeType.CALLS
            and e.properties.get("cross_file") is True
        ]
        assert len(cross_file_calls) >= 1, "Expected at least one cross-file CALLS edge"

        source_uids = {e.source_uid for e in cross_file_calls}
        target_uids = {e.target_uid for e in cross_file_calls}
        create_func = next(
            n for n in all_nodes
            if n.label == NodeLabel.FUNCTION and n.properties.get("name") == "create"
        )
        save_func = next(
            n for n in all_nodes
            if n.label == NodeLabel.FUNCTION and n.properties.get("name") == "save"
        )
        assert create_func.uid in source_uids
        assert save_func.uid in target_uids


class TestCrossFileInherits:
    def test_cross_file_inherits_edge(self, java_builder: CodeGraphBuilder):
        base_code = "package com.example;\npublic class BaseService {}\n"
        child_code = (
            "package com.example;\n"
            "import com.example.BaseService;\n"
            "public class UserService extends BaseService {}\n"
        )
        files = {
            "com/example/BaseService.java": base_code,
            "com/example/UserService.java": child_code,
        }
        all_nodes, all_edges = java_builder.build_from_files(files)

        inherits = [e for e in all_edges if e.edge_type == EdgeType.INHERITS]
        assert len(inherits) >= 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_cross_file_resolution.py -v`
Expected: FAIL — `build_from_files` does not exist on `CodeGraphBuilder`

- [x] **Step 3: Implement `_build_import_map`**

```python
def _build_import_map(
    self,
    imports: list,  # list[ParsedImport]
    file_path: str,
    symbol_table: dict[str, str],
) -> dict[str, str]:
    """Map imported symbol names to their uid for this file's scope."""
    result: dict[str, str] = {}
    for imp in imports:
        symbols = getattr(imp, "symbols", []) or imp.names
        for sym in symbols:
            candidate_fqn = f"{imp.module}.{sym}" if imp.module else sym
            if candidate_fqn in symbol_table:
                result[sym] = symbol_table[candidate_fqn]
            elif sym in symbol_table:
                result[sym] = symbol_table[sym]
    return result
```

- [x] **Step 4: Implement `_resolve_cross_file_edges`**

```python
from dataclasses import dataclass

@dataclass
class _CrossFileData:
    file_path: str
    language: str
    imports: list  # list[ParsedImport]
    unresolved_calls: list  # list of (caller_uid, callee_name, receiver_expr, line)
    unresolved_inherits: list  # list of (child_uid, base_name)
    unresolved_implements: list  # list of (child_uid, iface_name)


def _resolve_cross_file_edges(
    self,
    per_file_data: list[_CrossFileData],
    symbol_tables: dict[str, dict[str, str]],
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for data in per_file_data:
        lang = data.language
        table = symbol_tables.get(lang, {})
        import_map = self._build_import_map(data.imports, data.file_path, table)

        for caller_uid, callee_name, receiver_expr, line in data.unresolved_calls:
            target_uid = self._resolve_call_target(
                callee_name, receiver_expr, import_map, table
            )
            if target_uid and caller_uid != target_uid:
                edges.append(GraphEdge(
                    edge_type=EdgeType.CALLS,
                    source_uid=caller_uid,
                    target_uid=target_uid,
                    properties={"line": line, "cross_file": True},
                ))

        for child_uid, base_name in data.unresolved_inherits:
            target_uid = import_map.get(base_name) or table.get(base_name)
            if target_uid and child_uid != target_uid:
                edges.append(GraphEdge(
                    edge_type=EdgeType.INHERITS,
                    source_uid=child_uid,
                    target_uid=target_uid,
                ))

        for child_uid, iface_name in data.unresolved_implements:
            target_uid = import_map.get(iface_name) or table.get(iface_name)
            if target_uid and child_uid != target_uid:
                edges.append(GraphEdge(
                    edge_type=EdgeType.IMPLEMENTS,
                    source_uid=child_uid,
                    target_uid=target_uid,
                ))

    return edges


def _resolve_call_target(
    self, callee_name: str, receiver_expr: str,
    import_map: dict[str, str], symbol_table: dict[str, str],
) -> str | None:
    """Resolve a callee to a target uid using receiver type + import map."""
    if receiver_expr:
        receiver_type = receiver_expr.rsplit(".", 1)[-1] if "." in receiver_expr else receiver_expr
        receiver_class_uid = import_map.get(receiver_type) or symbol_table.get(receiver_type)
        if receiver_class_uid:
            method_fqn = f"{receiver_type}.{callee_name}"
            return symbol_table.get(method_fqn) or receiver_class_uid
    return import_map.get(callee_name) or symbol_table.get(callee_name)
```

- [x] **Step 5: Implement `build_from_files` (two-phase orchestrator)**

```python
def build_from_files(
    self, files: dict[str, str],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Two-phase build: per-file parsing + cross-file resolution."""
    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []
    per_file_data: list[_CrossFileData] = []

    # Phase 1: per-file parsing
    for file_path, content in files.items():
        nodes, edges = self.build_from_file(file_path, content=content)
        all_nodes.extend(nodes)
        all_edges.extend(edges)

        lang = self.detect_language(file_path) or ""
        result = self._parser.parse(file_path, content)

        func_uid_by_name: dict[str, list[str]] = {}
        for n in nodes:
            if n.label == NodeLabel.FUNCTION:
                name = n.properties.get("name", "")
                func_uid_by_name.setdefault(name, []).append(n.uid)

        unresolved_calls = []
        for call in result.calls:
            caller_uids = func_uid_by_name.get(call.caller_name, [])
            callee_uids = func_uid_by_name.get(call.callee_name, [])
            if caller_uids and not callee_uids:
                caller_uid = caller_uids[0]
                unresolved_calls.append((
                    caller_uid, call.callee_name,
                    getattr(call, "receiver_expr", ""), call.line,
                ))

        unresolved_inherits = []
        for n in nodes:
            if n.label == NodeLabel.CLASS:
                bases = n.properties.get("base_classes", [])
                for base in bases:
                    base_simple = base.rsplit(".", 1)[-1] if "." in base else base
                    base_uids = [
                        nn.uid for nn in nodes
                        if nn.label == NodeLabel.CLASS
                        and nn.properties.get("name") == base_simple
                        and nn.properties.get("file") == n.properties.get("file")
                    ]
                    if not base_uids:
                        unresolved_inherits.append((n.uid, base_simple))

        per_file_data.append(_CrossFileData(
            file_path=file_path,
            language=lang,
            imports=result.imports,
            unresolved_calls=unresolved_calls,
            unresolved_inherits=unresolved_inherits,
            unresolved_implements=[],
        ))

    # Phase 2: cross-file resolution
    symbol_tables = self._build_global_symbol_table(all_nodes)
    cross_edges = self._resolve_cross_file_edges(per_file_data, symbol_tables)
    all_edges.extend(cross_edges)

    return all_nodes, all_edges
```

- [x] **Step 6: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_cross_file_resolution.py -v`
Expected: PASS

- [x] **Step 7: Run full graph builder test suite for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_code_graph_builder.py -v`
Expected: All tests PASS

- [x] **Step 8: Commit**

```bash
git add indexer/code_graph_builder.py tests/test_cross_file_resolution.py
git commit -m "feat(graph): implement two-phase cross-file edge resolution (CALLS/INHERITS/IMPLEMENTS)"
```

---

### Task 6: Batch Edge Upsert in Store

**Files:**
- Modify: `store/indexer_store.py`
- Test: `tests/test_code_graph_builder.py` (add store integration test)

- [x] **Step 1: Write failing test for batch edge insertion**

```python
# tests/test_code_graph_builder.py — append

class TestUpsertEdgesBatch:
    @pytest.mark.asyncio
    async def test_upsert_edges_batch_creates_edges(self, mock_store):
        """indexer_store.upsert_edges_batch should accept list[GraphEdge] and batch insert."""
        from store.indexer_store import IndexerStore
        from store.schema import GraphEdge, EdgeType

        idx_store = IndexerStore(mock_store)
        edges = [
            GraphEdge(edge_type=EdgeType.CALLS, source_uid="a", target_uid="b",
                      properties={"cross_file": True}),
            GraphEdge(edge_type=EdgeType.INHERITS, source_uid="c", target_uid="d"),
        ]
        await idx_store.upsert_edges_batch("test_repo", edges)
        # Verify mock_store received the batch
        assert mock_store.upsert_edge_call_count >= 2
```

- [x] **Step 2: Implement `upsert_edges_batch` in IndexerStore**

In `store/indexer_store.py`, add:

```python
async def upsert_edges_batch(
    self, repository: str, edges: list[GraphEdge], batch_size: int = 500,
) -> int:
    """Batch upsert edges to the graph store. Returns count of edges written."""
    count = 0
    for i in range(0, len(edges), batch_size):
        batch = edges[i : i + batch_size]
        for edge in batch:
            await self._store.upsert_edge(repository, edge)
            count += 1
    return count
```

- [x] **Step 3: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_code_graph_builder.py::TestUpsertEdgesBatch -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add store/indexer_store.py tests/test_code_graph_builder.py
git commit -m "feat(store): add upsert_edges_batch for cross-file edge persistence"
```

---

### Task 7: Quick Fix — API Mode Default + inject_wikilinks

**Files:**
- Modify: `api/models/wiki_models.py:60-61`
- Modify: `wiki/service.py` (inject_wikilinks call)
- Test: `tests/test_wiki_config_defaults.py`

- [x] **Step 1: Write failing test for BusinessWikiGenerateBody default mode**

```python
# tests/test_wiki_config_defaults.py — append

def test_business_wiki_default_mode_is_full():
    from api.models.wiki_models import BusinessWikiGenerateBody
    body = BusinessWikiGenerateBody()
    assert body.mode == "full"
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_wiki_config_defaults.py::test_business_wiki_default_mode_is_full -v`
Expected: FAIL — default is "structure"

- [x] **Step 3: Change default mode to "full"**

In `api/models/wiki_models.py`, line 61:

```python
# Before:
mode: str = Field(
    default="structure",
    ...
)

# After:
mode: str = Field(
    default="full",
    pattern="^(structure|full)$",
    description="Wiki generation mode: 'structure' for fast code-only, 'full' for LLM-enriched content",
)
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_wiki_config_defaults.py::test_business_wiki_default_mode_is_full -v`
Expected: PASS

- [x] **Step 5: Integrate inject_wikilinks into compose pipeline**

In `wiki/service.py`, find `_compose_all_pages` (or the main compose orchestration method). After page composition is complete and before export, add:

```python
# After all pages are composed:
await self.inject_wikilinks(repository, composed_pages)
```

Locate the existing `inject_wikilinks` method to confirm its signature and ensure it's being called correctly.

- [x] **Step 6: Run existing wikilink tests for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_wikilink_resolver.py tests/wiki/test_wikilink_cache.py -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add api/models/wiki_models.py wiki/service.py tests/test_wiki_config_defaults.py
git commit -m "fix(wiki): set BusinessWiki default mode to 'full' and integrate inject_wikilinks"
```

---

### Task 8: Layer 0 Integration Test — Python Cross-File

**Files:**
- Test: `tests/test_cross_file_resolution.py`

- [x] **Step 1: Add Python cross-file CALLS test**

```python
@pytest.fixture
def python_builder():
    parser = TreeSitterParser(supported_languages=["python"])
    return CodeGraphBuilder(parser=parser, file_extensions={"python": [".py"]})


class TestCrossFileCallsPython:
    def test_service_to_repository_call(self, python_builder: CodeGraphBuilder):
        repo_code = "class UserRepository:\n    def find_by_id(self, uid):\n        pass\n"
        service_code = (
            "from repo import UserRepository\n\n"
            "class UserService:\n"
            "    def __init__(self):\n"
            "        self.repo = UserRepository()\n"
            "    def get_user(self, uid):\n"
            "        return self.repo.find_by_id(uid)\n"
        )
        files = {"repo.py": repo_code, "service.py": service_code}
        all_nodes, all_edges = python_builder.build_from_files(files)

        cross_calls = [
            e for e in all_edges
            if e.edge_type == EdgeType.CALLS and e.properties.get("cross_file")
        ]
        assert len(cross_calls) >= 1
```

- [x] **Step 2: Run test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_cross_file_resolution.py::TestCrossFileCallsPython -v`
Expected: PASS

- [x] **Step 3: Add backward compatibility regression test**

```python
class TestBackwardCompatibility:
    def test_same_file_calls_still_work(self, python_builder: CodeGraphBuilder):
        code = "def a():\n    b()\n\ndef b():\n    pass\n"
        files = {"test.py": code}
        _, all_edges = python_builder.build_from_files(files)
        calls = [e for e in all_edges if e.edge_type == EdgeType.CALLS]
        assert len(calls) >= 1

    def test_build_from_file_unchanged(self, python_builder: CodeGraphBuilder):
        """Original build_from_file should still work without cross-file resolution."""
        code = "def a():\n    b()\n\ndef b():\n    pass\n"
        nodes, edges = python_builder.build_from_file("test.py", content=code)
        calls = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(calls) >= 1
```

- [x] **Step 4: Run full cross-file test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_cross_file_resolution.py -v`
Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add tests/test_cross_file_resolution.py
git commit -m "test(graph): add Python cross-file CALLS and backward compat integration tests"
```

---

> **🔍 CODE REVIEW CHECKPOINT: Layer 0 完成**
>
> **Review Focus:**
> - 跨文件 CALLS/INHERITS/IMPLEMENTS 边解析的正确性
> - `_build_global_symbol_table` 内存安全性（大仓场景）
> - `build_from_files` 与原有 `build_from_file` 的向后兼容性
> - `ParsedCall.receiver_expr` 和 `ParsedImport.symbols` 的 tree-sitter query 准确性
> - JS/TS 箭头函数只提取顶层，不误提取 callback
>
> Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -v --tb=short`

---

## Layer 1: Quality Enhancement

> **⏱ Estimated: 6 days**
> **🔍 CODE REVIEW CHECKPOINT: Layer 1 完成后进行 Code Review，重点审查实体过滤逻辑、delegation 修复正确性、增量路径一致性**

### Task 9: EntityStrategy Enum + WikiEntityFilter

**Files:**
- Modify: `wiki/models.py`
- Create: `wiki/entity_filter.py`
- Test: `tests/wiki/test_entity_filter.py` (new file)

- [x] **Step 1: Write failing test for EntityStrategy and WikiEntityFilter**

```python
"""tests/wiki/test_entity_filter.py"""
import pytest
from store.schema import GraphNode, NodeLabel
from wiki.entity_filter import WikiEntityFilter, EntityStrategy


class TestWikiEntityFilter:
    @pytest.fixture
    def filter(self):
        return WikiEntityFilter()

    def test_enum_class_merges_to_parent(self, filter):
        node = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "StatusEnum",
                "is_interface": False,
                "methods_count": 0,
                "start_line": 1,
                "end_line": 5,
            },
        )
        assert filter.classify(node, edge_count=0, children_count=0) == EntityStrategy.MERGE_TO_PARENT

    def test_trivial_function_merges_to_parent(self, filter):
        node = GraphNode(
            label=NodeLabel.FUNCTION,
            properties={"name": "getId", "start_line": 10, "end_line": 12},
        )
        assert filter.classify(node, edge_count=0, children_count=0) == EntityStrategy.MERGE_TO_PARENT

    def test_service_class_gets_standard_page(self, filter):
        node = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "UserService",
                "methods_count": 10,
                "start_line": 1,
                "end_line": 200,
            },
        )
        assert filter.classify(node, edge_count=5, children_count=3) == EntityStrategy.STANDARD_PAGE

    def test_core_class_with_high_edges_gets_full_page(self, filter):
        node = GraphNode(
            label=NodeLabel.CLASS,
            properties={
                "name": "OrderController",
                "methods_count": 15,
                "start_line": 1,
                "end_line": 400,
                "semantic_roles": ["http_controller"],
            },
        )
        assert filter.classify(node, edge_count=20, children_count=5) == EntityStrategy.FULL_PAGE
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_entity_filter.py -v`
Expected: FAIL — module `wiki.entity_filter` not found

- [x] **Step 3: Add EntityStrategy to wiki/models.py**

```python
class EntityStrategy(StrEnum):
    FULL_PAGE = "full_page"
    STANDARD_PAGE = "standard"
    MERGE_TO_PARENT = "merge"
```

- [x] **Step 4: Create wiki/entity_filter.py**

```python
"""Entity filtering for Wiki page generation — classify which entities deserve pages."""

from __future__ import annotations

from store.schema import GraphNode, NodeLabel
from wiki.models import EntityStrategy


class WikiEntityFilter:
    """Classify graph entities into generation strategies."""

    TRIVIAL_LOC_THRESHOLD = 5
    CORE_EDGE_THRESHOLD = 10
    CORE_ROLES = frozenset({"http_controller", "rpc_provider", "message_listener"})

    def classify(
        self, node: GraphNode, edge_count: int, children_count: int,
    ) -> EntityStrategy:
        props = node.properties
        name = props.get("name", "")
        start = props.get("start_line", 0)
        end = props.get("end_line", 0)
        loc = end - start
        methods_count = props.get("methods_count", 0)
        is_interface = props.get("is_interface", False)
        roles = set(props.get("semantic_roles", []))

        if roles & self.CORE_ROLES or edge_count >= self.CORE_EDGE_THRESHOLD:
            return EntityStrategy.FULL_PAGE

        if node.label == NodeLabel.CLASS:
            if not is_interface and methods_count == 0 and loc < 20:
                return EntityStrategy.MERGE_TO_PARENT

        if node.label == NodeLabel.FUNCTION:
            if loc < self.TRIVIAL_LOC_THRESHOLD and edge_count == 0:
                return EntityStrategy.MERGE_TO_PARENT

        if children_count > 0 or methods_count > 3:
            return EntityStrategy.STANDARD_PAGE

        return EntityStrategy.STANDARD_PAGE
```

- [x] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_entity_filter.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add wiki/models.py wiki/entity_filter.py tests/wiki/test_entity_filter.py
git commit -m "feat(wiki): add WikiEntityFilter with EntityStrategy classification"
```

---

### Task 10: Integrate WikiEntityFilter into Structure Planner

**Files:**
- Modify: `wiki/structure_planner.py`
- Test: `tests/wiki/test_entity_filter.py` (extend)

- [x] **Step 1: Write failing test for filter integration in structure planner**

```python
class TestEntityFilterIntegration:
    @pytest.mark.asyncio
    async def test_enum_class_filtered_from_structure(self):
        """Enum classes should be filtered out of the wiki structure tree."""
        from wiki.structure_planner import WikiStructurePlanner
        from wiki.entity_filter import EntityStrategy

        # Create a mock graph query that returns an enum child node
        planner = WikiStructurePlanner(mock_graph_query)
        structure = await planner.plan(
            repository="test_repo",
            scope=ScopeParam(path="src/"),
        )
        child_names = [n.name for n in structure.root.children]
        assert "StatusEnum" not in child_names, "Enum should be filtered out"
```

- [x] **Step 2: Modify structure planner to use filter**

In `wiki/structure_planner.py`, import and use `WikiEntityFilter`:

```python
from wiki.entity_filter import WikiEntityFilter, EntityStrategy

# In _build_module_tree or equivalent, before creating child nodes:
entity_filter = WikiEntityFilter()
merged_entities: list[GraphNode] = []

for child in children:
    edge_count = ...  # count edges for this child
    children_count = ...  # count sub-children
    strategy = entity_filter.classify(child, edge_count, children_count)
    if strategy == EntityStrategy.MERGE_TO_PARENT:
        merged_entities.append(child)
        continue
    # ... create normal wiki structure node
```

- [x] **Step 3: Run structure planner tests for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -k "structure" -v`
Expected: All PASS

- [x] **Step 4: Commit**

```bash
git add wiki/structure_planner.py
git commit -m "feat(wiki): integrate WikiEntityFilter into structure planner to filter trivial entities"
```

---

### Task 11: Fix Delegation Edges — Real Graph Edges

**Files:**
- Modify: `wiki/service.py`
- Modify: `store/falkordb_store.py`
- Test: `tests/wiki/test_delegation.py`

- [x] **Step 1: Write failing test for find_edges_between**

```python
# tests/wiki/test_delegation.py — append

class TestFindEdgesBetween:
    @pytest.mark.asyncio
    async def test_find_edges_between_returns_relevant_edges(self, mock_store):
        """find_edges_between should return CALLS/IMPORTS edges between given uids."""
        uids = ["uid_a", "uid_b", "uid_c"]
        edge_types = ["CALLS", "IMPORTS"]
        result = await mock_store.find_edges_between("test_repo", uids, edge_types)
        assert isinstance(result, list)
```

- [x] **Step 2: Implement `find_edges_between` Cypher query**

In `store/falkordb_store.py`:

```python
async def find_edges_between(
    self, repository: str, uids: list[str], edge_types: list[str],
) -> list[dict[str, str]]:
    """Find all edges of given types between the specified node uids."""
    if not uids or not edge_types:
        return []
    query = (
        "MATCH (a)-[r]->(b) "
        "WHERE a.uid IN $uids AND b.uid IN $uids "
        "AND type(r) IN $edge_types "
        "RETURN a.uid AS source, type(r) AS edge_type, b.uid AS target"
    )
    result = await self._query(repository, query, {"uids": uids, "edge_types": edge_types})
    return [{"source": r["source"], "edge_type": r["edge_type"], "target": r["target"]}
            for r in result.data]
```

- [x] **Step 3: Fix service.py to pass real edges to `group_children_by_graph`**

In `wiki/service.py`, find where `group_children_by_graph(child_nodes, edges=[])` is called:

```python
# Before:
groups = group_children_by_graph(child_nodes, edges=[])

# After:
inter_child_edges = await self._store.find_edges_between(
    repository,
    [c.entity_uid for c in child_nodes if hasattr(c, 'entity_uid')],
    edge_types=[EdgeType.CALLS.value, EdgeType.IMPORTS.value],
)
groups = group_children_by_graph(child_nodes, edges=inter_child_edges)
```

- [x] **Step 4: Run delegation tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_delegation.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add wiki/service.py store/falkordb_store.py tests/wiki/test_delegation.py
git commit -m "fix(wiki): pass real graph edges to group_children_by_graph instead of empty list"
```

---

### Task 12: Incremental Path Enhancement — Depth Ordering + TD-3

**Files:**
- Modify: `wiki/service.py`
- Test: `tests/wiki/test_incremental_generation.py`

- [x] **Step 1: Write failing test for depth ordering**

```python
# tests/wiki/test_incremental_generation.py — append

class TestDepthOrdering:
    def test_leaves_processed_before_parents(self):
        """Incremental generation should process leaf nodes before parents."""
        from wiki.service import WikiService
        # Build mock edges showing CONTAINS hierarchy
        contains_edges = [
            {"source": "module_root", "target": "class_a"},
            {"source": "class_a", "target": "method_1"},
        ]
        sorted_uids = WikiService._sort_by_depth(
            ["module_root", "class_a", "method_1"], contains_edges,
        )
        assert sorted_uids.index("method_1") < sorted_uids.index("class_a")
        assert sorted_uids.index("class_a") < sorted_uids.index("module_root")
```

- [x] **Step 2: Implement `_sort_by_depth` static method**

```python
@staticmethod
def _sort_by_depth(
    uids: list[str],
    contains_edges: list[dict[str, str]],
) -> list[str]:
    """Sort uids by graph depth — leaves first, roots last."""
    children: dict[str, set[str]] = {}
    for edge in contains_edges:
        src, tgt = edge.get("source", ""), edge.get("target", "")
        children.setdefault(src, set()).add(tgt)

    uid_set = set(uids)

    def depth(uid: str, visited: set[str] | None = None) -> int:
        if visited is None:
            visited = set()
        if uid in visited:
            return 0
        visited.add(uid)
        kids = children.get(uid, set()) & uid_set
        if not kids:
            return 0
        return 1 + max(depth(k, visited) for k in kids)

    return sorted(uids, key=lambda u: depth(u))
```

- [x] **Step 3: Implement TD-3 entity_uid fallback in `_link_pages_to_tree`**

```python
# In _link_pages_to_tree, build lookup by entity_uid first:
pages_by_entity_uid = {p.get("entity_uid", ""): p for p in pages if p.get("entity_uid")}
pages_by_title = {p.get("title", ""): p for p in pages}

# Use combined lookup:
page = pages_by_entity_uid.get(entity_uid) or pages_by_title.get(title)
```

- [x] **Step 4: Run incremental generation tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_incremental_generation.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add wiki/service.py tests/wiki/test_incremental_generation.py
git commit -m "feat(wiki): add depth ordering for incremental generation and TD-3 entity_uid fallback"
```

---

### Task 13: Resume Functionality

**Files:**
- Modify: `wiki/service.py`
- Test: `tests/wiki/test_incremental_fallback.py`

- [x] **Step 1: Write failing test for resume skipping already-generated pages**

```python
class TestResumeGeneration:
    @pytest.mark.asyncio
    async def test_resume_skips_unchanged_pages(self):
        """When resume is enabled, pages with matching content hash should be skipped."""
        from wiki.service import WikiService
        import hashlib

        existing_hashes = {"src/user_service.py": hashlib.sha256(b"content_v1").hexdigest()}

        service = WikiService(config=mock_config_with_resume, store=mock_store)
        mock_store.set_existing_pages(existing_hashes)

        composed_paths = []
        original_compose = service._compose_single_page

        async def tracking_compose(*args, **kwargs):
            composed_paths.append(args[0].path)
            return await original_compose(*args, **kwargs)

        service._compose_single_page = tracking_compose
        await service.generate(repository="test_repo")

        assert "src/user_service.py" not in composed_paths, \
            "Unchanged page should not be re-composed"
```

- [x] **Step 2: Add resume logic to composition pipeline**

In `wiki/service.py`, in the relevant compose method:

```python
if self._config.resume_from_saved:
    existing_hashes = await self._load_existing_page_hashes(repository)
    for node in nodes_to_compose:
        current_hash = self._compute_content_hash(node)
        if node.path in existing_hashes and existing_hashes[node.path] == current_hash:
            summary_index[node.path] = await self._load_existing_summary(node.path)
            continue
        # ... compose page normally
```

- [x] **Step 3: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_incremental_fallback.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add wiki/service.py tests/wiki/test_incremental_fallback.py
git commit -m "feat(wiki): add resume-from-saved functionality for wiki generation"
```

---

### Task 14: CommentFilter Integration

**Files:**
- Modify: `indexer/comment_filter.py`
- Modify: `wiki/composer.py`
- Test: `tests/test_comment_filter.py`

- [x] **Step 1: Write failing test for complete CommentTier model**

```python
# tests/test_comment_filter.py — append

class TestCommentTierModel:
    def test_structured_doc_is_tier_1(self):
        from indexer.comment_filter import CommentFilter, CommentTier
        f = CommentFilter()
        assert f.classify("/** @param name The user name */") == CommentTier.STRUCTURED_DOC

    def test_license_header_is_never(self):
        from indexer.comment_filter import CommentFilter, CommentTier
        f = CommentFilter()
        result = f.classify("/* Copyright 2026 Example Corp. All rights reserved. */")
        assert result == CommentTier.NEVER

    def test_meaningful_inline_is_tier_4(self):
        from indexer.comment_filter import CommentFilter, CommentTier
        f = CommentFilter()
        result = f.classify("// This workaround is needed because the API returns null for deleted users")
        assert result == CommentTier.INLINE
```

- [x] **Step 2: Complete CommentTier enum in comment_filter.py**

```python
class CommentTier(Enum):
    STRUCTURED_DOC = 1
    FILE_HEADER = 2
    BLOCK_COMMENT = 3
    INLINE = 4
    NEVER = 99
```

Implement the `classify` method to properly categorize comments.

- [x] **Step 3: Wire CommentFilter into wiki/composer.py `_entity_digest`**

```python
from indexer.comment_filter import CommentFilter, CommentTier

# In _entity_digest method:
_comment_filter = CommentFilter()

if config.comment_injection_tier >= CommentTier.STRUCTURED_DOC.value:
    docstring = n.properties.get("docstring", "")
    if docstring and _comment_filter.classify(docstring).value <= CommentTier.STRUCTURED_DOC.value:
        lines.append(f"- Documentation: {docstring[:config.comment_max_chars]}")
```

- [x] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_comment_filter.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add indexer/comment_filter.py wiki/composer.py tests/test_comment_filter.py
git commit -m "feat(wiki): complete CommentTier model and integrate CommentFilter into composer"
```

---

> **🔍 CODE REVIEW CHECKPOINT: Layer 1 完成**
>
> **Review Focus:**
> - WikiEntityFilter 分类逻辑是否覆盖所有 edge case（enum、constant holder、trivial function）
> - delegation edges 修复后 `group_children_by_graph` 行为变化
> - 增量路径的深度排序正确性
> - CommentFilter 的 tier 判断准确性
> - resume 功能的 hash 一致性和边界情况
>
> Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -v --tb=short`

---

## Layer 2: Nested Domain Tree

> **⏱ Estimated: 6.5 days**
> **🔍 CODE REVIEW CHECKPOINT: Layer 2 完成后进行 Code Review，重点审查 LLM prompt 质量、依赖图准确性、树构建正确性**

### Task 15: ModuleDependencyGraph + Entry Point Identification

**Files:**
- Create: `wiki/dependency_graph.py`
- Modify: `store/falkordb_store.py`
- Test: `tests/wiki/test_dependency_graph.py` (new file)

- [x] **Step 1: Write failing test for ModuleDependencyGraph**

```python
"""tests/wiki/test_dependency_graph.py"""
import pytest
from wiki.dependency_graph import ModuleDependencyGraph, ModuleGraph, ModuleInfo


class TestModuleDependencyGraph:
    @pytest.mark.asyncio
    async def test_build_returns_module_graph(self, mock_store):
        graph_builder = ModuleDependencyGraph(mock_store)
        result = await graph_builder.build("test_repo")
        assert isinstance(result, ModuleGraph)
        assert isinstance(result.modules, list)
        assert isinstance(result.entry_points, list)

    @pytest.mark.asyncio
    async def test_rpc_provider_is_entry_point(self, mock_store_with_rpc):
        graph_builder = ModuleDependencyGraph(mock_store_with_rpc)
        result = await graph_builder.build("test_repo")
        entry_names = [m for m in result.entry_points]
        assert any("Provider" in name or "Controller" in name for name in entry_names)
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_dependency_graph.py -v`
Expected: FAIL — module `wiki.dependency_graph` not found

- [x] **Step 3: Create wiki/dependency_graph.py**

```python
"""Build module-level dependency graph for Wiki domain tree decomposition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from log import get_logger
from store.schema import NodeLabel

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_RPC_ENTRY_ROLES = frozenset({"rpc_provider", "http_controller", "message_listener", "scheduled_task"})
_ENTRY_NAME_HINTS = frozenset({"controller", "endpoint", "handler", "main", "gateway"})


@dataclass
class ModuleInfo:
    name: str
    path: str
    uid: str
    summary: str = ""
    docstring: str = ""
    semantic_roles: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    top_classes: list[str] = field(default_factory=list)
    calls_out: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleEdge:
    source: str
    target: str
    edge_type: str
    weight: int = 1


@dataclass
class ModuleGraph:
    modules: list[ModuleInfo] = field(default_factory=list)
    edges: list[ModuleEdge] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)


class ModuleDependencyGraph:
    """Build module-level dependency graph from FalkorDB."""

    _MODULE_CALLS_CYPHER = (
        "MATCH (m1:Module {repository: $repo})-[:CONTAINS*1..3]->(f1)"
        "-[:CALLS]->(f2)<-[:CONTAINS*1..3]-(m2:Module {repository: $repo}) "
        "WHERE m1 <> m2 "
        "RETURN m1.name AS source, m2.name AS target, count(*) AS weight "
        "ORDER BY weight DESC"
    )

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def build(self, repository: str) -> ModuleGraph:
        modules = await self._load_modules(repository)
        edges = await self._load_module_edges(repository)
        entry_points = self._identify_entry_points(modules, edges)
        return ModuleGraph(modules=modules, edges=edges, entry_points=entry_points)

    async def _load_modules(self, repository: str) -> list[ModuleInfo]:
        result = await self._store.query(
            repository,
            "MATCH (m:Module {repository: $repo}) RETURN m",
            {"repo": repository},
        )
        modules = []
        for row in result.data:
            m = row.get("m", {})
            modules.append(ModuleInfo(
                name=m.get("name", ""),
                path=m.get("path", ""),
                uid=m.get("uid", ""),
                summary=m.get("summary", ""),
                docstring=m.get("docstring", ""),
                semantic_roles=m.get("semantic_roles", []) or [],
                annotations=m.get("annotations", []) or [],
                properties=m,
            ))
        return modules

    async def _load_module_edges(self, repository: str) -> list[ModuleEdge]:
        result = await self._store.query(
            repository, self._MODULE_CALLS_CYPHER, {"repo": repository},
        )
        return [
            ModuleEdge(
                source=r["source"], target=r["target"],
                edge_type="CALLS", weight=r.get("weight", 1),
            )
            for r in result.data
        ]

    def _identify_entry_points(
        self, modules: list[ModuleInfo], edges: list[ModuleEdge],
    ) -> list[str]:
        called_modules = {e.target for e in edges}
        calling_modules = {e.source for e in edges}
        entry_points: list[str] = []

        for m in modules:
            is_entry = False
            if m.name in calling_modules and m.name not in called_modules:
                is_entry = True
            if set(m.semantic_roles) & _RPC_ENTRY_ROLES:
                is_entry = True
            if any(hint in m.name.lower() for hint in _ENTRY_NAME_HINTS):
                is_entry = True
            if is_entry:
                entry_points.append(m.name)

        return entry_points
```

- [x] **Step 4: Add module-level CALLS aggregation Cypher to FalkorDB store**

In `store/falkordb_store.py`, ensure the `query` method can handle the above Cypher.

- [x] **Step 5: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_dependency_graph.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add wiki/dependency_graph.py store/falkordb_store.py tests/wiki/test_dependency_graph.py
git commit -m "feat(wiki): add ModuleDependencyGraph with entry point identification and RPC support"
```

---

### Task 16: HubNodeDetector + LargeClassStrategy

**Files:**
- Modify: `wiki/entity_filter.py`
- Test: `tests/wiki/test_entity_filter.py`

- [x] **Step 1: Write failing test for LargeClassStrategy**

```python
class TestLargeClassStrategy:
    def test_groups_methods_by_semantic_role(self):
        from wiki.entity_filter import LargeClassStrategy, MethodGroup
        from store.schema import GraphNode, NodeLabel

        methods = [
            GraphNode(label=NodeLabel.FUNCTION, properties={"name": "createUser", "annotations": ["@PostMapping"]}),
            GraphNode(label=NodeLabel.FUNCTION, properties={"name": "getUser", "annotations": ["@GetMapping"]}),
            GraphNode(label=NodeLabel.FUNCTION, properties={"name": "deleteUser", "annotations": ["@DeleteMapping"]}),
            GraphNode(label=NodeLabel.FUNCTION, properties={"name": "scheduledCleanup", "annotations": ["@Scheduled"]}),
        ] + [
            GraphNode(label=NodeLabel.FUNCTION, properties={"name": f"helper_{i}"})
            for i in range(30)
        ]

        strategy = LargeClassStrategy()
        groups = strategy.group_methods(methods)
        assert len(groups) >= 2
        group_names = [g.name for g in groups]
        assert any("API" in name or "Endpoint" in name for name in group_names)

    def test_below_threshold_returns_single_group(self):
        from wiki.entity_filter import LargeClassStrategy
        from store.schema import GraphNode, NodeLabel

        methods = [
            GraphNode(label=NodeLabel.FUNCTION, properties={"name": f"m{i}"})
            for i in range(5)
        ]
        strategy = LargeClassStrategy()
        groups = strategy.group_methods(methods)
        assert len(groups) == 1
```

- [x] **Step 2: Implement LargeClassStrategy**

```python
@dataclass
class MethodGroup:
    name: str
    methods: list[GraphNode]


class LargeClassStrategy:
    METHOD_GROUP_THRESHOLD = 30

    _API_ANNOTATIONS = frozenset({
        "GetMapping", "PostMapping", "PutMapping", "DeleteMapping",
        "PatchMapping", "RequestMapping",
    })
    _TASK_ANNOTATIONS = frozenset({"Scheduled", "KafkaListener", "KafkaHandler"})

    def group_methods(self, methods: list[GraphNode]) -> list[MethodGroup]:
        if len(methods) < self.METHOD_GROUP_THRESHOLD:
            return [MethodGroup(name="All Methods", methods=methods)]

        api_methods = []
        task_methods = []
        other_methods = []

        for m in methods:
            anns = set(m.properties.get("annotations", []))
            ann_simple = {a.lstrip("@").split("(")[0].rsplit(".", 1)[-1] for a in anns}
            if ann_simple & self._API_ANNOTATIONS:
                api_methods.append(m)
            elif ann_simple & self._TASK_ANNOTATIONS:
                task_methods.append(m)
            else:
                other_methods.append(m)

        groups = []
        if api_methods:
            groups.append(MethodGroup(name="API Endpoints", methods=api_methods))
        if task_methods:
            groups.append(MethodGroup(name="Scheduled Tasks", methods=task_methods))
        if other_methods:
            groups.append(MethodGroup(name="Internal Methods", methods=other_methods))
        return groups or [MethodGroup(name="All Methods", methods=methods)]
```

- [x] **Step 3: Run LargeClassStrategy tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_entity_filter.py::TestLargeClassStrategy -v`
Expected: PASS

- [x] **Step 4: Write failing tests for HubNodeDetector**

```python
class TestHubNodeDetector:
    def test_high_degree_module_detected_as_hub(self):
        from wiki.entity_filter import HubNodeDetector
        from wiki.dependency_graph import ModuleGraph, ModuleInfo, ModuleEdge

        modules = [ModuleInfo(name=f"m{i}", path=f"m{i}.py", uid=f"uid_{i}") for i in range(10)]
        edges = [ModuleEdge(source="m0", target=f"m{i}", edge_type="CALLS") for i in range(1, 10)]
        edges += [ModuleEdge(source=f"m{i}", target="m0", edge_type="CALLS") for i in range(1, 10)]
        graph = ModuleGraph(modules=modules, edges=edges, entry_points=[])

        detector = HubNodeDetector()
        hubs = detector.detect_hubs(graph, percentile=90)
        assert "m0" in hubs

    def test_rpc_provider_not_in_hubs(self):
        from wiki.entity_filter import HubNodeDetector
        from wiki.dependency_graph import ModuleGraph, ModuleInfo, ModuleEdge

        modules = [
            ModuleInfo(name="RpcProvider", path="rpc.py", uid="uid_rpc",
                       semantic_roles=["rpc_provider"]),
        ] + [ModuleInfo(name=f"m{i}", path=f"m{i}.py", uid=f"uid_{i}") for i in range(9)]
        edges = [ModuleEdge(source="RpcProvider", target=f"m{i}", edge_type="CALLS") for i in range(9)]
        edges += [ModuleEdge(source=f"m{i}", target="RpcProvider", edge_type="CALLS") for i in range(9)]
        graph = ModuleGraph(modules=modules, edges=edges, entry_points=["RpcProvider"])

        detector = HubNodeDetector()
        hubs = detector.detect_hubs(graph, percentile=90)
        assert "RpcProvider" not in hubs
```

- [x] **Step 5: Implement HubNodeDetector in entity_filter.py**

```python
@dataclass
class HubInfo:
    name: str
    domain: str


class HubNodeDetector:
    WHITELIST_ROLES = frozenset({"rpc_provider", "http_controller", "message_listener"})

    def detect_hubs(self, graph: ModuleGraph, percentile: float = 90) -> list[str]:
        module_roles = {m.name: set(m.semantic_roles) for m in graph.modules}

        calls_out: dict[str, list[str]] = {}
        called_by: dict[str, list[str]] = {}
        for e in graph.edges:
            calls_out.setdefault(e.source, []).append(e.target)
            called_by.setdefault(e.target, []).append(e.source)

        degrees = sorted(
            [(m.name, len(calls_out.get(m.name, [])) + len(called_by.get(m.name, [])))
             for m in graph.modules],
            key=lambda x: x[1],
        )
        if not degrees:
            return []
        idx = int(len(degrees) * percentile / 100)
        threshold = degrees[idx][1] if idx < len(degrees) else float("inf")

        return [
            m for m, d in degrees
            if d > threshold and not (module_roles.get(m, set()) & self.WHITELIST_ROLES)
        ]

    def prepare(self, graph: ModuleGraph) -> tuple[ModuleGraph, list[HubInfo]]:
        hubs = self.detect_hubs(graph)
        hub_set = set(hubs)
        reduced_modules = [m for m in graph.modules if m.name not in hub_set]
        reduced_edges = [
            e for e in graph.edges
            if e.source not in hub_set and e.target not in hub_set
        ]
        reduced_graph = ModuleGraph(
            modules=reduced_modules,
            edges=reduced_edges,
            entry_points=[ep for ep in graph.entry_points if ep not in hub_set],
        )
        return reduced_graph, [HubInfo(name=h, domain="__infrastructure__") for h in hubs]
```

- [x] **Step 6: Run all entity filter tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_entity_filter.py -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add wiki/entity_filter.py tests/wiki/test_entity_filter.py
git commit -m "feat(wiki): add HubNodeDetector with RPC whitelist and LargeClassStrategy for God classes"
```

---

### Task 17: LLM Hierarchical Decomposition — ModuleReprBuilder + HierarchicalDecomposer

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py`
- Create: (logic in `wiki/dependency_graph.py` or new file — prefer extending `dependency_graph.py`)
- Test: `tests/wiki/test_nested_domain_tree.py`

- [x] **Step 1: Write failing test for ModuleReprBuilder**

```python
"""tests/wiki/test_nested_domain_tree.py"""
import pytest
from wiki.dependency_graph import ModuleInfo, ModuleReprBuilder, TokenBudget


class TestModuleReprBuilder:
    def test_p0_always_included(self):
        module = ModuleInfo(
            name="UserService", path="user_service.py", uid="uid_1",
            semantic_roles=["service"],
            calls_out=["OrderService", "PaymentService"],
            called_by=["UserController"],
        )
        builder = ModuleReprBuilder()
        budget = TokenBudget(total=100, used=0)
        text = builder.build(module, budget)
        assert "UserService" in text
        assert "service" in text
        assert "OrderService" in text

    def test_rpc_interface_injected_for_rpc_provider(self):
        module = ModuleInfo(
            name="UserProvider", path="user_provider.py", uid="uid_2",
            semantic_roles=["rpc_provider"],
            properties={"rpc_interface": "com.example.api.UserService"},
        )
        builder = ModuleReprBuilder()
        budget = TokenBudget(total=200, used=0)
        text = builder.build(module, budget)
        assert "com.example.api.UserService" in text
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_nested_domain_tree.py::TestModuleReprBuilder -v`
Expected: FAIL — `ModuleReprBuilder` not found

- [x] **Step 3: Implement ModuleReprBuilder and TokenBudget in dependency_graph.py**

```python
@dataclass
class TokenBudget:
    total: int
    used: int

    def allows_p1(self) -> bool:
        return (self.total - self.used) > 150

    def allows_p2(self) -> bool:
        return (self.total - self.used) > 250


class ModuleReprBuilder:
    MAX_TOKENS_PER_BATCH = 30_000

    def build(self, module: ModuleInfo, budget: TokenBudget) -> str:
        lines = [f"Module: {module.name}"]

        if module.semantic_roles:
            lines.append(f"  Role: {', '.join(module.semantic_roles)}")
        if "rpc_provider" in (module.semantic_roles or []):
            rpc_iface = module.properties.get("rpc_interface", "")
            if rpc_iface:
                lines.append(f"  RPC Interface: {rpc_iface}")
        lines.append(f"  Deps OUT: {module.calls_out[:10]}")
        lines.append(f"  Deps IN: {module.called_by[:10]}")

        if budget.allows_p1():
            summary = module.summary or module.docstring
            if summary:
                lines.append(f"  Summary: {summary[:300]}")

        if budget.allows_p2():
            if module.top_classes:
                lines.append(f"  Key classes: {module.top_classes[:5]}")
            if module.annotations:
                lines.append(f"  Annotations: {module.annotations[:5]}")

        return "\n".join(lines)
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_nested_domain_tree.py::TestModuleReprBuilder -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add wiki/dependency_graph.py tests/wiki/test_nested_domain_tree.py
git commit -m "feat(wiki): add ModuleReprBuilder with token-budget-aware module representation"
```

---

### Task 18: HierarchicalDecomposer — LLM Domain Tree Generation

**Files:**
- Modify: `wiki/dependency_graph.py` (add HierarchicalDecomposer)
- Modify: `wiki/cross_repo_domain_planner.py` (refactor to use HierarchicalDecomposer)
- Test: `tests/wiki/test_nested_domain_tree.py`

- [x] **Step 1: Write failing test for HierarchicalDecomposer**

```python
class TestHierarchicalDecomposer:
    @pytest.mark.asyncio
    async def test_single_pass_returns_domain_tree(self, mock_llm):
        from wiki.dependency_graph import (
            HierarchicalDecomposer, ModuleGraph, ModuleInfo,
        )
        modules = [
            ModuleInfo(name="UserController", path="uc.py", uid="1",
                       semantic_roles=["http_controller"]),
            ModuleInfo(name="UserService", path="us.py", uid="2",
                       semantic_roles=["service"]),
            ModuleInfo(name="UserRepository", path="ur.py", uid="3",
                       semantic_roles=["repository"]),
        ]
        graph = ModuleGraph(modules=modules, edges=[], entry_points=["UserController"])
        decomposer = HierarchicalDecomposer(llm=mock_llm, max_depth=3, min_modules_for_nesting=2)
        result = await decomposer.decompose(modules, graph)
        assert result is not None
        assert len(result) >= 1  # at least one domain
```

- [x] **Step 2: Implement HierarchicalDecomposer**

```python
@dataclass
class DomainNode:
    name: str
    description: str = ""
    modules: list[str] = field(default_factory=list)
    children: list[DomainNode] = field(default_factory=list)


class HierarchicalDecomposer:
    def __init__(
        self, llm: Any, *,
        max_depth: int = 4,
        min_modules_for_nesting: int = 3,
        max_tokens_per_batch: int = 30_000,
    ) -> None:
        self._llm = llm
        self._max_depth = max_depth
        self._min_modules = min_modules_for_nesting
        self._max_tokens = max_tokens_per_batch
        self._repr_builder = ModuleReprBuilder()

    async def decompose(
        self, modules: list[ModuleInfo], graph: ModuleGraph,
    ) -> list[DomainNode]:
        estimated = self._estimate_tokens(modules, graph)
        if estimated <= self._max_tokens:
            return await self._single_pass(modules, graph)

        batch_count = max(2, estimated // self._max_tokens)
        pre_clusters = self._pre_cluster_by_imports(modules, graph, batch_count)
        trees = []
        for cluster in pre_clusters:
            tree = await self._single_pass(cluster, graph)
            trees.extend(tree)
        return await self._merge_domains(trees)

    async def _single_pass(
        self, modules: list[ModuleInfo], graph: ModuleGraph,
    ) -> list[DomainNode]:
        budget = TokenBudget(total=self._max_tokens, used=0)
        module_texts = []
        for m in modules:
            text = self._repr_builder.build(m, budget)
            budget.used += len(text) // 4  # rough token estimate
            module_texts.append(text)

        prompt = self._build_decomposition_prompt(module_texts, graph.entry_points)
        response = await self._llm.chat(
            system="Reply with JSON only. No markdown fences.",
            user=prompt,
        )
        return self._parse_domain_tree(response, modules)

    def _build_decomposition_prompt(
        self, module_texts: list[str], entry_points: list[str],
    ) -> str:
        modules_block = "\n---\n".join(module_texts)
        return (
            f"Analyze the following code modules and organize them into a hierarchical "
            f"business domain tree.\n\n"
            f"Entry points: {entry_points}\n\n"
            f"Modules:\n{modules_block}\n\n"
            f"## Constraints\n"
            f"- Maximum tree depth: {self._max_depth} levels\n"
            f"- Only create a sub-domain if it contains >= {self._min_modules} modules\n"
            f"- Prefer flatter trees when modules are loosely related\n\n"
            f"## Output Format\n"
            f"Return a JSON array of domain objects:\n"
            f'{{"domains": [{{"name": "...", "description": "...", '
            f'"modules": ["module_name", ...], '
            f'"children": [... nested domains ...]}}]}}'
        )

    def _parse_domain_tree(
        self, response: str, modules: list[ModuleInfo],
    ) -> list[DomainNode]:
        import json
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                return [DomainNode(
                    name="Uncategorized",
                    modules=[m.name for m in modules],
                )]

        domains_raw = data.get("domains", [])
        return [self._parse_node(d) for d in domains_raw]

    def _parse_node(self, raw: dict) -> DomainNode:
        return DomainNode(
            name=raw.get("name", "Unknown"),
            description=raw.get("description", ""),
            modules=raw.get("modules", []),
            children=[self._parse_node(c) for c in raw.get("children", [])],
        )

    def _estimate_tokens(self, modules: list[ModuleInfo], graph: ModuleGraph) -> int:
        return len(modules) * 150  # rough estimate

    def _pre_cluster_by_imports(
        self, modules: list[ModuleInfo], graph: ModuleGraph, batch_count: int,
    ) -> list[list[ModuleInfo]]:
        if batch_count <= 1:
            return [modules]
        chunk_size = max(1, len(modules) // batch_count)
        return [modules[i:i+chunk_size] for i in range(0, len(modules), chunk_size)]

    async def _merge_domains(self, trees: list[DomainNode]) -> list[DomainNode]:
        return trees
```

- [x] **Step 3: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_nested_domain_tree.py -v`
Expected: PASS

- [x] **Step 4: Refactor CrossRepoBusinessDomainPlanner to use HierarchicalDecomposer**

In `wiki/cross_repo_domain_planner.py`, replace the flat classification with:

```python
from wiki.dependency_graph import HierarchicalDecomposer, ModuleDependencyGraph

# In classify method or equivalent:
dep_graph = ModuleDependencyGraph(self._store)
module_graph = await dep_graph.build(repository)
decomposer = HierarchicalDecomposer(llm=self._llm)
domain_tree = await decomposer.decompose(module_graph.modules, module_graph)
```

- [x] **Step 5: Run existing domain planner tests for regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_cross_repo_domain_planner.py tests/wiki/test_business_domain_planner.py -v`
Expected: PASS (may need mock updates)

- [x] **Step 6: Commit**

```bash
git add wiki/dependency_graph.py wiki/cross_repo_domain_planner.py tests/wiki/test_nested_domain_tree.py
git commit -m "feat(wiki): add HierarchicalDecomposer for LLM-driven nested domain tree generation"
```

---

### Task 19: Recursive WikiSection Construction

**Files:**
- Modify: `wiki/service.py`
- Modify: `store/wiki_tree_store.py`
- Test: `tests/wiki/test_business_tree_persist.py`

- [x] **Step 1: Write failing test for recursive tree linking**

```python
class TestRecursiveTreeLinking:
    @pytest.mark.asyncio
    async def test_nested_domains_create_nested_sections(self, wiki_service, mock_store):
        from wiki.dependency_graph import DomainNode

        domain_tree = [
            DomainNode(
                name="User Management",
                modules=["UserController"],
                children=[
                    DomainNode(name="Authentication", modules=["AuthService", "TokenService"]),
                    DomainNode(name="Profile", modules=["ProfileService"]),
                ],
            ),
        ]
        await wiki_service._link_pages_to_nested_tree(
            "business_1", domain_tree, {}, wiki_service._tree_builder,
        )
        # Verify nested HAS_CHILD edges were created
        assert mock_store.upsert_wiki_section_call_count >= 3
```

- [x] **Step 2: Implement `_link_pages_to_nested_tree` in wiki/service.py**

```python
async def _link_pages_to_nested_tree(
    self,
    business_id: str,
    domain_tree: list,  # list[DomainNode]
    pages_by_entity_uid: dict[str, Any],
    tree_builder: WikiTreeBuilder,
) -> None:
    root_uid = f"wiki_root_{business_id}"

    async def _link_domain(parent_uid: str, domain: Any, sort_idx: int) -> None:
        section_uid = f"{business_id}_{domain.name.lower().replace(' ', '_')}"
        await self._wiki_store.upsert_wiki_section(
            section_uid, domain.name, domain.description or "", business_id,
        )
        await self._wiki_store.add_has_child_edge(parent_uid, section_uid, sort_idx)

        for i, module_name in enumerate(domain.modules):
            page = pages_by_entity_uid.get(module_name)
            if page:
                page_uid = page.get("uid", "") if isinstance(page, dict) else getattr(page, "uid", "")
                if page_uid:
                    await self._wiki_store.add_has_child_edge(section_uid, page_uid, i)

        for i, child in enumerate(domain.children):
            await _link_domain(section_uid, child, i)

    for i, domain in enumerate(domain_tree):
        await _link_domain(root_uid, domain, i)
```

- [x] **Step 3: Add multi-level HAS_CHILD traversal to wiki_tree_store.py**

```python
async def get_nested_tree(self, root_uid: str, max_depth: int = 5) -> list[dict]:
    query = (
        f"MATCH path = (root:WikiSection {{uid: $root_uid}})"
        f"-[:HAS_CHILD*1..{max_depth}]->(child) "
        f"RETURN path ORDER BY length(path)"
    )
    return await self._query(query, {"root_uid": root_uid})
```

- [x] **Step 4: Run tree tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_business_tree_persist.py tests/wiki/test_tree_builder.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add wiki/service.py store/wiki_tree_store.py tests/wiki/test_business_tree_persist.py
git commit -m "feat(wiki): implement recursive WikiSection construction for nested domain tree"
```

---

> **🔍 CODE REVIEW CHECKPOINT: Layer 2 完成**
>
> **Review Focus:**
> - LLM decomposition prompt 质量和 JSON 解析健壮性
> - ModuleDependencyGraph 的 Cypher 查询性能（CONTAINS*1..3 展开）
> - HubNodeDetector whitelist 覆盖范围（@MoaProvider/@Controller/@KafkaListener）
> - 递归树构建的边界情况（空 domain、单模块 domain）
> - ModuleReprBuilder token budget 管理准确性
>
> Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -v --tb=short`

---

## Layer 3: Overview Enhancement

> **⏱ Estimated: 3 days**
> **🔍 CODE REVIEW CHECKPOINT: Layer 3 完成后进行 Code Review，重点审查 LLM prompt V2 质量、域概览页完整性、glossary 一致性**

### Task 20: Parent Compose Enhancement — V2 Prompt

**Files:**
- Modify: `wiki/composer.py`
- Test: `tests/wiki/test_compose_phases.py`

- [x] **Step 1: Write failing test for enhanced parent page with inter-child deps**

```python
class TestParentComposeV2:
    @pytest.mark.asyncio
    async def test_parent_page_includes_architecture_section(self, composer, mock_llm):
        """V2 parent compose should produce pages with Architecture Overview section."""
        mock_llm.set_response(
            "## Purpose\nUser management module\n\n"
            "## Architecture Overview\n```mermaid\ngraph TD\n  A-->B\n```\n\n"
            "## Key Data Flows\nCreate user flow\n\n"
            "## Entry Points\n- UserController\n\n"
            "## Design Patterns\n- Repository pattern"
        )
        page = await composer.compose_parent_page(
            parent_node=mock_parent,
            children_summaries=mock_children,
            inter_child_edges=mock_edges,
        )
        assert "Architecture Overview" in page.content
```

- [x] **Step 2: Update `_PARENT_SYSTEM_PROMPT` to V2**

In `wiki/composer.py`:

```python
_PARENT_SYSTEM_PROMPT = (
    "You are a senior architect synthesizing module documentation. "
    "You receive child component summaries AND their inter-dependencies. "
    "Generate a cohesive module overview with these sections:\n"
    "1. **Purpose & Responsibility**\n"
    "2. **Architecture Overview** (with Mermaid diagram)\n"
    "3. **Key Data Flows**\n"
    "4. **Entry Points**\n"
    "5. **Design Patterns**"
)
```

- [x] **Step 3: Inject inter-child edges into parent compose prompt**

In the `compose_parent_page` method, add inter-child dependency info:

```python
if inter_child_edges:
    deps_text = "\n".join(
        f"  {e['source']} --{e['edge_type']}--> {e['target']}"
        for e in inter_child_edges[:20]
    )
    prompt += f"\n\nInter-component dependencies:\n{deps_text}"
```

- [x] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_phases.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add wiki/composer.py tests/wiki/test_compose_phases.py
git commit -m "feat(wiki): upgrade parent compose to V2 with inter-child dependencies and structured sections"
```

---

### Task 21: Domain Overview Enhancement

**Files:**
- Modify: `wiki/domain_overview_composer.py`
- Test: `tests/wiki/test_nested_domain_tree.py` (extend)

- [x] **Step 1: Enhance domain overview with nested navigation and entry points**

In `wiki/domain_overview_composer.py`, add:

```python
def _build_nested_navigation(self, domain_tree: list) -> str:
    """Generate nested sub-domain navigation links."""
    lines = ["## Sub-Domains\n"]
    for domain in domain_tree:
        lines.append(f"- **{domain.name}**: {domain.description}")
        for child in domain.children:
            lines.append(f"  - {child.name}: {child.description}")
    return "\n".join(lines)

def _build_entry_points_section(self, entry_points: list[str]) -> str:
    """List module entry points."""
    if not entry_points:
        return ""
    lines = ["## Entry Points\n"]
    for ep in entry_points:
        lines.append(f"- `{ep}`")
    return "\n".join(lines)
```

- [x] **Step 2: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -k "domain" -v`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add wiki/domain_overview_composer.py
git commit -m "feat(wiki): enhance domain overview with nested navigation and entry point listing"
```

---

### Task 22: Glossary Alignment

**Files:**
- Modify: `wiki/service.py`
- Test: `tests/wiki/test_incremental_generation.py`

- [x] **Step 1: Fix build_glossary parameter shape in incremental path**

In `wiki/service.py`, locate the incremental generation path and ensure `build_glossary` receives the same parameters as in the full generation path.

- [x] **Step 2: Run incremental generation tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_incremental_generation.py -v`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add wiki/service.py
git commit -m "fix(wiki): align glossary parameters between full and incremental generation paths"
```

---

> **🔍 CODE REVIEW CHECKPOINT: Layer 3 完成 — 全量最终审查**
>
> **Review Focus:**
> - V2 parent compose prompt 生成的页面质量
> - 域概览页的嵌套导航链接正确性
> - glossary 参数在全量/增量路径的一致性
> - 全量测试通过
>
> Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -v --tb=short`
>
> **Final Regression:**
> ```bash
> cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
> uv run pytest tests/ -v --tb=short 2>&1 | tail -20
> ```

---

## Summary

| Layer | Tasks | New Files | Modified Files | Tests | Code Review |
|-------|-------|-----------|---------------|-------|-------------|
| L0: Graph Foundation | 1-8 | 1 test file | 5 | 8 test classes | After Task 8 |
| L1: Quality | 9-14 | 2 (entity_filter.py, test) | 5 | 6 test classes | After Task 14 |
| L2: Nested Domain Tree | 15-19 | 1 (dependency_graph.py) + tests | 4 | 5 test classes | After Task 19 |
| L3: Overview | 20-22 | — | 3 | 3 test classes | After Task 22 (Final) |
| **Total** | **22 tasks** | **4 new files** | **14 modified files** | **22 test classes** | **4 reviews** |
