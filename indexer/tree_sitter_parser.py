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

from log import get_logger

if TYPE_CHECKING:
    from tree_sitter import Language, Parser, Tree

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
    base_classes: list[str] = field(default_factory=list)
    methods: list[ParsedFunction] = field(default_factory=list)


@dataclass
class ParsedImport:
    module: str
    names: list[str]
    file: str
    line: int
    language: str
    alias: str = ""


@dataclass
class ParsedCall:
    caller_name: str
    callee_name: str
    file: str
    line: int


@dataclass
class ParseResult:
    functions: list[ParsedFunction] = field(default_factory=list)
    classes: list[ParsedClass] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    calls: list[ParsedCall] = field(default_factory=list)


LANGUAGE_QUERIES: dict[str, dict[str, str]] = {
    "python": {
        "function": "(function_definition name: (identifier) @func.name) @func.def",
        "class": "(class_definition name: (identifier) @class.name) @class.def",
        "import": """[
            (import_statement name: (dotted_name) @import.name) @import.stmt
            (import_from_statement module_name: (dotted_name) @import.module) @import.stmt
        ]""",
        "call": "(call function: [(identifier) @call.name (attribute attribute: (identifier) @call.name)]) @call.expr",
    },
    "java": {
        "function": "(method_declaration name: (identifier) @func.name) @func.def",
        "class": "(class_declaration name: (identifier) @class.name) @class.def",
        "import": "(import_declaration (scoped_identifier) @import.name) @import.stmt",
        "call": "(method_invocation name: (identifier) @call.name) @call.expr",
    },
    "go": {
        "function": "(function_declaration name: (identifier) @func.name) @func.def",
        "class": "(type_declaration (type_spec name: (type_identifier) @class.name)) @class.def",
        "import": "(import_spec path: (interpreted_string_literal) @import.name) @import.stmt",
        "call": "(call_expression function: [(identifier) @call.name (selector_expression field: (field_identifier) @call.name)]) @call.expr",
    },
    "javascript": {
        "function": """[
            (function_declaration name: (identifier) @func.name) @func.def
            (method_definition name: (property_identifier) @func.name) @func.def
        ]""",
        "class": "(class_declaration name: (identifier) @class.name) @class.def",
        "import": "(import_statement source: (string) @import.name) @import.stmt",
        "call": "(call_expression function: [(identifier) @call.name (member_expression property: (property_identifier) @call.name)]) @call.expr",
    },
    "typescript": {
        "function": """[
            (function_declaration name: (identifier) @func.name) @func.def
            (method_definition name: (property_identifier) @func.name) @func.def
        ]""",
        "class": "(class_declaration name: (type_identifier) @class.name) @class.def",
        "import": "(import_statement source: (string) @import.name) @import.stmt",
        "call": "(call_expression function: [(identifier) @call.name (member_expression property: (property_identifier) @call.name)]) @call.expr",
    },
}


