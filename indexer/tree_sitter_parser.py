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
        "function": """[
            (method_declaration name: (identifier) @func.name) @func.def
            (constructor_declaration name: (identifier) @func.name) @func.def
        ]""",
        "class": """[
            (class_declaration name: (identifier) @class.name) @class.def
            (interface_declaration name: (identifier) @class.name) @class.def
        ]""",
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
            (lexical_declaration
                (variable_declarator
                    name: (identifier) @func.name
                    value: (arrow_function) @func.def))
        ]""",
        "class": "(class_declaration name: (identifier) @class.name) @class.def",
        "import": "(import_statement source: (string) @import.name) @import.stmt",
        "call": "(call_expression function: [(identifier) @call.name (member_expression property: (property_identifier) @call.name)]) @call.expr",
    },
    "typescript": {
        "function": """[
            (function_declaration name: (identifier) @func.name) @func.def
            (method_definition name: (property_identifier) @func.name) @func.def
            (lexical_declaration
                (variable_declarator
                    name: (identifier) @func.name
                    value: (arrow_function) @func.def))
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

        if language == "java":
            result.fields = self._extract_java_fields(tree, source_bytes, file_path, result)

        result.module_docstring = self._extract_module_docstring(tree.root_node, language)

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
            if language in ("javascript", "typescript") and func_node.type == "arrow_function":
                lex = TreeSitterParser._lexical_declaration_for_arrow_binding(func_node)
                if lex is None or not TreeSitterParser._is_module_level(lex):
                    continue

            name = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
            raw_snippet = func_node.text.decode("utf-8") if func_node.text else ""
            code_snippet = TreeSitterParser._truncate_code_snippet(raw_snippet)

            docstring = self._extract_docstring(func_node, language)
            signature = self._extract_signature(func_node, source, language)
            decorators = self._extract_decorators(func_node, language)
            parameters = self._extract_parameters(func_node, language)
            return_type = self._extract_return_type(func_node, language)

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

    @staticmethod
    def _is_module_level(node: Node) -> bool:
        """True if node is direct child of program or of export_statement under program."""
        parent = node.parent
        if parent is None:
            return False
        if parent.type == "program":
            return True
        if parent.type == "export_statement":
            gp = parent.parent
            return gp is not None and gp.type == "program"
        return False

    @staticmethod
    def _lexical_declaration_for_arrow_binding(arrow: Node) -> Node | None:
        """Walk from arrow_function to enclosing lexical_declaration (const/let binding)."""
        p = arrow.parent
        if p is None or p.type != "variable_declarator":
            return None
        p = p.parent
        if p is None or p.type != "lexical_declaration":
            return None
        return p

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
            is_interface = class_node.type == "interface_declaration"
            docstring = self._extract_docstring(class_node, language)
            base_classes, generic_type_params = self._extract_base_classes(class_node, language)
            interfaces = self._extract_interfaces(class_node, language)

            decorators = self._extract_decorators(class_node, language)

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
        self, tree: Tree, source: bytes, file_path: str, language: str, query_str: str,
    ) -> list[ParsedImport]:
        if language == "python":
            return self._extract_imports_python(tree, file_path)

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
            line = import_node.start_point[0] + 1

            if language == "java":
                module = name_nodes[0].text.decode("utf-8").strip() if name_nodes[0].text else ""
                imp = ParsedImport(
                    module=module,
                    names=[],
                    file=file_path,
                    line=line,
                    language=language,
                )
            elif language in ("javascript", "typescript"):
                imp = self._parsed_import_js_ts(import_node, file_path, language)
            elif language == "go":
                raw = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
                module = TreeSitterParser._strip_string_delimiters(raw)
                imp = ParsedImport(
                    module=module,
                    names=[],
                    file=file_path,
                    line=line,
                    language=language,
                )
            else:
                module = name_nodes[0].text.decode("utf-8").strip("'\"") if name_nodes[0].text else ""
                imp = ParsedImport(
                    module=module,
                    names=[],
                    file=file_path,
                    line=line,
                    language=language,
                )

            TreeSitterParser._finalize_import_symbols(imp)
            imports.append(imp)

        return imports

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

    @staticmethod
    def _strip_string_delimiters(raw: str) -> str:
        s = raw.strip()
        if len(s) >= 2 and s[0] in "'\"`" and s[-1] == s[0]:
            return s[1:-1]
        return s

    def _extract_imports_python(self, tree: Tree, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []

        def visit(node: Node) -> None:
            if node.type == "import_statement":
                imports.extend(self._python_import_statement_entries(node, file_path))
            elif node.type == "import_from_statement":
                imports.append(self._python_import_from_statement_entry(node, file_path))
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        for imp in imports:
            TreeSitterParser._finalize_import_symbols(imp)
        return imports

    def _python_import_statement_entries(self, node: Node, file_path: str) -> list[ParsedImport]:
        line = node.start_point[0] + 1
        out: list[ParsedImport] = []
        for child in node.children:
            if child.type in ("import", ","):
                continue
            if child.type == "dotted_name":
                mod = TreeSitterParser._python_dotted_name_text(child)
                loc = TreeSitterParser._python_import_stmt_local_name(child)
                out.append(ParsedImport(
                    module=mod,
                    names=[loc],
                    file=file_path,
                    line=line,
                    language="python",
                ))
            elif child.type == "aliased_import":
                dn = child.child_by_field_name("name")
                al = child.child_by_field_name("alias")
                mod = TreeSitterParser._python_dotted_name_text(dn) if dn else ""
                loc = TreeSitterParser._node_text(al) if al else mod
                out.append(ParsedImport(
                    module=mod,
                    names=[loc],
                    file=file_path,
                    line=line,
                    language="python",
                ))
        return out

    def _python_import_from_statement_entry(self, node: Node, file_path: str) -> ParsedImport:
        mod = TreeSitterParser._python_import_from_module_string(node)
        line = node.start_point[0] + 1
        bindings = TreeSitterParser._python_from_import_bindings(node)
        return ParsedImport(
            module=mod,
            names=bindings,
            file=file_path,
            line=line,
            language="python",
        )

    @staticmethod
    def _python_dotted_name_text(dn: Node) -> str:
        return dn.text.decode("utf-8").strip() if dn.text else ""

    @staticmethod
    def _python_import_stmt_local_name(dn: Node) -> str:
        ids = [TreeSitterParser._node_text(c) for c in dn.children if c.type == "identifier"]
        if not ids:
            t = dn.text.decode("utf-8") if dn.text else ""
            return t.split(".")[0] if t else ""
        if len(ids) == 1:
            return ids[0]
        return ids[0]

    @staticmethod
    def _python_import_from_module_string(node: Node) -> str:
        parts: list[str] = []
        for child in node.children:
            if child.type == "import":
                break
            if child.type == "from":
                continue
            if child.text:
                parts.append(child.text.decode("utf-8"))
        return "".join(parts)

    @staticmethod
    def _python_from_import_bindings(node: Node) -> list[str]:
        bindings: list[str] = []
        seen_import = False
        for child in node.children:
            if child.type == "import":
                seen_import = True
                continue
            if not seen_import:
                continue
            if child.type in (",", "wildcard_import"):
                continue
            if child.type == "dotted_name":
                ids = [TreeSitterParser._node_text(c) for c in child.children if c.type == "identifier"]
                bindings.append(ids[-1] if ids else TreeSitterParser._python_dotted_name_text(child))
            elif child.type == "aliased_import":
                al = child.child_by_field_name("alias")
                bindings.append(TreeSitterParser._node_text(al) if al else "")
        return [b for b in bindings if b]

    def _parsed_import_js_ts(self, import_node: Node, file_path: str, language: str) -> ParsedImport:
        line = import_node.start_point[0] + 1
        src = import_node.child_by_field_name("source")
        raw_src = TreeSitterParser._node_text(src)
        module = TreeSitterParser._strip_string_delimiters(raw_src)
        clause = next((c for c in import_node.children if c.type == "import_clause"), None)
        syms = TreeSitterParser._js_ts_import_clause_symbols(clause)
        return ParsedImport(
            module=module,
            names=list(syms),
            file=file_path,
            line=line,
            language=language,
        )

    @staticmethod
    def _js_ts_import_clause_symbols(clause: Node | None) -> list[str]:
        if clause is None:
            return []
        syms: list[str] = []
        for ch in clause.children:
            if ch.type == "identifier":
                syms.append(TreeSitterParser._node_text(ch))
            elif ch.type == "named_imports":
                for sub in ch.children:
                    if sub.type != "import_specifier":
                        continue
                    name_n = sub.child_by_field_name("name")
                    alias_n = sub.child_by_field_name("alias")
                    if alias_n is not None and TreeSitterParser._node_text(alias_n):
                        syms.append(TreeSitterParser._node_text(alias_n))
                    elif name_n is not None:
                        syms.append(TreeSitterParser._node_text(name_n))
            elif ch.type == "namespace_import":
                for sub in ch.children:
                    if sub.type == "identifier":
                        syms.append(TreeSitterParser._node_text(sub))
        return syms

    @staticmethod
    def _extract_receiver_expr(call_node: Node, language: str) -> str:
        """Text of the object/receiver for method-style calls; empty for plain calls."""
        if language == "java":
            obj = call_node.child_by_field_name("object")
            if obj is not None and obj.text:
                return obj.text.decode("utf-8")
            return ""
        if language == "python":
            func_child = call_node.child_by_field_name("function")
            if func_child is not None and func_child.type == "attribute":
                obj = func_child.child_by_field_name("object")
                if obj is not None and obj.text:
                    return obj.text.decode("utf-8")
            return ""
        if language in ("javascript", "typescript"):
            func_child = call_node.child_by_field_name("function")
            if func_child is not None and func_child.type == "member_expression":
                obj = func_child.child_by_field_name("object")
                if obj is not None and obj.text:
                    return obj.text.decode("utf-8")
            return ""
        return ""

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
            call_node = call_nodes[0]
            receiver_expr = TreeSitterParser._extract_receiver_expr(call_node, language)
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
    def _extract_docstring(node: Node, language: str) -> str:
        """Extract docstring from a function/class node."""
        body = None
        for child in node.children:
            if child.type in ("block", "class_body", "interface_body", "statement_block"):
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
    def _extract_module_docstring(root_node: Node, language: str) -> str:
        """Extract file-level docstring from the module root."""
        if language == "python":
            for child in root_node.children:
                if child.type == "comment":
                    continue
                if child.type in ("string", "concatenated_string"):
                    raw = child.text.decode("utf-8") if child.text else ""
                    return raw.strip("'\"").strip()
                if child.type == "expression_statement":
                    expr = child.children[0] if child.children else None
                    if expr and expr.type in ("string", "concatenated_string"):
                        raw = expr.text.decode("utf-8") if expr.text else ""
                        return raw.strip("'\"").strip()
                    break
                if child.type not in ("import_statement", "import_from_statement"):
                    break
            return ""
        return TreeSitterParser._extract_file_header_comment(root_node, language)

    @staticmethod
    def _extract_file_header_comment(root_node: Node, language: str) -> str:
        """Extract documentation comment above the first class declaration (not above imports)."""
        if language not in ("java", "javascript", "typescript", "go"):
            return ""

        first_class = None
        for child in root_node.children:
            if child.type in (
                "class_declaration", "interface_declaration",
                "enum_declaration", "annotation_type_declaration",
                "class",
            ):
                first_class = child
                break
            if child.type == "export_statement":
                for sub in child.children:
                    if sub.type in ("class_declaration", "interface_declaration", "class"):
                        first_class = sub
                        break
                if first_class:
                    break

        if first_class is None:
            return ""

        prev = first_class.prev_named_sibling
        while prev and prev.type in (
            "decorator", "annotation", "marker_annotation", "modifiers",
        ):
            prev = prev.prev_named_sibling

        if prev and prev.type in ("comment", "block_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            cleaned = raw.strip("/* \n\t")
            if _is_license_comment(cleaned):
                return ""
            return cleaned

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
        """Extract decorators/annotations. Python/TS/JS: decorator nodes; Java: modifiers."""
        if language == "python":
            decorators: list[str] = []
            parent = node.parent
            if parent is not None and parent.type == "decorated_definition":
                for child in parent.children:
                    if child is node:
                        break
                    if child.type == "decorator":
                        decorators.append(child.text.decode("utf-8") if child.text else "")
            else:
                for child in node.children:
                    if child.type == "decorator":
                        decorators.append(child.text.decode("utf-8") if child.text else "")
            return decorators

        if language == "java":
            return TreeSitterParser._extract_java_annotations_from_node(node)

        if language in ("typescript", "javascript"):
            decorators: list[str] = []
            for child in node.children:
                if child.type == "decorator":
                    decorators.append(child.text.decode("utf-8") if child.text else "")
            cur = node.prev_named_sibling
            while cur is not None and cur.type == "decorator":
                text = cur.text.decode("utf-8") if cur.text else ""
                if text:
                    decorators.insert(0, text)
                cur = cur.prev_named_sibling
            return decorators

        return []

    @staticmethod
    def _extract_java_annotations_from_node(node: Node) -> list[str]:
        """Collect marker_annotation and annotation from modifiers (class or method)."""
        out: list[str] = []
        for child in node.children:
            if child.type != "modifiers":
                continue
            for mod_child in child.children:
                if mod_child.type in ("marker_annotation", "annotation"):
                    text = mod_child.text.decode("utf-8") if mod_child.text else ""
                    if text:
                        out.append(text)
        return out

    @staticmethod
    def _node_text(node: Node | None) -> str:
        if node is None or not node.text:
            return ""
        return node.text.decode("utf-8")

    @staticmethod
    def _strip_type_annotation(node: Node | None) -> str:
        if node is None:
            return ""
        raw = TreeSitterParser._node_text(node)
        if node.type == "type_annotation":
            return raw.lstrip().lstrip(":").strip()
        return raw.strip()

    @staticmethod
    def _extract_parameters(func_node: Node, language: str) -> list[dict[str, str]]:
        if language == "python":
            return TreeSitterParser._extract_parameters_python(func_node)
        if language == "java":
            return TreeSitterParser._extract_parameters_java(func_node)
        if language in ("typescript", "javascript"):
            return TreeSitterParser._extract_parameters_ts_js(func_node)
        if language == "go":
            return TreeSitterParser._extract_parameters_go(func_node)
        return []

    @staticmethod
    def _extract_parameters_python(func_node: Node) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        params = func_node.child_by_field_name("parameters")
        if params is None:
            return out
        for child in params.children:
            if child.type in ("typed_parameter", "typed_default_parameter"):
                pname = TreeSitterParser._python_parameter_name(child)
                ptype = TreeSitterParser._python_parameter_type(child)
                if pname and pname not in ("self", "cls"):
                    out.append({"name": pname, "type": ptype})
            elif child.type == "default_parameter":
                for gc in child.children:
                    if gc.type == "identifier":
                        n = TreeSitterParser._node_text(gc)
                        if n and n not in ("self", "cls"):
                            out.append({"name": n, "type": ""})
                        break
            elif child.type == "identifier":
                n = TreeSitterParser._node_text(child)
                if n and n not in ("self", "cls"):
                    out.append({"name": n, "type": ""})
            elif child.type == "list_splat_pattern":
                for gc in child.children:
                    if gc.type == "identifier":
                        out.append({"name": TreeSitterParser._node_text(gc), "type": ""})
                        break
            elif child.type == "dictionary_splat_pattern":
                for gc in child.children:
                    if gc.type == "identifier":
                        out.append({"name": TreeSitterParser._node_text(gc), "type": ""})
                        break
        return out

    @staticmethod
    def _python_parameter_name(param: Node) -> str:
        for ch in param.children:
            if ch.type == "identifier":
                return TreeSitterParser._node_text(ch)
            if ch.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                for gc in ch.children:
                    if gc.type == "identifier":
                        return TreeSitterParser._node_text(gc)
        return ""

    @staticmethod
    def _python_parameter_type(param: Node) -> str:
        t = param.child_by_field_name("type")
        if t is not None:
            return TreeSitterParser._node_text(t).strip()
        for ch in param.children:
            if ch.type == "type":
                return TreeSitterParser._node_text(ch).strip()
        return ""

    @staticmethod
    def _extract_parameters_java(method_node: Node) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        fp = None
        for ch in method_node.children:
            if ch.type == "formal_parameters":
                fp = ch
                break
        if fp is None:
            return out
        for ch in fp.children:
            if ch.type == "formal_parameter":
                t = ch.child_by_field_name("type")
                n = ch.child_by_field_name("name")
                out.append({
                    "name": TreeSitterParser._node_text(n),
                    "type": TreeSitterParser._node_text(t),
                })
            elif ch.type == "spread_parameter":
                typ = ""
                pname = ""
                for sp in ch.children:
                    if sp.type == "variable_declarator":
                        for vv in sp.children:
                            if vv.type == "identifier":
                                pname = TreeSitterParser._node_text(vv)
                    else:
                        typ += TreeSitterParser._node_text(sp)
                out.append({"name": pname, "type": typ})
        return out

    @staticmethod
    def _ts_js_pattern_name(pattern: Node | None) -> str:
        if pattern is None:
            return ""
        if pattern.type == "identifier":
            return TreeSitterParser._node_text(pattern)
        if pattern.type == "rest_pattern":
            for ch in pattern.children:
                if ch.type == "identifier":
                    return TreeSitterParser._node_text(ch)
        return TreeSitterParser._node_text(pattern)

    @staticmethod
    def _extract_parameters_ts_js(func_node: Node) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        fp = None
        for ch in func_node.children:
            if ch.type == "formal_parameters":
                fp = ch
                break
        if fp is None:
            return out
        for ch in fp.children:
            if ch.type == "identifier":
                out.append({"name": TreeSitterParser._node_text(ch), "type": ""})
            elif ch.type in ("required_parameter", "optional_parameter"):
                pat = ch.child_by_field_name("pattern")
                name = TreeSitterParser._ts_js_pattern_name(pat)
                tnode = ch.child_by_field_name("type")
                typ = TreeSitterParser._strip_type_annotation(tnode) if tnode else ""
                if name:
                    out.append({"name": name, "type": typ})
        return out

    @staticmethod
    def _extract_parameters_go(func_node: Node) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        pl = func_node.child_by_field_name("parameters")
        if pl is None or pl.type != "parameter_list":
            return out
        for ch in pl.children:
            if ch.type != "parameter_declaration":
                continue
            chs = ch.children
            names: list[str] = []
            i = 0
            while i < len(chs):
                if chs[i].type == "identifier":
                    names.append(TreeSitterParser._node_text(chs[i]))
                    i += 1
                    if i < len(chs) and chs[i].type == ",":
                        i += 1
                        continue
                    break
                break
            typ = "".join(TreeSitterParser._node_text(chs[j]) for j in range(i, len(chs))).strip()
            for n in names:
                out.append({"name": n, "type": typ})
        return out

    @staticmethod
    def _extract_return_type(func_node: Node, language: str) -> str:
        if language == "java":
            return TreeSitterParser._node_text(func_node.child_by_field_name("type")).strip()
        if language == "python":
            rt = func_node.child_by_field_name("return_type")
            return TreeSitterParser._node_text(rt).strip() if rt else ""
        if language in ("typescript", "javascript"):
            rt = func_node.child_by_field_name("return_type")
            return TreeSitterParser._strip_type_annotation(rt) if rt else ""
        if language == "go":
            return TreeSitterParser._extract_return_type_go(func_node)
        return ""

    @staticmethod
    def _extract_return_type_go(func_node: Node) -> str:
        if func_node.type != "function_declaration":
            return ""
        children = list(func_node.children)
        block_idx = next((i for i, c in enumerate(children) if c.type == "block"), None)
        if block_idx is None:
            return ""
        before_block = children[:block_idx]
        segment = [c for c in before_block if c.type != "func"]
        if len(segment) < 2 or segment[0].type != "identifier":
            return ""
        if len(segment) <= 2:
            return ""
        return "".join(TreeSitterParser._node_text(c) for c in segment[2:]).strip()

    @staticmethod
    def _truncate_code_snippet(code_snippet: str) -> str:
        if len(code_snippet) <= 5000:
            return code_snippet
        total = len(code_snippet)
        return code_snippet[:3000] + f"\n# ... truncated ({total} total chars)"

    @staticmethod
    def _extract_base_classes(class_node: Node, language: str) -> tuple[list[str], list[str]]:
        bases: list[str] = []
        generic_params: list[str] = []
        for child in class_node.children:
            if child.type == "argument_list":  # Python: class Foo(Base1, Base2)
                for arg in child.children:
                    if arg.type == "identifier" and arg.text:
                        bases.append(arg.text.decode("utf-8"))
            elif child.type == "superclass":  # Java: extends Base
                if child.text:
                    raw = child.text.decode("utf-8").replace("extends ", "").strip()
                    bases.append(raw)
                    if language == "java":
                        generic_params.extend(
                            TreeSitterParser._java_type_arguments_from_super_ref(child),
                        )
            elif child.type == "extends_interfaces":  # Java interface extends Type
                if language == "java":
                    for sub in child.children:
                        if sub.type != "type_list":
                            continue
                        for tl_child in sub.children:
                            if tl_child.type == ",":
                                continue
                            raw = TreeSitterParser._node_text(tl_child).strip()
                            if raw:
                                bases.append(raw)
                            generic_params.extend(
                                TreeSitterParser._java_type_arguments_from_type_list_child(tl_child),
                            )
            elif child.type == "super_interfaces":  # Java class implements
                if language == "java":
                    for sub in child.children:
                        if sub.type != "type_list":
                            continue
                        for tl_child in sub.children:
                            if tl_child.type == ",":
                                continue
                            generic_params.extend(
                                TreeSitterParser._java_type_arguments_from_type_list_child(tl_child),
                            )
            elif child.type == "class_heritage":  # JS/TS: extends Base
                for sub in child.children:
                    if sub.type == "identifier" and sub.text:
                        bases.append(sub.text.decode("utf-8"))
        return bases, generic_params

    @staticmethod
    def _java_type_arguments_from_super_ref(super_node: Node) -> list[str]:
        for ch in super_node.children:
            if ch.type == "generic_type":
                return TreeSitterParser._java_type_arguments_from_generic_type(ch)
        return []

    @staticmethod
    def _java_type_arguments_from_type_list_child(tl_child: Node) -> list[str]:
        if tl_child.type == "generic_type":
            return TreeSitterParser._java_type_arguments_from_generic_type(tl_child)
        return []

    @staticmethod
    def _java_type_arguments_from_generic_type(gt: Node) -> list[str]:
        out: list[str] = []
        for ch in gt.children:
            if ch.type != "type_arguments":
                continue
            for arg in ch.children:
                if arg.type == ",":
                    continue
                name = TreeSitterParser._java_type_argument_simple_name(arg)
                if name:
                    out.append(name)
        return out

    @staticmethod
    def _java_type_argument_simple_name(node: Node) -> str:
        if node.type == "type_identifier":
            return TreeSitterParser._node_text(node).strip()
        if node.type == "generic_type":
            for c in node.children:
                if c.type in ("type_identifier", "scoped_type_identifier"):
                    return TreeSitterParser._java_type_identifier_simple(c)
        if node.type == "scoped_type_identifier":
            return TreeSitterParser._java_type_identifier_simple(node)
        return ""

    @staticmethod
    def _java_type_identifier_simple(node: Node) -> str:
        if node.type == "type_identifier":
            return TreeSitterParser._node_text(node).strip()
        if node.type == "scoped_type_identifier":
            id_nodes = [c for c in node.children if c.type == "type_identifier"]
            if id_nodes:
                return TreeSitterParser._node_text(id_nodes[-1]).strip()
        return TreeSitterParser._node_text(node).strip()

    @staticmethod
    def _java_type_list_simple_name(type_node: Node) -> str:
        """Map one Java type_list entry to a simple name (for same-file / simple graph matching)."""
        if type_node.type == "type_identifier":
            return TreeSitterParser._node_text(type_node).strip()
        if type_node.type == "scoped_type_identifier":
            id_nodes = [c for c in type_node.children if c.type == "type_identifier"]
            if id_nodes:
                return TreeSitterParser._node_text(id_nodes[-1]).strip()
            raw = TreeSitterParser._node_text(type_node).strip()
            return raw.split(".")[-1] if raw else ""
        if type_node.type == "generic_type":
            for c in type_node.children:
                if c.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                    return TreeSitterParser._java_type_list_simple_name(c)
        return ""

    @staticmethod
    def _extract_interfaces(class_node: Node, language: str) -> list[str]:
        if language != "java":
            return []
        out: list[str] = []
        for child in class_node.children:
            if child.type not in ("super_interfaces", "extends_interfaces"):
                continue
            for sub in child.children:
                if sub.type != "type_list":
                    continue
                for tl_child in sub.children:
                    if tl_child.type == ",":
                        continue
                    name = TreeSitterParser._java_type_list_simple_name(tl_child)
                    if name:
                        out.append(name)
        return out

    @staticmethod
    def _java_field_modifiers_private_final(node: Node) -> tuple[bool, bool]:
        private = False
        final = False
        for child in node.children:
            if child.type != "modifiers":
                continue
            for m in child.children:
                if m.type == "private":
                    private = True
                elif m.type == "final":
                    final = True
        return private, final

    @staticmethod
    def _java_field_decl_type_simple_name(node: Node) -> str:
        for child in node.children:
            if child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                return TreeSitterParser._java_di_simple_name_from_type_node(child)
        return ""

    @staticmethod
    def _java_di_simple_name_from_type_node(tnode: Node) -> str:
        if tnode.type == "type_identifier":
            return TreeSitterParser._node_text(tnode).strip()
        if tnode.type == "scoped_type_identifier":
            id_nodes = [c for c in tnode.children if c.type == "type_identifier"]
            if id_nodes:
                return TreeSitterParser._node_text(id_nodes[-1]).strip()
            raw = TreeSitterParser._node_text(tnode).strip()
            return raw.split(".")[-1] if raw else ""
        if tnode.type == "generic_type":
            for c in tnode.children:
                if c.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                    return TreeSitterParser._java_di_simple_name_from_type_node(c)
        return ""

    @staticmethod
    def _java_type_looks_like_spring_bean(simple_name: str) -> bool:
        if not simple_name or not simple_name[0].isupper():
            return False
        return simple_name not in _JAVA_DI_NON_BEAN_SIMPLE_TYPES

    @staticmethod
    def _java_field_is_private_final_bean_candidate(node: Node) -> bool:
        if node.type != "field_declaration":
            return False
        priv, fin = TreeSitterParser._java_field_modifiers_private_final(node)
        if not (priv and fin):
            return False
        simple = TreeSitterParser._java_field_decl_type_simple_name(node)
        return TreeSitterParser._java_type_looks_like_spring_bean(simple)

    @staticmethod
    def _extract_java_fields(
        tree: "Tree", source: bytes, file_path: str, result: ParseResult,
    ) -> list[ParsedField]:
        """Extract annotated field declarations from Java class bodies."""
        fields: list[ParsedField] = []

        def _visit(node: Node) -> None:
            if node.type == "field_declaration":
                annotations = TreeSitterParser._extract_java_annotations_from_node(node)
                inferred_ctor = False
                if not annotations:
                    if TreeSitterParser._java_field_is_private_final_bean_candidate(node):
                        inferred_ctor = True
                    else:
                        return

                field_type = ""
                field_name = ""
                for child in node.children:
                    if child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                        field_type = (child.text.decode("utf-8") if child.text else "").strip()
                    elif child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node and name_node.text:
                            field_name = name_node.text.decode("utf-8").strip()

                if not field_name:
                    return

                parent_class = ""
                parent = node.parent
                while parent:
                    if parent.type in ("class_declaration", "interface_declaration"):
                        for ch in parent.children:
                            if ch.type == "identifier":
                                parent_class = (ch.text.decode("utf-8") if ch.text else "").strip()
                                break
                        break
                    parent = parent.parent

                inj = "constructor" if inferred_ctor else ""
                fields.append(ParsedField(
                    name=field_name,
                    field_type=field_type,
                    file=file_path,
                    line=node.start_point[0] + 1,
                    annotations=annotations,
                    parent_class=parent_class,
                    injection_type=inj,
                ))
                return

            for child in node.children:
                _visit(child)

        _visit(tree.root_node)
        return fields

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
