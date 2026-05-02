"""Shared abstract base and helpers for language plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from indexer.tree_sitter_parser import ParsedField, ParsedImport

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

    from indexer.tree_sitter_parser import ParseResult

_LICENSE_KEYWORDS: frozenset[str] = frozenset({
    "copyright",
    "licensed",
    "license",
    "apache",
    "mit license",
    "gpl",
    "bsd",
    "mozilla",
    "all rights reserved",
})

DEFAULT_SIGNATURE_BODY_TYPES: frozenset[str] = frozenset({
    "block",
    "class_body",
    "statement_block",
    "constructor_body",
    "method_body",
    "arrow_function",
    "function_body",
})


class BaseLanguagePlugin(ABC):
    """Abstract plugin with defaults for optional Protocol hooks."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]:
        ...

    @abstractmethod
    def get_queries(self) -> dict[str, str]:
        ...

    @abstractmethod
    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        ...

    @abstractmethod
    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        ...

    @abstractmethod
    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        ...

    @abstractmethod
    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        ...

    @abstractmethod
    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        ...

    @abstractmethod
    def build_module_name(self, file_path: str) -> str:
        ...

    @abstractmethod
    def resolve_import(
        self,
        import_path: str,
        source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None:
        ...

    @property
    def interop_group(self) -> str | None:
        return None

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

    def extract_field_comments(self, class_node: Node, source: bytes) -> dict[str, str]:
        return {}

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        return []

    def extract_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        result: ParseResult,
    ) -> list[ParsedField]:
        return []

    @staticmethod
    def _node_text(node: Node | None) -> str:
        if node is None or not node.text:
            return ""
        return node.text.decode("utf-8")

    @staticmethod
    def _truncate_code_snippet(code: str, max_len: int = 5000) -> str:
        if len(code) <= max_len:
            return code
        total = len(code)
        head = max(1, max_len - 80)
        return code[:head] + f"\n# ... truncated ({total} total chars)"

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

    @staticmethod
    def _extract_signature_generic(
        node: Node,
        source: bytes,
        body_types: frozenset[str] | None = None,
    ) -> str:
        types = DEFAULT_SIGNATURE_BODY_TYPES if body_types is None else body_types
        start = node.start_byte
        for child in node.children:
            if child.type in types:
                end = child.start_byte
                return source[start:end].decode("utf-8").strip()
        first_line_end = source.find(b"\n", start)
        if first_line_end == -1:
            first_line_end = node.end_byte
        return source[start:first_line_end].decode("utf-8").strip()

    @staticmethod
    def _extract_block_comment_above(node: Node) -> str:
        prev = node.prev_named_sibling
        while prev and prev.type in (
            "decorator",
            "annotation",
            "marker_annotation",
            "modifiers",
        ):
            prev = prev.prev_named_sibling
        if prev is None or prev.type not in ("comment", "block_comment"):
            return ""
        raw = prev.text.decode("utf-8") if prev.text else ""
        cleaned = raw.strip()
        if prev.type == "block_comment":
            cleaned = cleaned.strip("/* \n\t")
        elif prev.type == "comment" and cleaned.startswith("//"):
            cleaned = cleaned[2:].strip()
        if BaseLanguagePlugin._is_license_comment(cleaned):
            return ""
        return cleaned

    @staticmethod
    def _pick_from_reverse(reverse_index: dict[str, list[str]], key: str) -> str | None:
        paths = reverse_index.get(key)
        if not paths:
            return None
        return sorted(paths)[0]

    @staticmethod
    def _finalize_import_symbols(imp: ParsedImport) -> None:
        if imp.symbols:
            return
        if imp.names:
            imp.symbols = list(imp.names)
            return
        if imp.language == "java" and imp.module:
            simple = imp.module.rsplit(".", 1)[-1]
            if simple and simple[0].isupper():
                imp.symbols = [simple]
