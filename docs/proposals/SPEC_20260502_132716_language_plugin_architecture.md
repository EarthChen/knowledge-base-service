# SPEC: Language Plugin Architecture

> **Status**: Draft — Awaiting Approval  
> **Created**: 2026-05-02  
> **Scope**: Backend (indexer subsystem)  
> **Approach**: Plugin-based Refactor (Option B)  
> **Phases**: 3

---

## 1. Background

### 1.1 Current State

The indexer subsystem supports 5 languages (Python, Java, Go, JavaScript, TypeScript) via:

- **`indexer/tree_sitter_parser.py`** — `LANGUAGE_QUERIES` dict + language-specific branching in `_extract_imports`, `_extract_docstring`, `_extract_decorators`, `_extract_parameters`, `_extract_return_type`
- **`indexer/code_graph_builder.py`** — `compute_fqn()` with per-language `if/elif` chains
- **`indexer/import_resolver.py`** — `resolve()` with per-language `_resolve_*` methods
- **`core/config.py`** — `supported_languages` and `file_extensions` hardcoded defaults

### 1.2 Problem

Adding each new language requires touching 4+ files and extending multiple `if/elif` chains. Client platform projects (Android, iOS, Flutter) commonly involve **multi-language codebases** (Java+Kotlin, ObjC+Swift, Dart+native), requiring cross-language import resolution.

### 1.3 Goal

Add support for **Kotlin, Swift, Objective-C, Dart** while refactoring the existing architecture into a plugin system where each language is a self-contained module.

---

## 2. Design

### 2.1 LanguagePlugin Protocol

```python
# indexer/languages/__init__.py

from __future__ import annotations
from typing import Protocol, runtime_checkable
from tree_sitter import Node

@runtime_checkable
class LanguagePlugin(Protocol):
    """Contract for a language support plugin."""

    @property
    def name(self) -> str:
        """Canonical language name, e.g. 'kotlin'."""
        ...

    @property
    def file_extensions(self) -> list[str]:
        """File extensions including dot, e.g. ['.kt', '.kts']."""
        ...

    @property
    def interop_group(self) -> str | None:
        """Cross-language interop group: 'jvm', 'apple', 'js', or None."""
        ...

    # --- Tree-sitter queries ---

    def get_queries(self) -> dict[str, str]:
        """Return Tree-sitter queries: {function, class, import, call}."""
        ...

    # --- Structure extraction ---

    def extract_imports(
        self, tree: Tree, source: bytes, file_path: str
    ) -> list[ParsedImport]:
        """Extract all import statements from the AST."""
        ...

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        """Extract function parameter names and types."""
        ...

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        """Extract function return type."""
        ...

    def extract_signature(self, func_node: Node, source: bytes) -> str:
        """Extract function signature (text from declaration to body start).
        
        Uses body_node_types to locate the body node and slice the source."""
        ...

    def extract_base_classes(
        self, class_node: Node, source: bytes
    ) -> tuple[list[str], list[str]]:
        """Return (base_classes, generic_type_params)."""
        ...

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
        """Extract implemented interfaces/protocols."""
        ...

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        """Extract receiver/object expression from a method call node.
        
        Returns e.g. 'userService' from 'userService.findById()', or '' for plain calls."""
        ...

    def should_include_function(self, func_node: Node) -> bool:
        """Return True if this function node should be included in parse results.
        
        Used for language-specific filtering, e.g. JS/TS filters out
        non-module-level arrow functions."""
        ...

    # --- Comment extraction (separated by entity type) ---

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        """Extract class-level documentation comment."""
        ...

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        """Extract function-level documentation comment."""
        ...

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        """Extract file-level documentation comment."""
        ...

    def extract_field_comments(
        self, class_node: Node, source: bytes
    ) -> dict[str, str]:
        """Extract per-field/property comments: {field_name: comment}."""
        ...

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        """Extract annotations/decorators/attributes."""
        ...

    # --- Naming and resolution ---

    def compute_fqn(
        self, file_path: str, entity_name: str,
        label: str, parent_class: str = ""
    ) -> str:
        """Compute fully-qualified name from file path and entity."""
        ...

    def build_module_name(self, file_path: str) -> str:
        """Convert a file path to its module-style dotted name for the import index.
        
        E.g. 'src/main/java/com/example/Foo.java' -> 'src.main.java.com.example.Foo'
        Or  'utils/helper.py' -> 'utils.helper'
        """
        ...

    def resolve_import(
        self, import_path: str, source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]]
    ) -> str | None:
        """Resolve an import string to a relative file path.
        
        Receives both file_index (path -> module name) and
        reverse_index (module name -> paths) pre-built by ImportResolver."""
        ...

    # --- Optional: language-specific field extraction ---

    def extract_fields(
        self, tree: Tree, source: bytes, file_path: str, result: ParseResult
    ) -> list[ParsedField]:
        """Extract class fields/properties (Java fields, Kotlin properties, etc.).
        
        Default: returns empty list. Override for languages with field-level DI or annotations."""
        ...
```

