# Language Plugin Architecture — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the indexer's language support from hardcoded `if/elif` chains into a plugin-based architecture where each language is a self-contained module, with zero behavior regression.

**Architecture:** Define a `LanguagePlugin` Protocol that each language implements. A `PluginRegistry` discovers and manages plugins. `TreeSitterParser`, `CodeGraphBuilder`, and `ImportResolver` dispatch to plugins instead of branching on language strings. All existing constructors keep backward-compatible signatures via optional `registry` kwargs.

**Tech Stack:** Python 3.12+, tree-sitter, tree-sitter-language-pack, pytest

**Spec:** `docs/proposals/SPEC_20260502_132716_language_plugin_architecture.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `indexer/languages/__init__.py` | `LanguagePlugin` Protocol, `PluginRegistry`, `create_default_registry()` |
| `indexer/languages/_base.py` | `BaseLanguagePlugin` ABC with shared helpers (`_node_text`, `_truncate_code_snippet`, `_extract_block_comment_above`, `_extract_signature_generic`) |
| `indexer/languages/_jvm_common.py` | Shared JVM FQN computation, package extraction |
| `indexer/languages/python_lang.py` | `PythonPlugin` — all Python-specific parsing logic |
| `indexer/languages/java_lang.py` | `JavaPlugin` — all Java-specific parsing logic |
| `indexer/languages/go_lang.py` | `GoPlugin` — all Go-specific parsing logic |
| `indexer/languages/javascript_lang.py` | `JavaScriptPlugin` + `TypeScriptPlugin` |
| `tests/indexer/languages/__init__.py` | Test package |
| `tests/indexer/languages/test_plugin_registry.py` | Registry tests |
| `tests/indexer/languages/test_python_plugin.py` | Python plugin tests |
| `tests/indexer/languages/test_java_plugin.py` | Java plugin tests |
| `tests/indexer/languages/test_go_plugin.py` | Go plugin tests |
| `tests/indexer/languages/test_js_ts_plugin.py` | JS/TS plugin tests |

### Modified files

| File | Changes |
|------|---------|
| `indexer/tree_sitter_parser.py` | Accept `registry` kwarg, delegate extraction to plugins |
| `indexer/code_graph_builder.py` | Accept `registry` kwarg, delegate `compute_fqn` to plugins |
| `indexer/import_resolver.py` | Accept `registry` kwarg, delegate `resolve` and `build_file_index` to plugins |
| `core/config.py` | No change needed (values remain as defaults; registry overrides at runtime) |

---

## Task 1: LanguagePlugin Protocol + PluginRegistry

**Files:**
- Create: `indexer/languages/__init__.py`
- Test: `tests/indexer/languages/__init__.py`
- Test: `tests/indexer/languages/test_plugin_registry.py`

- [ ] **Step 1: Write the failing test for PluginRegistry**

```python
# tests/indexer/languages/test_plugin_registry.py
"""Tests for LanguagePlugin Protocol and PluginRegistry."""
from __future__ import annotations

import pytest

from indexer.languages import LanguagePlugin, PluginRegistry


class _StubPlugin:
    """Minimal plugin for registry tests."""
    name = "stub"
    file_extensions = [".stub"]
    interop_group = None

    def get_queries(self): return {}
    def extract_imports(self, tree, source, file_path): return []
    def extract_parameters(self, func_node, source): return []
    def extract_return_type(self, func_node, source): return ""
    def extract_signature(self, func_node, source): return ""
    def extract_base_classes(self, class_node, source): return [], []
    def extract_interfaces(self, class_node, source): return []
    def extract_receiver_expr(self, call_node, source): return ""
    def should_include_function(self, func_node): return True
    def extract_class_docstring(self, class_node, source): return ""
    def extract_function_docstring(self, func_node, source): return ""
    def extract_module_docstring(self, root_node, source): return ""
    def extract_field_comments(self, class_node, source): return {}
    def extract_annotations(self, node, source): return []
    def compute_fqn(self, file_path, entity_name, label, parent_class=""): return ""
    def build_module_name(self, file_path): return ""
    def resolve_import(self, import_path, source_file, file_index, reverse_index): return None
    def extract_fields(self, tree, source, file_path, result): return []


class _JvmStub(_StubPlugin):
    name = "jvm_a"
    file_extensions = [".jvma"]
    interop_group = "jvm"


