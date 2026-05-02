"""Language plugins: protocol, registry, and default registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from indexer.tree_sitter_parser import ParsedField, ParsedImport

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

    from indexer.tree_sitter_parser import ParseResult


@runtime_checkable
class LanguagePlugin(Protocol):
    """Per-language extraction hooks used by the indexer."""

    @property
    def name(self) -> str:
        ...

    @property
    def file_extensions(self) -> list[str]:
        ...

    @property
    def interop_group(self) -> str | None:
        ...

    def get_queries(self) -> dict[str, str]:
        ...

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        ...

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        ...

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        ...

    def extract_signature(self, func_node: Node, source: bytes) -> str:
        ...

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        ...

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
        ...

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        ...

    def should_include_function(self, func_node: Node) -> bool:
        ...

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        ...

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        ...

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        ...

    def extract_field_comments(self, class_node: Node, source: bytes) -> dict[str, str]:
        ...

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        ...

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        ...

    def build_module_name(self, file_path: str) -> str:
        ...

    def resolve_import(
        self,
        import_path: str,
        source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None:
        ...

    def extract_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        result: ParseResult,
    ) -> list[ParsedField]:
        ...


class PluginRegistry:
    """Maps languages and file extensions to plugins."""

    def __init__(self) -> None:
        self._by_name: dict[str, LanguagePlugin] = {}
        self._by_ext: dict[str, LanguagePlugin] = {}

    def register(self, plugin: LanguagePlugin) -> None:
        self._by_name[plugin.name] = plugin
        for ext in plugin.file_extensions:
            norm = ext if ext.startswith(".") else f".{ext}"
            self._by_ext.setdefault(norm.lower(), plugin)

    def get_by_name(self, name: str) -> LanguagePlugin | None:
        return self._by_name.get(name)

    def get_by_extension(self, ext: str) -> LanguagePlugin | None:
        norm = ext if ext.startswith(".") else f".{ext}"
        return self._by_ext.get(norm.lower())

    def get_interop_peers(self, plugin: LanguagePlugin) -> list[LanguagePlugin]:
        group = plugin.interop_group
        if group is None:
            return []
        return [p for p in self._by_name.values() if p is not plugin and p.interop_group == group]

    @property
    def all_plugins(self) -> list[LanguagePlugin]:
        return list(self._by_name.values())

    @property
    def supported_languages(self) -> list[str]:
        return sorted(self._by_name.keys())

    @property
    def file_extensions(self) -> dict[str, list[str]]:
        return {p.name: list(p.file_extensions) for p in self._by_name.values()}


def create_default_registry(languages: list[str] | None = None) -> PluginRegistry:
    """Build a registry with built-in language plugins (lazy-imported)."""
    from indexer.languages.go_lang import GoPlugin
    from indexer.languages.java_lang import JavaPlugin
    from indexer.languages.javascript_lang import JavaScriptPlugin, TypeScriptPlugin
    from indexer.languages.python_lang import PythonPlugin

    specs: list[tuple[str, type]] = [
        ("python", PythonPlugin),
        ("java", JavaPlugin),
        ("go", GoPlugin),
        ("javascript", JavaScriptPlugin),
        ("typescript", TypeScriptPlugin),
    ]
    allow = None if languages is None else {x.lower() for x in languages}

    registry = PluginRegistry()
    for lang_key, cls in specs:
        if allow is not None and lang_key not in allow:
            continue
        registry.register(cls())
    return registry


__all__ = [
    "LanguagePlugin",
    "ParsedField",
    "ParsedImport",
    "PluginRegistry",
    "create_default_registry",
]