### 2.2 Plugin Registry

```python
# indexer/languages/__init__.py (continued)

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
        """Return other plugins in the same interop group."""
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
    """Create registry with all (or specified) language plugins."""
    from indexer.languages.python_lang import PythonPlugin
    from indexer.languages.java_lang import JavaPlugin
    from indexer.languages.go_lang import GoPlugin
    from indexer.languages.javascript_lang import JavaScriptPlugin, TypeScriptPlugin
    # Phase 2/3 imports added when available:
    # from indexer.languages.kotlin import KotlinPlugin
    # from indexer.languages.swift import SwiftPlugin
    # from indexer.languages.objc import ObjCPlugin
    # from indexer.languages.dart import DartPlugin

    ALL_PLUGINS = [
        PythonPlugin(), JavaPlugin(), GoPlugin(),
        JavaScriptPlugin(), TypeScriptPlugin(),
    ]

    registry = PluginRegistry()
    for plugin in ALL_PLUGINS:
        if languages is None or plugin.name in languages:
            registry.register(plugin)
    return registry
```

### 2.3 Directory Structure

```
indexer/
  languages/
    __init__.py           # LanguagePlugin Protocol, PluginRegistry, create_default_registry
    _base.py              # BaseLanguagePlugin with shared helpers (_node_text, _truncate, etc.)
    _jvm_common.py        # Shared JVM FQN computation, package resolution
    _apple_common.py      # Shared Apple module resolution (bridging header awareness)
    python_lang.py        # PythonPlugin
    java_lang.py          # JavaPlugin (interop_group="jvm")
    go_lang.py            # GoPlugin
    javascript_lang.py    # JavaScriptPlugin + TypeScriptPlugin (interop_group="js")
    kotlin_lang.py        # KotlinPlugin (interop_group="jvm") — Phase 2
    swift_lang.py         # SwiftPlugin (interop_group="apple") — Phase 2
    objc_lang.py          # ObjCPlugin (interop_group="apple") — Phase 3
    dart_lang.py          # DartPlugin — Phase 3
```

### 2.4 Integration Points

#### 2.4.1 TreeSitterParser Refactor

`TreeSitterParser` becomes a thin dispatcher:

```python
class TreeSitterParser:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry
        self._parsers: dict[str, Parser] = {}
        self._init_parsers()

    def _init_parsers(self) -> None:
        for plugin in self._registry.all_plugins:
            try:
                self._parsers[plugin.name] = get_parser(plugin.name)
            except LookupError:
                log.warning("tree_sitter_language_not_found", language=plugin.name)

    def parse_file(self, file_path: str, language: str, content: str | None = None) -> ParseResult:
        plugin = self._registry.get_by_name(language)
        if plugin is None or language not in self._parsers:
            return ParseResult()

        # Parse tree
        source_bytes = (content or Path(file_path).read_text(...)).encode("utf-8")
        tree = self._parsers[language].parse(source_bytes)

        # Delegate to plugin
        result = ParseResult()
        queries = plugin.get_queries()
        result.classes = self._extract_classes(tree, source_bytes, file_path, plugin)
        result.functions = self._extract_functions(tree, source_bytes, file_path, plugin)
        result.imports = plugin.extract_imports(tree, source_bytes, file_path)
        result.calls = self._extract_calls(tree, source_bytes, file_path, plugin, result)
        result.fields = plugin.extract_fields(tree, source_bytes, file_path, result)
        result.module_docstring = plugin.extract_module_docstring(tree.root_node, source_bytes)
        self._classify_methods(result)
        return result
```

#### 2.4.2 CodeGraphBuilder Refactor

