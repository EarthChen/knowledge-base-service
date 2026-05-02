"""Tree-sitter multi-language AST parser.

Parses source code files into structured AST data for extracting
functions, classes, imports, and call relationships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Node, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from core.log import get_logger

if TYPE_CHECKING:
    from indexer.languages import LanguagePlugin, PluginRegistry

    from tree_sitter import Language, Parser, Tree

_LANGUAGE_QUERIES_CACHE: dict[str, dict[str, str]] | None = None


def __getattr__(name: str) -> dict[str, dict[str, str]]:
    if name == "LANGUAGE_QUERIES":
        global _LANGUAGE_QUERIES_CACHE
        if _LANGUAGE_QUERIES_CACHE is None:
            from indexer.languages import create_default_registry

            reg = create_default_registry()
            _LANGUAGE_QUERIES_CACHE = {p.name: p.get_queries() for p in reg.all_plugins}
        return _LANGUAGE_QUERIES_CACHE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

log = get_logger(__name__)


@dataclass
class ParsedFunction:
    name: str
    file: str
    start_line: int
    end_line: int
    signature: str
    docstring: str
    code_snippet: str
    language: str
    parameters: list[dict[str, str]] = field(default_factory=list)
    return_type: str = ""
    decorators: list[str] = field(default_factory=list)
    parent_class: str = ""


@dataclass
class ParsedClass:
    name: str
    file: str
    start_line: int
    end_line: int
    docstring: str
    language: str
    # Java: raw extended type strings may include generics, e.g. JpaRepository<User, Long>
    base_classes: list[str] = field(default_factory=list)
    generic_type_params: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    is_interface: bool = False
    methods: list[ParsedFunction] = field(default_factory=list)
    code_snippet: str = ""


@dataclass
class ParsedImport:
    module: str
    names: list[str]
    file: str
    line: int
    language: str
    alias: str = ""
    symbols: list[str] = field(default_factory=list)


@dataclass
class ParsedField:
    """A class field declaration with annotations and type info."""
    name: str
    field_type: str
    file: str
    line: int
    annotations: list[str] = field(default_factory=list)
    parent_class: str = ""
    # field (annotation-based), constructor (inferred ctor / private final bean)
    injection_type: str = ""


@dataclass
class ParsedCall:
    caller_name: str
    callee_name: str
    file: str
    line: int
    receiver_expr: str = ""


@dataclass
class ParseResult:
    functions: list[ParsedFunction] = field(default_factory=list)
    classes: list[ParsedClass] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    calls: list[ParsedCall] = field(default_factory=list)
    fields: list[ParsedField] = field(default_factory=list)
    module_docstring: str = ""


_LICENSE_KEYWORDS: frozenset[str] = frozenset({
    "copyright", "licensed", "license", "apache", "mit license",
    "gpl", "bsd", "mozilla", "all rights reserved",
})


def _is_license_comment(text: str) -> bool:
    lower = text.lower()[:500]
    return sum(1 for kw in _LICENSE_KEYWORDS if kw in lower) >= 2


_JAVA_DI_NON_BEAN_SIMPLE_TYPES: frozenset[str] = frozenset({
    "String", "Boolean", "Byte", "Character", "Double", "Float", "Integer", "Long", "Short",
    "Object", "Void", "Class", "Throwable", "Exception", "RuntimeException",
    "List", "Map", "Set", "Collection", "Iterable", "Optional", "Stream",
})


class TreeSitterParser:
    """Multi-language code parser using tree-sitter."""

    def __init__(
        self,
        supported_languages: list[str] | None = None,
        registry: PluginRegistry | None = None,
    ) -> None:
        from indexer.languages import create_default_registry

        if registry is not None:
            self._registry = registry
            self._languages = (
                list(supported_languages)
                if supported_languages
                else list(registry.supported_languages)
            )
        else:
            reg_langs = supported_languages if supported_languages else None
            self._registry = create_default_registry(reg_langs)
            self._languages = list(self._registry.supported_languages)
        self._parsers: dict[str, Parser] = {}
        self._init_parsers()

    def _init_parsers(self) -> None:
        for lang in self._languages:
            try:
                self._parsers[lang] = get_parser(lang)
                log.info("tree_sitter_parser_loaded", language=lang)
            except LookupError:
                log.warning("tree_sitter_language_not_found", language=lang)

    def parse_file(self, file_path: str, language: str, content: str | None = None) -> ParseResult:
        if language not in self._parsers:
            log.warning("unsupported_language", language=language, file=file_path)
            return ParseResult()

        plugin = self._registry.get_by_name(language)
        if plugin is None:
            log.warning("unsupported_language", language=language, file=file_path)
            return ParseResult()

        if content is None:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")

        source_bytes = content.encode("utf-8")
        tree = self._parsers[language].parse(source_bytes)

        result = ParseResult()
        queries = plugin.get_queries()

        if "class" in queries:
            result.classes = self._extract_classes(tree, source_bytes, file_path, language, plugin)

        if "function" in queries:
            result.functions = self._extract_functions(tree, source_bytes, file_path, language, plugin)
            self._classify_methods(result)

        if "import" in queries:
            result.imports = self._extract_imports(tree, source_bytes, file_path, plugin)

        if "call" in queries:
            result.calls = self._extract_calls(tree, source_bytes, file_path, language, plugin, result)

        result.fields = plugin.extract_fields(tree, source_bytes, file_path, result)

        result.module_docstring = plugin.extract_module_docstring(tree.root_node, source_bytes)

        return result

    def _extract_functions(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        language: str,
        plugin: LanguagePlugin,
    ) -> list[ParsedFunction]:
        functions: list[ParsedFunction] = []
        query_str = plugin.get_queries().get("function", "")
        if not query_str:
            return functions
        lang = get_language(language)
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language=language, query_type="function", error=str(exc))
            return functions

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            func_nodes = match_captures.get("func.def", [])
            name_nodes = match_captures.get("func.name", [])
            if not func_nodes or not name_nodes:
                continue

            func_node = func_nodes[0]
            if not plugin.should_include_function(func_node):
                continue

            name = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
            raw_snippet = func_node.text.decode("utf-8") if func_node.text else ""
            code_snippet = TreeSitterParser._truncate_code_snippet(raw_snippet)

            docstring = plugin.extract_function_docstring(func_node, source)
            signature = plugin.extract_signature(func_node, source)
            decorators = plugin.extract_annotations(func_node, source)
            parameters = plugin.extract_parameters(func_node, source)
            return_type = plugin.extract_return_type(func_node, source)

            functions.append(ParsedFunction(
                name=name,
                file=file_path,
                start_line=func_node.start_point[0] + 1,
                end_line=func_node.end_point[0] + 1,
                signature=signature,
                docstring=docstring,
                code_snippet=code_snippet,
                language=language,
                parameters=parameters,
                return_type=return_type,
                decorators=decorators,
            ))

        return functions

    def _extract_classes(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        language: str,
        plugin: LanguagePlugin,
    ) -> list[ParsedClass]:
        classes: list[ParsedClass] = []
        query_str = plugin.get_queries().get("class", "")
        if not query_str:
            return classes
        lang = get_language(language)
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language=language, query_type="class", error=str(exc))
            return classes

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            class_nodes = match_captures.get("class.def", [])
            name_nodes = match_captures.get("class.name", [])
            if not class_nodes or not name_nodes:
                continue

            class_node = class_nodes[0]
            name = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
            is_interface = class_node.type == "interface_declaration"
            docstring = plugin.extract_class_docstring(class_node, source)
            base_classes, generic_type_params = plugin.extract_base_classes(class_node, source)
            interfaces = plugin.extract_interfaces(class_node, source)

            decorators = plugin.extract_annotations(class_node, source)

            raw_class_snippet = class_node.text.decode("utf-8") if class_node.text else ""
            class_snippet = TreeSitterParser._truncate_code_snippet(raw_class_snippet)

            classes.append(ParsedClass(
                name=name,
                file=file_path,
                start_line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                docstring=docstring,
                language=language,
                base_classes=base_classes,
                generic_type_params=generic_type_params,
                decorators=decorators,
                interfaces=interfaces,
                is_interface=is_interface,
                code_snippet=class_snippet,
            ))

        return classes

    def _extract_imports(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        plugin: LanguagePlugin,
    ) -> list[ParsedImport]:
        return plugin.extract_imports(tree, source, file_path)

    def _extract_calls(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        language: str,
        plugin: LanguagePlugin,
        parse_result: ParseResult,
    ) -> list[ParsedCall]:
        calls: list[ParsedCall] = []
        query_str = plugin.get_queries().get("call", "")
        if not query_str:
            return calls
        lang = get_language(language)
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language=language, query_type="call", error=str(exc))
            return calls

        func_ranges = [
            (f.name, f.start_line, f.end_line) for f in parse_result.functions
        ]

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            call_nodes = match_captures.get("call.expr", [])
            name_nodes = match_captures.get("call.name", [])
            if not call_nodes or not name_nodes:
                continue

            callee = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
            call_line = call_nodes[0].start_point[0] + 1
            call_node = call_nodes[0]
            receiver_expr = plugin.extract_receiver_expr(call_node, source)
            caller = self._find_enclosing_function(call_line, func_ranges)
            if caller:
                calls.append(ParsedCall(
                    caller_name=caller,
                    callee_name=callee,
                    file=file_path,
                    line=call_line,
                    receiver_expr=receiver_expr,
                ))

        return calls

    def _classify_methods(self, result: ParseResult) -> None:
        """Assign parent_class to functions that are methods of a class."""
        for cls in result.classes:
            for func in result.functions:
                if cls.start_line <= func.start_line <= func.end_line <= cls.end_line:
                    func.parent_class = cls.name
                    cls.methods.append(func)

    @staticmethod
    def _node_within(child: Node, parent: Node) -> bool:
        return (
            parent.start_byte <= child.start_byte
            and child.end_byte <= parent.end_byte
        )

    @staticmethod
    def _truncate_code_snippet(code_snippet: str) -> str:
        if len(code_snippet) <= 5000:
            return code_snippet
        total = len(code_snippet)
        return code_snippet[:3000] + f"\n# ... truncated ({total} total chars)"

    @staticmethod
    def _java_type_looks_like_spring_bean(simple_name: str) -> bool:
        if not simple_name or not simple_name[0].isupper():
            return False
        return simple_name not in _JAVA_DI_NON_BEAN_SIMPLE_TYPES

    @staticmethod
    def _find_enclosing_function(line: int, func_ranges: list[tuple[str, int, int]]) -> str:
        """Find the innermost function enclosing the given line."""
        best: str = ""
        best_size = float("inf")
        for name, start, end in func_ranges:
            if start <= line <= end:
                size = end - start
                if size < best_size:
                    best = name
                    best_size = size
        return best