class TreeSitterParser:
    """Multi-language code parser using tree-sitter."""

    def __init__(self, supported_languages: list[str] | None = None) -> None:
        self._languages = supported_languages or list(LANGUAGE_QUERIES.keys())
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

        if content is None:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")

        source_bytes = content.encode("utf-8")
        tree = self._parsers[language].parse(source_bytes)

        result = ParseResult()
        queries = LANGUAGE_QUERIES.get(language, {})

        if "class" in queries:
            result.classes = self._extract_classes(tree, source_bytes, file_path, language, queries["class"])

        if "function" in queries:
            result.functions = self._extract_functions(tree, source_bytes, file_path, language, queries["function"])
            self._classify_methods(result)

        if "import" in queries:
            result.imports = self._extract_imports(tree, source_bytes, file_path, language, queries["import"])

        if "call" in queries:
            result.calls = self._extract_calls(tree, source_bytes, file_path, language, queries["call"], result)

        return result

    def _extract_functions(
        self, tree: Tree, source: bytes, file_path: str, language: str, query_str: str,
    ) -> list[ParsedFunction]:
        functions: list[ParsedFunction] = []
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
            name = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
            code_snippet = func_node.text.decode("utf-8") if func_node.text else ""

            if len(code_snippet) > 2000:
                code_snippet = code_snippet[:2000] + "\n# ... truncated"

            docstring = self._extract_docstring(func_node, language)
            signature = self._extract_signature(func_node, source, language)
            decorators = self._extract_decorators(func_node, language)

            functions.append(ParsedFunction(
                name=name,
                file=file_path,
                start_line=func_node.start_point[0] + 1,
                end_line=func_node.end_point[0] + 1,
                signature=signature,
                docstring=docstring,
                code_snippet=code_snippet,
                language=language,
                decorators=decorators,
            ))

        return functions

    def _extract_classes(
        self, tree: Tree, source: bytes, file_path: str, language: str, query_str: str,
    ) -> list[ParsedClass]:
        classes: list[ParsedClass] = []
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
            docstring = self._extract_docstring(class_node, language)
            base_classes = self._extract_base_classes(class_node, language)

            classes.append(ParsedClass(
                name=name,
                file=file_path,
                start_line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                docstring=docstring,
                language=language,
                base_classes=base_classes,
            ))

        return classes

    def _extract_imports(
        self, tree: Tree, source: bytes, file_path: str, language: str, query_str: str,
    ) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language(language)
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language=language, query_type="import", error=str(exc))
            return imports

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            import_nodes = match_captures.get("import.stmt", [])
            name_nodes = match_captures.get("import.name", []) + match_captures.get("import.module", [])
            if not import_nodes or not name_nodes:
                continue

            import_node = import_nodes[0]
            module = name_nodes[0].text.decode("utf-8").strip("'\"") if name_nodes[0].text else ""
            imports.append(ParsedImport(
                module=module,
                names=[],
                file=file_path,
                line=import_node.start_point[0] + 1,
                language=language,
            ))

        return imports

    def _extract_calls(
        self, tree: Tree, source: bytes, file_path: str, language: str,
        query_str: str, parse_result: ParseResult,
    ) -> list[ParsedCall]:
        calls: list[ParsedCall] = []
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
            caller = self._find_enclosing_function(call_line, func_ranges)
            if caller:
                calls.append(ParsedCall(
                    caller_name=caller,
                    callee_name=callee,
                    file=file_path,
                    line=call_line,
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
    def _extract_docstring(node: Node, language: str) -> str:
        """Extract docstring from a function/class node."""
        body = None
        for child in node.children:
            if child.type in ("block", "class_body", "statement_block"):
                body = child
                break

        if body is None:
            return ""

        first_stmt = body.children[0] if body.children else None
        if first_stmt is None:
            return ""

        if language in ("python",):
            if first_stmt.type == "expression_statement":
                expr = first_stmt.children[0] if first_stmt.children else None
                if expr and expr.type in ("string", "concatenated_string"):
                    raw = expr.text.decode("utf-8") if expr.text else ""
                    return raw.strip("'\"").strip()
        elif language in ("java", "javascript", "typescript", "go"):
            prev = node.prev_named_sibling
            if prev and prev.type in ("comment", "block_comment"):
                raw = prev.text.decode("utf-8") if prev.text else ""
                return raw.strip("/* \n\t")

        return ""

    @staticmethod
    def _extract_signature(node: Node, source: bytes, language: str) -> str:
        """Extract the function signature (first line up to body)."""
        start = node.start_byte
        for child in node.children:
            if child.type in ("block", "class_body", "statement_block", "constructor_body", "method_body"):
                end = child.start_byte
                return source[start:end].decode("utf-8").strip()
        first_line_end = source.find(b"\n", start)
        if first_line_end == -1:
            first_line_end = node.end_byte
        return source[start:first_line_end].decode("utf-8").strip()

    @staticmethod
    def _extract_decorators(node: Node, language: str) -> list[str]:
        if language != "python":
            return []
        decorators: list[str] = []
        for child in node.children:
            if child.type == "decorator":
                decorators.append(child.text.decode("utf-8") if child.text else "")
        return decorators

    @staticmethod
    def _extract_base_classes(class_node: Node, language: str) -> list[str]:
        bases: list[str] = []
        for child in class_node.children:
            if child.type == "argument_list":  # Python: class Foo(Base1, Base2)
                for arg in child.children:
                    if arg.type == "identifier" and arg.text:
                        bases.append(arg.text.decode("utf-8"))
            elif child.type == "superclass":  # Java: extends Base
                if child.text:
                    bases.append(child.text.decode("utf-8").replace("extends ", "").strip())
            elif child.type == "class_heritage":  # JS/TS: extends Base
                for sub in child.children:
                    if sub.type == "identifier" and sub.text:
                        bases.append(sub.text.decode("utf-8"))
        return bases

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