`compute_fqn()` dispatches to plugin:

```python
def compute_fqn(file_path: str, entity_name: str, label: str,
                parent_class: str = "", *, registry: PluginRegistry) -> str:
    ext = Path(file_path).suffix
    plugin = registry.get_by_extension(ext)
    if plugin is None:
        return ""
    return plugin.compute_fqn(file_path, entity_name, label, parent_class)
```

#### 2.4.3 ImportResolver Refactor

`resolve()` dispatches to plugin, with interop group fallback. `build_file_index()` delegates to plugin's `build_module_name()`:

```python
class ImportResolver:
    def __init__(self, file_index: dict[str, str], registry: PluginRegistry | None = None) -> None:
        self._file_index = file_index
        self._registry = registry
        self._reverse_index: dict[str, list[str]] = {}
        self._build_reverse_index()

    @staticmethod
    def build_file_index(
        file_paths: list[str], registry: PluginRegistry | None = None
    ) -> dict[str, str]:
        """Convert file paths to module-style names, delegating to plugins."""
        out: dict[str, str] = {}
        for raw in file_paths:
            if registry:
                ext = Path(raw).suffix
                plugin = registry.get_by_extension(ext)
                if plugin:
                    out[raw] = plugin.build_module_name(raw)
                    continue
            # Fallback to existing if/elif logic for backward compatibility
            out[raw] = _legacy_build_module_name(raw)
        return out

    def resolve(self, import_path: str, source_file: str, language: str) -> str | None:
        if self._registry:
            plugin = self._registry.get_by_name(language)
            if plugin is None:
                return None

            # 1. Try same-language resolution
            result = plugin.resolve_import(
                import_path, source_file, self._file_index, self._reverse_index
            )
            if result:
                return result

            # 2. Try interop group peers (e.g. Java→Kotlin, Swift→ObjC)
            for peer in self._registry.get_interop_peers(plugin):
                result = peer.resolve_import(
                    import_path, source_file, self._file_index, self._reverse_index
                )
                if result:
                    return result

            return None
        
        # Legacy fallback (no registry)
        return self._legacy_resolve(import_path, source_file, language)
```

#### 2.4.4 Config Update

`core/config.py` `supported_languages` and `file_extensions` become derived from the registry. The config fields remain for backward compatibility but the registry is the source of truth at runtime.

---

### 2.5 Cross-Language Interop

| Group | Languages | Interop Mechanism | Resolution Strategy |
|-------|-----------|------------------|---------------------|
| `jvm` | Java, Kotlin | Full JVM bytecode interop | Shared FQN namespace (`package.Class`), resolve across `.java`/`.kt` |
| `apple` | Swift, Objective-C | Bridging Headers | Module-level import, resolve across `.swift`/`.h`/`.m` |
| `js` | JavaScript, TypeScript | Native interop | Already shared, resolve across `.js`/`.ts`/`.jsx`/`.tsx` |
| _(none)_ | Dart | Platform Channels (MethodChannel) | Best-effort: detect `MethodChannel` calls, tag as `PLATFORM_BRIDGE` edge |
| _(none)_ | Python, Go | N/A | Standalone resolution |

### 2.6 New Language Details

#### 2.6.1 Kotlin

- **File extensions**: `.kt`, `.kts`
- **Interop group**: `jvm`
- **Tree-sitter grammar**: `tree-sitter-kotlin` (bundled in `tree-sitter-language-pack`)
- **Queries**:
  - function: `function_declaration`, `secondary_constructor`
  - class: `class_declaration`, `object_declaration`
  - import: `import_header`
  - call: `call_expression`
- **Special constructs**: `data class`, `sealed class`, `companion object`, `suspend fun`, extension functions, `object` declarations
- **Docstring**: KDoc (`/** */`) — same syntax as JavaDoc, parsed above declaration
- **FQN**: Shared `_jvm_common.py` — `src/main/kotlin/` or package-based
- **Import resolution**: Same as Java (`com.example.Class`), supports `as` aliases

#### 2.6.2 Swift

- **File extensions**: `.swift`
- **Interop group**: `apple`
- **Tree-sitter grammar**: `tree-sitter-swift`
- **Queries**:
  - function: `function_declaration`, `init_declaration`
  - class: `class_declaration`, `struct_declaration`, `enum_declaration`, `protocol_declaration`, `actor_declaration`
  - import: `import_declaration`
  - call: `call_expression`