class _JvmStub2(_StubPlugin):
    name = "jvm_b"
    file_extensions = [".jvmb"]
    interop_group = "jvm"


def test_register_and_lookup_by_name():
    reg = PluginRegistry()
    plugin = _StubPlugin()
    reg.register(plugin)
    assert reg.get_by_name("stub") is plugin
    assert reg.get_by_name("missing") is None


def test_lookup_by_extension():
    reg = PluginRegistry()
    plugin = _StubPlugin()
    reg.register(plugin)
    assert reg.get_by_extension(".stub") is plugin
    assert reg.get_by_extension(".xyz") is None


def test_interop_peers():
    reg = PluginRegistry()
    a = _JvmStub()
    b = _JvmStub2()
    standalone = _StubPlugin()
    reg.register(a)
    reg.register(b)
    reg.register(standalone)

    peers_a = reg.get_interop_peers(a)
    assert len(peers_a) == 1
    assert peers_a[0] is b

    peers_standalone = reg.get_interop_peers(standalone)
    assert peers_standalone == []


def test_supported_languages():
    reg = PluginRegistry()
    reg.register(_StubPlugin())
    reg.register(_JvmStub())
    assert "stub" in reg.supported_languages
    assert "jvm_a" in reg.supported_languages


def test_file_extensions_property():
    reg = PluginRegistry()
    reg.register(_StubPlugin())
    exts = reg.file_extensions
    assert exts["stub"] == [".stub"]


def test_isinstance_check():
    """Verify _StubPlugin satisfies LanguagePlugin Protocol at runtime."""
    assert isinstance(_StubPlugin(), LanguagePlugin)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/indexer/languages/test_plugin_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indexer.languages'`

- [ ] **Step 3: Create `indexer/languages/__init__.py` and `tests/indexer/languages/__init__.py`**

```python
# indexer/languages/__init__.py
"""Language plugin system for multi-language AST parsing.

Each language is implemented as a plugin conforming to the LanguagePlugin Protocol.
The PluginRegistry manages plugin discovery, lookup, and interop group resolution.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

    from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult


@runtime_checkable
class LanguagePlugin(Protocol):
    """Contract for a language support plugin."""

    @property
    def name(self) -> str: ...

    @property
    def file_extensions(self) -> list[str]: ...

    @property
    def interop_group(self) -> str | None: ...

    def get_queries(self) -> dict[str, str]: ...

    def extract_imports(
        self, tree: Tree, source: bytes, file_path: str,
    ) -> list[ParsedImport]: ...

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]: ...

    def extract_return_type(self, func_node: Node, source: bytes) -> str: ...

    def extract_signature(self, func_node: Node, source: bytes) -> str: ...

    def extract_base_classes(
        self, class_node: Node, source: bytes,
    ) -> tuple[list[str], list[str]]: ...

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]: ...

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str: ...

    def should_include_function(self, func_node: Node) -> bool: ...

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str: ...

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str: ...

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str: ...

    def extract_field_comments(
        self, class_node: Node, source: bytes,
    ) -> dict[str, str]: ...

    def extract_annotations(self, node: Node, source: bytes) -> list[str]: ...

    def compute_fqn(
        self, file_path: str, entity_name: str,
        label: str, parent_class: str = "",
    ) -> str: ...

    def build_module_name(self, file_path: str) -> str: ...

    def resolve_import(
        self, import_path: str, source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None: ...

    def extract_fields(
        self, tree: Tree, source: bytes, file_path: str, result: ParseResult,
    ) -> list[ParsedField]: ...


class PluginRegistry:
    """Registry for language plugins with interop group lookup."""

    def __init__(self) -> None:
        self._plugins: dict[str, LanguagePlugin] = {}
        self._ext_to_plugin: dict[str, LanguagePlugin] = {}

    def register(self, plugin: LanguagePlugin) -> None:
        self._plugins[plugin.name] = plugin
        for ext in plugin.file_extensions:
            self._ext_to_plugin[ext] = plugin

    def get_by_name(self, name: str) -> LanguagePlugin | None:
        return self._plugins.get(name)

    def get_by_extension(self, ext: str) -> LanguagePlugin | None:
        return self._ext_to_plugin.get(ext)

    def get_interop_peers(self, plugin: LanguagePlugin) -> list[LanguagePlugin]:
        if not plugin.interop_group:
            return []
        return [
            p for p in self._plugins.values()
            if p.interop_group == plugin.interop_group and p.name != plugin.name
        ]

    @property
    def all_plugins(self) -> list[LanguagePlugin]:
        return list(self._plugins.values())

    @property
    def supported_languages(self) -> list[str]:
        return list(self._plugins.keys())

    @property
    def file_extensions(self) -> dict[str, list[str]]:
        return {p.name: list(p.file_extensions) for p in self._plugins.values()}


def create_default_registry(languages: list[str] | None = None) -> PluginRegistry:
    """Create registry with all (or filtered) built-in language plugins."""
    from indexer.languages.go_lang import GoPlugin
    from indexer.languages.java_lang import JavaPlugin
    from indexer.languages.javascript_lang import JavaScriptPlugin, TypeScriptPlugin
    from indexer.languages.python_lang import PythonPlugin

    all_plugins: list[LanguagePlugin] = [
        PythonPlugin(), JavaPlugin(), GoPlugin(),
        JavaScriptPlugin(), TypeScriptPlugin(),
    ]

    registry = PluginRegistry()
    for plugin in all_plugins:
        if languages is None or plugin.name in languages:
            registry.register(plugin)
    return registry
```