- **Special constructs**: `protocol`, `extension`, `actor`, `@propertyWrapper`, `@Published`, access control (`public`, `private`, etc.)
- **Docstring**: DocC (`///` and `/** */`) — `- Parameter:`, `- Returns:`, `- Throws:` format
- **FQN**: Module + type name (no package hierarchy like JVM)
- **Import resolution**: Module-level (`import Foundation`), not file-level. Cross-module resolution uses bridging headers for ObjC interop.

#### 2.6.3 Objective-C

- **File extensions**: `.h`, `.m`, `.mm`
- **Interop group**: `apple`
- **Tree-sitter grammar**: `tree-sitter-objc`
- **Queries**:
  - function: `method_declaration`, `function_definition`
  - class: `class_interface`, `class_implementation`, `protocol_declaration`, `category_interface`
  - import: `preproc_import` / `module_import`
  - call: `message_expression`
- **Special constructs**: Categories, Protocols, `@property`, `@synthesize`, class methods vs instance methods (`+`/`-`)
- **Docstring**: HeaderDoc (`/** */`), `@param`, `@return`
- **FQN**: Class name (ObjC has no namespaces); prefix convention (e.g. `NS`, `UI`)
- **Import resolution**: `#import "Header.h"` (local), `#import <Framework/Header.h>` (system), `@import Module` (module import)

#### 2.6.4 Dart

- **File extensions**: `.dart`
- **Interop group**: `None` (platform bridge detection only)
- **Tree-sitter grammar**: `tree-sitter-dart`
- **Queries**:
  - function: `function_signature`, `method_signature`
  - class: `class_declaration`, `mixin_declaration`, `enum_declaration`, `extension_declaration`
  - import: `import_or_export`
  - call: `function_expression_body` / `selector`
- **Special constructs**: `mixin`, `extension`, `part`/`part of`, `factory` constructors, named constructors, `async`/`await`/`Stream`
- **Docstring**: DartDoc (`///`), supports `[reference]` cross-reference syntax
- **FQN**: `package:name/path.dart` → dotted path
- **Import resolution**: `import 'package:x/y.dart'` (package), `import './relative.dart'` (relative), `import 'dart:core'` (SDK)
- **Platform bridge detection**: Detect `MethodChannel('channel_name')` and `EventChannel('channel_name')` patterns; emit `PLATFORM_BRIDGE` edge type.

---

## 3. Implementation Phases

### Phase 1: Plugin Architecture + Migrate Existing Languages

**Goal**: Introduce `LanguagePlugin` Protocol and refactor existing 5 languages into plugins, with zero behavior change.

**Tasks**:

- [ ] P1.1: Create `indexer/languages/__init__.py` — define `LanguagePlugin`, `PluginRegistry`, `create_default_registry`
- [ ] P1.2: Create `indexer/languages/_base.py` — `BaseLanguagePlugin` with shared static helpers (`_node_text`, `_truncate_code_snippet`, `_is_license_comment`, etc.)
- [ ] P1.3: Create `indexer/languages/python.py` — extract Python-specific logic from `tree_sitter_parser.py`
- [ ] P1.4: Create `indexer/languages/java.py` + `indexer/languages/_jvm_common.py` — extract Java-specific logic
- [ ] P1.5: Create `indexer/languages/go.py` — extract Go-specific logic
- [ ] P1.6: Create `indexer/languages/javascript.py` — extract JS/TS-specific logic (shared plugin, separate TypeScript subclass)
- [ ] P1.7: Refactor `TreeSitterParser` to use `PluginRegistry` dispatch instead of `if/elif`
- [ ] P1.8: Refactor `CodeGraphBuilder.compute_fqn` to use plugin dispatch
- [ ] P1.9: Refactor `ImportResolver.resolve` to use plugin dispatch with interop group
- [ ] P1.10: Update `core/config.py` — `supported_languages`/`file_extensions` derived from registry
- [ ] P1.11: Migrate all existing tests to use new plugin-based architecture
- [ ] P1.12: Run full test suite — confirm zero behavior regression

**Key constraint**: All existing tests MUST pass with identical output. This is a pure refactor.

### Phase 2: Kotlin + Swift Plugins

**Goal**: Add Kotlin and Swift parsing support.

**Tasks**:

- [ ] P2.1: Verify `tree-sitter-kotlin` and `tree-sitter-swift` grammars available in `tree-sitter-language-pack`
- [ ] P2.2: Create `indexer/languages/kotlin.py` — `KotlinPlugin` (interop_group="jvm")
- [ ] P2.3: Create `indexer/languages/swift.py` + `indexer/languages/_apple_common.py` — `SwiftPlugin` (interop_group="apple")
- [ ] P2.4: Add Kotlin test fixtures (sample `.kt` files with classes, functions, data classes, suspend functions, companion objects)
- [ ] P2.5: Add Swift test fixtures (sample `.swift` files with classes, structs, protocols, extensions, actors)
- [ ] P2.6: Write tests for Kotlin plugin — parsing, FQN, import resolution, cross-language Java↔Kotlin
- [ ] P2.7: Write tests for Swift plugin — parsing, FQN, import resolution
- [ ] P2.8: Update `create_default_registry` to include Kotlin and Swift plugins
- [ ] P2.9: Update `core/config.py` defaults to include `kotlin` and `swift` in `supported_languages`
- [ ] P2.10: Integration test — index a mixed Java+Kotlin Android project
- [ ] P2.11: Update documentation

### Phase 3: Objective-C + Dart Plugins

**Goal**: Add Objective-C and Dart parsing support.

**Tasks**:

- [ ] P3.1: Verify `tree-sitter-objc` and `tree-sitter-dart` grammars available
- [ ] P3.2: Create `indexer/languages/objc.py` — `ObjCPlugin` (interop_group="apple")
- [ ] P3.3: Create `indexer/languages/dart.py` — `DartPlugin` with platform bridge detection
- [ ] P3.4: Add Objective-C test fixtures (`.h`/`.m` with classes, categories, protocols)
- [ ] P3.5: Add Dart test fixtures (`.dart` with classes, mixins, extensions, MethodChannel usage)
- [ ] P3.6: Write tests for ObjC plugin — parsing, FQN, import resolution, Swift↔ObjC interop
- [ ] P3.7: Write tests for Dart plugin — parsing, FQN, import resolution, platform bridge detection
- [ ] P3.8: Add `PLATFORM_BRIDGE` edge type to `store/schema.py`
- [ ] P3.9: Update `create_default_registry` to include ObjC and Dart
- [ ] P3.10: Integration test — index a mixed Swift+ObjC iOS project
- [ ] P3.11: Integration test — index a Flutter project (Dart + native)
- [ ] P3.12: Update documentation

---

## 4. Backward Compatibility

### 4.1 Constructor Transition Strategy

Each refactored class supports both old and new signatures during the transition:

```python
# TreeSitterParser — accepts either old or new style
class TreeSitterParser:
    def __init__(
        self,
        supported_languages: list[str] | None = None,
        *,
        registry: PluginRegistry | None = None,
    ) -> None:
        if registry is not None:
            self._registry = registry
        else:
            self._registry = create_default_registry(supported_languages)
        # ...

# CodeGraphBuilder — registry passed alongside existing params
class CodeGraphBuilder:
    def __init__(
        self, parser: TreeSitterParser, file_extensions: dict[str, list[str]],
        *, registry: PluginRegistry | None = None, ...
    ) -> None:
        self._registry = registry or create_default_registry()
        # file_extensions still used for ext→lang mapping as before

# ImportResolver — registry is optional
class ImportResolver:
    def __init__(
        self, file_index: dict[str, str],
        registry: PluginRegistry | None = None,
    ) -> None:
        # When registry is None, falls back to existing if/elif logic
```

### 4.2 Preserved APIs

- `LANGUAGE_QUERIES` dict remains as a module-level computed property, aggregated from all registered plugins
- `compute_fqn()` module-level function signature unchanged (adds optional `registry` kwarg with default)
- `ImportResolver.build_file_index(file_paths)` keeps its original signature (adds optional `registry` kwarg)
- Existing test fixtures and assertions remain valid
- `ParsedFunction`, `ParsedClass`, `ParsedImport`, `ParsedCall`, `ParsedField`, `ParseResult` dataclasses unchanged

---

## 5. Non-Goals