```python
# tests/indexer/languages/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/indexer/languages/test_plugin_registry.py -v`
Expected: PASS (except `create_default_registry` test which will fail until plugins exist — that's OK, the registry tests should pass)

- [ ] **Step 5: Commit**

```bash
git add indexer/languages/__init__.py tests/indexer/languages/
git commit -m "feat: add LanguagePlugin Protocol and PluginRegistry"
```

---

## Task 2: BaseLanguagePlugin with Shared Helpers

**Files:**
- Create: `indexer/languages/_base.py`

- [ ] **Step 1: Create BaseLanguagePlugin ABC**

```python
# indexer/languages/_base.py
"""Base class for language plugins with shared AST helper methods."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

    from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult

_LICENSE_KEYWORDS: frozenset[str] = frozenset({
    "copyright", "licensed", "license", "apache", "mit license",
    "gpl", "bsd", "mozilla", "all rights reserved",
})


class BaseLanguagePlugin(ABC):
    """ABC providing shared helpers. Subclasses implement language-specific logic."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]: ...

    @property
    def interop_group(self) -> str | None:
        return None

    @abstractmethod
    def get_queries(self) -> dict[str, str]: ...

    @abstractmethod
    def extract_imports(
        self, tree: Tree, source: bytes, file_path: str,
    ) -> list[ParsedImport]: ...

    @abstractmethod
    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]: ...

    @abstractmethod
    def extract_return_type(self, func_node: Node, source: bytes) -> str: ...

    @abstractmethod
    def extract_base_classes(
        self, class_node: Node, source: bytes,
    ) -> tuple[list[str], list[str]]: ...

    @abstractmethod
    def compute_fqn(
        self, file_path: str, entity_name: str,
        label: str, parent_class: str = "",
    ) -> str: ...

    @abstractmethod
    def build_module_name(self, file_path: str) -> str: ...

    @abstractmethod
    def resolve_import(
        self, import_path: str, source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None: ...

    # --- Default implementations for optional methods ---

    def extract_signature(self, func_node: Node, source: bytes) -> str:
        return self._extract_signature_generic(func_node, source)

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
        return []

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        return ""

    def should_include_function(self, func_node: Node) -> bool:
        return True

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return ""

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return ""

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        return ""

    def extract_field_comments(
        self, class_node: Node, source: bytes,
    ) -> dict[str, str]:
        return {}

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        return []

    def extract_fields(
        self, tree: Tree, source: bytes, file_path: str, result: ParseResult,
    ) -> list[ParsedField]:
        return []

    # --- Shared static helpers ---

    @staticmethod
    def _node_text(node: Node | None) -> str:
        if node is None or not node.text:
            return ""
        return node.text.decode("utf-8")

    @staticmethod
    def _truncate_code_snippet(code_snippet: str, max_len: int = 5000) -> str:
        if len(code_snippet) <= max_len:
            return code_snippet
        total = len(code_snippet)
        return code_snippet[:3000] + f"\n# ... truncated ({total} total chars)"

    @staticmethod
    def _is_license_comment(text: str) -> bool:
        lower = text.lower()[:500]
        return sum(1 for kw in _LICENSE_KEYWORDS if kw in lower) >= 2

    @staticmethod
    def _strip_string_delimiters(raw: str) -> str:
        s = raw.strip()
        if len(s) >= 2 and s[0] in "'\"`" and s[-1] == s[0]:
            return s[1:-1]
        return s

    def _extract_signature_generic(self, node: Node, source: bytes) -> str:
        """Extract function signature — text from declaration start to body start."""
        body_types = frozenset({
            "block", "class_body", "statement_block", "constructor_body",
            "method_body", "function_body", "compound_statement",
            "code_block", "statements",
        })
        start = node.start_byte
        for child in node.children:
            if child.type in body_types:
                end = child.start_byte
                return source[start:end].decode("utf-8").strip()
        first_line_end = source.find(b"\n", start)
        if first_line_end == -1:
            first_line_end = node.end_byte
        return source[start:first_line_end].decode("utf-8").strip()

    def _extract_block_comment_above(self, node: Node) -> str:
        """Extract /** */ or // doc comment above a declaration node."""
        prev = node.prev_named_sibling
        while prev and prev.type in (
            "decorator", "annotation", "marker_annotation",
            "modifiers", "module_attribute",
        ):
            prev = prev.prev_named_sibling
        if prev and prev.type in ("comment", "block_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            return raw.strip("/* \n\t")
        return ""

    @staticmethod
    def _pick_from_reverse(reverse_index: dict[str, list[str]], key: str) -> str | None:
        paths = reverse_index.get(key)
        if not paths:
            return None
        return sorted(paths)[0]

    @staticmethod
    def _finalize_import_symbols(imp: ParsedImport) -> None:
        """Populate symbols list from names/module when not explicitly set."""
        if imp.symbols:
            return
        if imp.names:
            imp.symbols = list(imp.names)
            return
        if imp.language == "java" and imp.module:
            simple = imp.module.rsplit(".", 1)[-1]
            if simple and simple[0].isupper():
                imp.symbols = [simple]
```

- [ ] **Step 2: Verify no import errors**

Run: `uv run python -c "from indexer.languages._base import BaseLanguagePlugin; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add indexer/languages/_base.py
git commit -m "feat: add BaseLanguagePlugin ABC with shared helpers"
```

---

## Task 3: PythonPlugin

**Files:**
- Create: `indexer/languages/python_lang.py`
- Test: `tests/indexer/languages/test_python_plugin.py`

- [ ] **Step 1: Write the failing test for PythonPlugin**

```python
# tests/indexer/languages/test_python_plugin.py
"""Tests for PythonPlugin — extracted from test_tree_sitter_parser.py."""
from __future__ import annotations

import pytest

from indexer.languages.python_lang import PythonPlugin
from indexer.languages import LanguagePlugin


def test_isinstance_protocol():
    assert isinstance(PythonPlugin(), LanguagePlugin)


def test_properties():
    p = PythonPlugin()
    assert p.name == "python"
    assert ".py" in p.file_extensions
    assert p.interop_group is None


def test_get_queries_has_all_keys():
    q = PythonPlugin().get_queries()
    assert set(q.keys()) >= {"function", "class", "import", "call"}


def test_compute_fqn_function():
    p = PythonPlugin()
    assert p.compute_fqn("utils/helper.py", "do_stuff", "Function") == "utils.helper.do_stuff"


def test_compute_fqn_class():
    p = PythonPlugin()
    assert p.compute_fqn("models/user.py", "User", "Class") == "models.user.User"


def test_compute_fqn_method():
    p = PythonPlugin()
    fqn = p.compute_fqn("models/user.py", "save", "Function", parent_class="User")
    assert fqn == "models.user.User.save"


def test_build_module_name():
    p = PythonPlugin()
    assert p.build_module_name("foo/bar.py") == "foo.bar"
    assert p.build_module_name("pkg/__init__.py") == "pkg"


def test_resolve_import_absolute():
    p = PythonPlugin()
    fi = {"foo/bar.py": "foo.bar"}
    ri = {"foo.bar": ["foo/bar.py"]}
    assert p.resolve_import("foo.bar", "main.py", fi, ri) == "foo/bar.py"


def test_resolve_import_relative():
    p = PythonPlugin()
    fi = {"app/pkg/models.py": "app.pkg.models"}
    ri = {"app.pkg.models": ["app/pkg/models.py"]}
    assert p.resolve_import(".models", "app/pkg/runner.py", fi, ri) == "app/pkg/models.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/indexer/languages/test_python_plugin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indexer.languages.python_lang'`

- [ ] **Step 3: Implement PythonPlugin**

Extract all Python-specific logic from `indexer/tree_sitter_parser.py` into `indexer/languages/python_lang.py`. The plugin must reproduce identical behavior for:
- `LANGUAGE_QUERIES["python"]`
- `_extract_imports_python` → `extract_imports`
- `_extract_parameters_python` → `extract_parameters`
- `_extract_return_type` (python branch) → `extract_return_type`
- `_extract_docstring` (python branch) → `extract_class_docstring` / `extract_function_docstring`
- `_extract_module_docstring` (python branch) → `extract_module_docstring`
- `_extract_decorators` (python branch) → `extract_annotations`
- `_python_module_from_file` → `compute_fqn`
- `build_file_index` (python branch) → `build_module_name`
- `_resolve_python` + `_resolve_python_relative` → `resolve_import`

The file will be ~350-400 lines. All Python-specific helper methods (`_python_dotted_name_text`, `_python_import_from_module_string`, `_python_from_import_bindings`, etc.) move into the plugin class.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/indexer/languages/test_python_plugin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/languages/python_lang.py tests/indexer/languages/test_python_plugin.py
git commit -m "feat: extract PythonPlugin from tree_sitter_parser"
```

---

## Task 4: JavaPlugin + JVM Common

**Files:**
- Create: `indexer/languages/_jvm_common.py`
- Create: `indexer/languages/java_lang.py`
- Test: `tests/indexer/languages/test_java_plugin.py`

- [ ] **Step 1: Write the failing test for JavaPlugin**

```python
# tests/indexer/languages/test_java_plugin.py
"""Tests for JavaPlugin."""
from __future__ import annotations

from indexer.languages.java_lang import JavaPlugin
from indexer.languages import LanguagePlugin


def test_isinstance_protocol():
    assert isinstance(JavaPlugin(), LanguagePlugin)


def test_properties():
    p = JavaPlugin()
    assert p.name == "java"
    assert ".java" in p.file_extensions
    assert p.interop_group == "jvm"


def test_get_queries_has_all_keys():
    q = JavaPlugin().get_queries()
    assert set(q.keys()) >= {"function", "class", "import", "call"}


def test_compute_fqn_class():
    p = JavaPlugin()
    fqn = p.compute_fqn(
        "src/main/java/com/example/UserService.java",
        "UserService", "Class",
    )
    assert fqn == "com.example.UserService"


def test_compute_fqn_method():
    p = JavaPlugin()
    fqn = p.compute_fqn(
        "src/main/java/com/example/UserService.java",
        "findById", "Function", parent_class="UserService",
    )
    assert fqn == "com.example.UserService#findById"


def test_build_module_name():
    p = JavaPlugin()
    name = p.build_module_name("src/main/java/com/example/Foo.java")
    assert name == "src.main.java.com.example.Foo"


def test_resolve_import():
    p = JavaPlugin()
    fi = {"src/main/java/com/example/service/UserService.java": "src.main.java.com.example.service.UserService"}
    ri = {"src.main.java.com.example.service.UserService": ["src/main/java/com/example/service/UserService.java"]}
    result = p.resolve_import(
        "com.example.service.UserService",
        "com/example/App.java", fi, ri,
    )
    assert result == "src/main/java/com/example/service/UserService.java"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/indexer/languages/test_java_plugin.py -v`
Expected: FAIL

- [ ] **Step 3: Create `_jvm_common.py`**

```python
# indexer/languages/_jvm_common.py
"""Shared JVM utilities for Java and Kotlin plugins."""
from __future__ import annotations

_JVM_SRC_MARKERS = ("src/main/java/", "src/test/java/", "src/main/kotlin/", "src/test/kotlin/")


def compute_jvm_fqn(
    file_path: str,
    entity_name: str,
    *,
    is_method: bool = False,
    parent_class: str = "",
    file_suffix: str = ".java",
) -> str:
    """Derive a JVM fully-qualified name from the file path."""
    for marker in _JVM_SRC_MARKERS:
        idx = file_path.find(marker)
        if idx == -1:
            continue
        rel = file_path[idx + len(marker):]
        class_fqn = rel.replace("/", ".").removesuffix(file_suffix)
        if is_method:
            if parent_class:
                return f"{class_fqn}#{entity_name}"
            pkg = class_fqn.rsplit(".", 1)[0] if "." in class_fqn else ""
            return f"{pkg}.{entity_name}" if pkg else entity_name
        return class_fqn
    return ""
```

- [ ] **Step 4: Implement JavaPlugin**

Extract all Java-specific logic from `tree_sitter_parser.py` into `indexer/languages/java_lang.py`. This includes:
- `LANGUAGE_QUERIES["java"]`
- `_extract_java_annotations_from_node` → `extract_annotations`
- `_extract_parameters_java` → `extract_parameters`
- `_extract_return_type` (java branch) → `extract_return_type`
- `_extract_base_classes` (java branches: `superclass`, `extends_interfaces`, `super_interfaces`) → `extract_base_classes`
- `_extract_interfaces` (java) → `extract_interfaces`
- `_extract_java_fields` → `extract_fields`
- `_extract_docstring` (java branch) → `extract_class_docstring` / `extract_function_docstring`
- `_extract_file_header_comment` (java) → `extract_module_docstring`
- `_extract_receiver_expr` (java branch) → `extract_receiver_expr`
- `compute_java_fqn` → `compute_fqn` (delegates to `_jvm_common`)
- `build_file_index` (java branch) → `build_module_name`
- `_resolve_java` → `resolve_import`

Also move Java DI-related constants (`_JAVA_DI_NON_BEAN_SIMPLE_TYPES`, `_java_field_is_private_final_bean_candidate`, etc.) into the plugin.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/indexer/languages/test_java_plugin.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add indexer/languages/_jvm_common.py indexer/languages/java_lang.py tests/indexer/languages/test_java_plugin.py
git commit -m "feat: extract JavaPlugin with JVM common utilities"
```

---

## Task 5: GoPlugin

**Files:**
- Create: `indexer/languages/go_lang.py`
- Test: `tests/indexer/languages/test_go_plugin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/indexer/languages/test_go_plugin.py
"""Tests for GoPlugin."""
from __future__ import annotations

from indexer.languages.go_lang import GoPlugin
from indexer.languages import LanguagePlugin


def test_isinstance_protocol():
    assert isinstance(GoPlugin(), LanguagePlugin)


def test_properties():
    p = GoPlugin()
    assert p.name == "go"
    assert ".go" in p.file_extensions
    assert p.interop_group is None


def test_get_queries_has_all_keys():
    q = GoPlugin().get_queries()
    assert set(q.keys()) >= {"function", "class", "import", "call"}


def test_compute_fqn_function():
    p = GoPlugin()
    fqn = p.compute_fqn("pkg/utils/helper.go", "DoStuff", "Function")
    assert fqn == "utils.DoStuff"


def test_compute_fqn_struct():
    p = GoPlugin()
    fqn = p.compute_fqn("pkg/models/user.go", "User", "Class")
    assert fqn == "models.User"


def test_build_module_name():
    p = GoPlugin()
    assert p.build_module_name("pkg/utils/helper.go") == "pkg.utils.helper"


def test_resolve_import():
    p = GoPlugin()
    fi = {"vendor/github.com/example/pkg/utils/foo.go": "vendor.github.com.example.pkg.utils.foo"}
    ri = {}
    result = p.resolve_import(
        "github.com/example/pkg/utils",
        "cmd/main.go", fi, ri,
    )
    assert result == "vendor/github.com/example/pkg/utils/foo.go"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/indexer/languages/test_go_plugin.py -v`
Expected: FAIL

- [ ] **Step 3: Implement GoPlugin**

Extract Go-specific logic: `LANGUAGE_QUERIES["go"]`, `_extract_parameters_go`, `_extract_return_type_go`, `_go_package_from_file`, `_resolve_go`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/indexer/languages/test_go_plugin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/languages/go_lang.py tests/indexer/languages/test_go_plugin.py
git commit -m "feat: extract GoPlugin"
```

---

## Task 6: JavaScriptPlugin + TypeScriptPlugin

**Files:**
- Create: `indexer/languages/javascript_lang.py`
- Test: `tests/indexer/languages/test_js_ts_plugin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/indexer/languages/test_js_ts_plugin.py
"""Tests for JavaScriptPlugin and TypeScriptPlugin."""
from __future__ import annotations

from indexer.languages.javascript_lang import JavaScriptPlugin, TypeScriptPlugin
from indexer.languages import LanguagePlugin


def test_isinstance_protocol():
    assert isinstance(JavaScriptPlugin(), LanguagePlugin)
    assert isinstance(TypeScriptPlugin(), LanguagePlugin)


def test_js_properties():
    p = JavaScriptPlugin()
    assert p.name == "javascript"
    assert ".js" in p.file_extensions
    assert p.interop_group == "js"


def test_ts_properties():
    p = TypeScriptPlugin()
    assert p.name == "typescript"
    assert ".ts" in p.file_extensions
    assert p.interop_group == "js"


def test_compute_fqn_function():
    p = JavaScriptPlugin()
    fqn = p.compute_fqn("src/utils/helper.js", "doStuff", "Function")
    assert fqn == "src/utils/helper.doStuff"


def test_compute_fqn_ts_class():
    p = TypeScriptPlugin()
    fqn = p.compute_fqn("src/models/User.ts", "User", "Class")
    assert fqn == "src/models/User.User"


def test_build_module_name_index_file():
    p = TypeScriptPlugin()
    assert p.build_module_name("src/components/index.ts") == "src.components"


def test_resolve_import_relative():
    p = TypeScriptPlugin()
    fi = {"src/utils/helper.ts": "src.utils.helper"}
    ri = {"src.utils.helper": ["src/utils/helper.ts"]}
    result = p.resolve_import("./utils/helper", "src/app.tsx", fi, ri)
    assert result == "src/utils/helper.ts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/indexer/languages/test_js_ts_plugin.py -v`
Expected: FAIL

- [ ] **Step 3: Implement JavaScriptPlugin + TypeScriptPlugin**

Extract JS/TS-specific logic. `TypeScriptPlugin` inherits from `JavaScriptPlugin`, overriding `name`, `file_extensions`, and `get_queries()` (TypeScript uses `type_identifier` for class names vs `identifier`).

Key JS/TS-specific methods:
- `_is_module_level`, `_lexical_declaration_for_arrow_binding` → `should_include_function`
- `_parsed_import_js_ts`, `_js_ts_import_clause_symbols` → `extract_imports`
- `_extract_parameters_ts_js` → `extract_parameters`
- `_extract_receiver_expr` (JS/TS branch) → `extract_receiver_expr`
- `_js_ts_module_prefix` → `compute_fqn`
- `_resolve_js_ts` → `resolve_import`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/indexer/languages/test_js_ts_plugin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indexer/languages/javascript_lang.py tests/indexer/languages/test_js_ts_plugin.py
git commit -m "feat: extract JavaScriptPlugin and TypeScriptPlugin"
```

---

## Task 7: Refactor TreeSitterParser to Use PluginRegistry

**Files:**
- Modify: `indexer/tree_sitter_parser.py`
- Existing test: `tests/test_tree_sitter_parser.py` (must still pass unchanged)

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `uv run pytest tests/test_tree_sitter_parser.py -v`
Expected: All PASS — record exact count

- [ ] **Step 2: Modify TreeSitterParser.__init__ to accept registry**

Add optional `registry` kwarg. When provided, use it for dispatch. When not provided, create one from `supported_languages`. This preserves backward compatibility.

Key changes to `TreeSitterParser`:
1. `__init__`: Accept `registry: PluginRegistry | None = None`
2. `_extract_functions`: Use `plugin.extract_parameters`, `plugin.extract_return_type`, `plugin.extract_function_docstring`, `plugin.extract_signature`, `plugin.extract_annotations`, `plugin.should_include_function`
3. `_extract_classes`: Use `plugin.extract_class_docstring`, `plugin.extract_base_classes`, `plugin.extract_interfaces`, `plugin.extract_annotations`
4. `_extract_imports`: Delegate entirely to `plugin.extract_imports`
5. `_extract_calls`: Use `plugin.extract_receiver_expr`
6. `_extract_module_docstring`: Delegate to `plugin.extract_module_docstring`
7. `parse_file`: Use `plugin.extract_fields` for field extraction (removing Java-only `if`)
8. Keep `LANGUAGE_QUERIES` as a module-level computed dict for backward compatibility

The existing language-specific methods (`_extract_imports_python`, `_extract_parameters_java`, etc.) remain in the file temporarily for backward compatibility but are no longer called by the main flow. They will be removed in a cleanup step after all tests pass.

- [ ] **Step 3: Run existing tests to verify zero regression**

Run: `uv run pytest tests/test_tree_sitter_parser.py -v`
Expected: All PASS with identical count to Step 1

- [ ] **Step 4: Commit**

```bash
git add indexer/tree_sitter_parser.py
git commit -m "refactor: TreeSitterParser dispatches to PluginRegistry"
```

---

## Task 8: Refactor CodeGraphBuilder to Use PluginRegistry

**Files:**
- Modify: `indexer/code_graph_builder.py`
- Existing test: `tests/test_cross_file_resolution.py` (must still pass)

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `uv run pytest tests/test_cross_file_resolution.py -v`
Expected: All PASS

- [ ] **Step 2: Modify CodeGraphBuilder and compute_fqn**

Add optional `registry` kwarg to `CodeGraphBuilder.__init__`. Modify `compute_fqn()` module-level function to accept optional `registry` kwarg and dispatch to plugin when available. Keep existing if/elif chains as fallback when `registry` is None.

- [ ] **Step 3: Run existing tests to verify zero regression**

Run: `uv run pytest tests/test_cross_file_resolution.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add indexer/code_graph_builder.py
git commit -m "refactor: CodeGraphBuilder delegates FQN to PluginRegistry"
```

---

## Task 9: Refactor ImportResolver to Use PluginRegistry

**Files:**
- Modify: `indexer/import_resolver.py`
- Existing test: `tests/indexer/test_import_resolver.py` (must still pass)

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `uv run pytest tests/indexer/test_import_resolver.py -v`
Expected: All PASS

- [ ] **Step 2: Modify ImportResolver**

Add optional `registry` kwarg to `__init__`. Modify `resolve()` to dispatch to plugin when registry is available, with interop group fallback. Modify `build_file_index()` to delegate to `plugin.build_module_name()` when registry is available. Keep existing methods as `_legacy_*` fallbacks.

- [ ] **Step 3: Run existing tests to verify zero regression**

Run: `uv run pytest tests/indexer/test_import_resolver.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add indexer/import_resolver.py
git commit -m "refactor: ImportResolver delegates to PluginRegistry with interop"
```

---

## Task 10: Full Regression Test Suite

**Files:**
- No new files

- [ ] **Step 1: Run the FULL test suite**

Run: `uv run pytest --tb=short -q`
Expected: All tests pass with the same count as before refactoring

- [ ] **Step 2: If any failures, fix them**

Each failure should be traced to a dispatch mismatch between old if/elif logic and new plugin methods. Fix by adjusting the plugin implementation to match original behavior exactly.

- [ ] **Step 3: Remove dead code from TreeSitterParser**

After all tests pass, remove the now-unused language-specific methods from `tree_sitter_parser.py` that have been extracted into plugins. Keep only the generic dispatch logic.

**Do NOT remove**: `LANGUAGE_QUERIES` dict (backward compat), dataclass definitions (`ParsedFunction`, `ParsedClass`, etc.), `ParseResult`, `_is_license_comment`.

- [ ] **Step 4: Run full test suite again**

Run: `uv run pytest --tb=short -q`
Expected: All tests still pass

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "refactor: complete Phase 1 — language plugin architecture"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `uv run pytest --tb=short -q` — all tests pass
- [ ] `uv run python -c "from indexer.languages import create_default_registry; r = create_default_registry(); print(r.supported_languages)"` — prints `['python', 'java', 'go', 'javascript', 'typescript']`
- [ ] `uv run python -c "from indexer.languages import create_default_registry; r = create_default_registry(['python']); print(r.supported_languages)"` — prints `['python']`
- [ ] `uv run python -c "from indexer.tree_sitter_parser import TreeSitterParser; p = TreeSitterParser(['python']); print('OK')"` — backward compatible constructor
- [ ] `uv run python -c "from indexer.tree_sitter_parser import LANGUAGE_QUERIES; print(list(LANGUAGE_QUERIES.keys()))"` — backward compatible dict