- Cross-repo language resolution (deferred)
- IDE-specific project file parsing (e.g. `.xcodeproj`, `build.gradle`) — we rely on file system convention
- Runtime platform channel tracing for Dart ↔ native — only static `MethodChannel` pattern detection
- Support for C/C++/Rust/other languages (out of scope for this spec)

---

## 6. Language-Specific Edge Cases

### 6.1 Kotlin

- **`object` declarations**: Captured as CLASS nodes with `is_object: True` property (singleton pattern)
- **`companion object`**: Nested CLASS node with `is_companion: True`
- **Extension functions**: `fun String.toSlug()` — captured with `receiver_type: "String"` property on the FUNCTION node
- **`data class`**: CLASS node with `is_data_class: True` — auto-generated methods (`copy`, `equals`, etc.) are NOT indexed

### 6.2 Swift

- **`extension` declarations**: Create EXTENDS edges from the extension CLASS node to the extended type, NOT separate standalone CLASS nodes
- **`protocol` declarations**: CLASS node with `is_interface: True` (matches Java interface behavior)
- **Access control**: `public`, `internal`, `fileprivate`, `private` stored as property on nodes
- **`actor`**: CLASS node with `is_actor: True`

### 6.3 Objective-C

- **Header/Implementation linking**: When both `Foo.h` and `Foo.m` exist, they produce one logical CLASS node. Implementation: parse both files, the `.h` provides the interface (methods, properties), `.m` provides method bodies
- **Categories**: `Foo+Bar.h` creates an EXTENDS edge from category to base class
- **`+`/`-` methods**: FUNCTION node with `is_class_method: True`/`False`
- **`@property`**: Generates ParsedField entries

### 6.4 Dart

- **`mixin` declarations**: CLASS node with `is_mixin: True`
- **`extension` declarations**: Similar to Swift — EXTENDS edge to the extended type
- **`part`/`part of`**: Library parts are merged into the parent library's module for FQN calculation
- **`MethodChannel` detection**: Regex pattern on string literals in constructor calls → `PLATFORM_BRIDGE` edge with properties `{channel_name: str, method_name: str | None}`
- **Named constructors**: `Foo.named()` — captured as separate FUNCTION node with `name: "Foo.named"`

---

## 7. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| `tree-sitter-language-pack` missing grammar for target language | Verify in Phase 2/3 task 1; fallback to standalone grammar package |
| Plugin interface too broad, forces empty stubs | Provide `BaseLanguagePlugin` with sensible defaults (empty lists, empty strings) |
| Performance regression from plugin dispatch | Dispatch is O(1) dict lookup; negligible vs. AST parsing cost |
| Cross-language resolution false positives | Restrict to same `interop_group`; never cross unrelated languages |
| Kotlin/Swift Tree-sitter query accuracy | Use community-maintained query files; add comprehensive test fixtures |
| ObjC header/impl split complicates single-file parsing | Parse both `.h`/`.m` independently; cross-file resolution merges them |
| Dart platform bridge detection inaccuracy | Best-effort string matching; clearly document as heuristic, not guaranteed |

---

## Appendix A: Sequential-Thinking Review Findings

The following issues were identified during deep review and have been incorporated into the spec above:

1. **[Critical] Missing `extract_signature`** — Signature extraction depends on language-specific body node types (`block`, `function_body`, `compound_statement`, etc.). Added to Protocol.
2. **[Critical] Missing `extract_receiver_expr`** — Receiver/object expression extraction varies by language (Java `object` field, Python `attribute.object`, JS `member_expression.object`). Added to Protocol.
3. **[Critical] Missing `should_include_function`** — JS/TS needs to filter non-module-level arrow functions; added as a general-purpose filter hook.
4. **[Critical] `resolve_import` signature flaw** — Original design passed only `file_index`, forcing plugins to rebuild reverse index on each call. Fixed to pass both `file_index` and `reverse_index`.
5. **[Critical] Missing `build_module_name`** — `ImportResolver.build_file_index` has per-language if/elif for path→module conversion. Added to Protocol for delegation.
6. **[Important] Constructor backward compatibility** — Explicitly documented dual-signature strategy for `TreeSitterParser`, `CodeGraphBuilder`, and `ImportResolver`.
7. **[Important] Language edge cases** — Added Section 6 documenting Kotlin objects, Swift extensions, ObjC header/impl linking, Dart mixins, platform bridge edge properties.
