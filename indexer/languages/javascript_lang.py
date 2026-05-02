"""JavaScript / TypeScript language plugins — extraction aligned with TreeSitterParser JS/TS branches."""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language

from indexer.languages._base import BaseLanguagePlugin
from indexer.tree_sitter_parser import ParsedImport

from core.log import get_logger

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

log = get_logger(__name__)

_JS_QUERIES: dict[str, str] = {
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
}

_TS_QUERIES: dict[str, str] = {
    **_JS_QUERIES,
    "class": "(class_declaration name: (type_identifier) @class.name) @class.def",
}

_JS_TS_EXTS_LONGEST_FIRST = (
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".d.ts",
    ".ts",
    ".js",
)

_JS_TS_EXTS_TRY_ORDER = (
    ".tsx",
    ".jsx",
    ".ts",
    ".js",
    ".mjs",
    ".cjs",
)

_JS_INDEX_NAMES = frozenset({"index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs", "index.cjs"})


class JavaScriptPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "javascript"

    @property
    def file_extensions(self) -> list[str]:
        return [".js", ".jsx", ".mjs"]

    @property
    def interop_group(self) -> str | None:
        return "js"

    def get_queries(self) -> dict[str, str]:
        return dict(_JS_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language(self.name)
        query_str = self.get_queries()["import"]
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language=self.name, query_type="import", error=str(exc))
            return imports

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            import_nodes = match_captures.get("import.stmt", [])
            name_nodes = match_captures.get("import.name", []) + match_captures.get("import.module", [])
            if not import_nodes or not name_nodes:
                continue
            import_node = import_nodes[0]
            imp = self._parsed_import_js_ts(import_node, file_path)
            BaseLanguagePlugin._finalize_import_symbols(imp)
            imports.append(imp)
        return imports

    def _parsed_import_js_ts(self, import_node: Node, file_path: str) -> ParsedImport:
        line = import_node.start_point[0] + 1
        src = import_node.child_by_field_name("source")
        raw_src = self._node_text(src)
        module = BaseLanguagePlugin._strip_string_delimiters(raw_src)
        clause = next((c for c in import_node.children if c.type == "import_clause"), None)
        syms = self._js_ts_import_clause_symbols(clause)
        return ParsedImport(
            module=module,
            names=list(syms),
            file=file_path,
            line=line,
            language=self.name,
        )

    def _js_ts_import_clause_symbols(self, clause: Node | None) -> list[str]:
        if clause is None:
            return []
        syms: list[str] = []
        for ch in clause.children:
            if ch.type == "identifier":
                syms.append(self._node_text(ch))
            elif ch.type == "named_imports":
                for sub in ch.children:
                    if sub.type != "import_specifier":
                        continue
                    name_n = sub.child_by_field_name("name")
                    alias_n = sub.child_by_field_name("alias")
                    if alias_n is not None and self._node_text(alias_n):
                        syms.append(self._node_text(alias_n))
                    elif name_n is not None:
                        syms.append(self._node_text(name_n))
            elif ch.type == "namespace_import":
                for sub in ch.children:
                    if sub.type == "identifier":
                        syms.append(self._node_text(sub))
        return syms

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
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
                out.append({"name": self._node_text(ch), "type": ""})
            elif ch.type in ("required_parameter", "optional_parameter"):
                pat = ch.child_by_field_name("pattern")
                name = self._ts_js_pattern_name(pat)
                tnode = ch.child_by_field_name("type")
                typ = self._strip_type_annotation(tnode) if tnode else ""
                if name:
                    out.append({"name": name, "type": typ})
        return out

    def _ts_js_pattern_name(self, pattern: Node | None) -> str:
        if pattern is None:
            return ""
        if pattern.type == "identifier":
            return self._node_text(pattern)
        if pattern.type == "rest_pattern":
            for ch in pattern.children:
                if ch.type == "identifier":
                    return self._node_text(ch)
        return self._node_text(pattern)

    def _strip_type_annotation(self, node: Node | None) -> str:
        if node is None:
            return ""
        raw = self._node_text(node)
        if node.type == "type_annotation":
            return raw.lstrip().lstrip(":").strip()
        return raw.strip()

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        rt = func_node.child_by_field_name("return_type")
        return self._strip_type_annotation(rt) if rt else ""

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        bases: list[str] = []
        generic_params: list[str] = []
        for child in class_node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type == "identifier" and arg.text:
                        bases.append(arg.text.decode("utf-8"))
            elif child.type == "superclass":
                if child.text:
                    raw = child.text.decode("utf-8").replace("extends ", "").strip()
                    bases.append(raw)
            elif child.type == "extends_interfaces":
                for sub in child.children:
                    if sub.type != "type_list":
                        continue
                    for tl_child in sub.children:
                        if tl_child.type == ",":
                            continue
                        raw = self._node_text(tl_child).strip()
                        if raw:
                            bases.append(raw)
            elif child.type == "class_heritage":
                for sub in child.children:
                    if sub.type == "identifier" and sub.text:
                        bases.append(sub.text.decode("utf-8"))
        return bases, generic_params

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
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

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        func_child = call_node.child_by_field_name("function")
        if func_child is not None and func_child.type == "member_expression":
            obj = func_child.child_by_field_name("object")
            if obj is not None and obj.text:
                return obj.text.decode("utf-8")
        return ""

    def should_include_function(self, func_node: Node) -> bool:
        if func_node.type == "arrow_function":
            lex = self._lexical_declaration_for_arrow_binding(func_node)
            if lex is None or not self._is_module_level(lex):
                return False
        return True

    @staticmethod
    def _is_module_level(node: Node) -> bool:
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
        p = arrow.parent
        if p is None or p.type != "variable_declarator":
            return None
        p = p.parent
        if p is None or p.type != "lexical_declaration":
            return None
        return p

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return self._extract_js_ts_block_docstring(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return self._extract_js_ts_block_docstring(func_node)

    @staticmethod
    def _extract_js_ts_block_docstring(node: Node) -> str:
        prev = node.prev_named_sibling
        while prev and prev.type in (
            "decorator",
            "annotation",
            "marker_annotation",
            "modifiers",
            "module_attribute",
        ):
            prev = prev.prev_named_sibling
        if prev and prev.type in ("comment", "block_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            return raw.strip("/* \n\t")
        return ""

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        return self._extract_file_header_comment_js_ts(root_node)

    @staticmethod
    def _extract_file_header_comment_js_ts(root_node: Node) -> str:
        first_class = None
        for child in root_node.children:
            if child.type in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "annotation_type_declaration",
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
            "decorator",
            "annotation",
            "marker_annotation",
            "modifiers",
        ):
            prev = prev.prev_named_sibling

        if prev and prev.type in ("comment", "block_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            cleaned = raw.strip("/* \n\t")
            if BaseLanguagePlugin._is_license_comment(cleaned):
                return ""
            return cleaned

        return ""

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        fp = file_path.replace("\\", "/")
        mod = self._js_ts_module_prefix(fp)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    @staticmethod
    def _js_ts_suffix(lower_name: str) -> str | None:
        for ext in _JS_TS_EXTS_LONGEST_FIRST:
            if lower_name.endswith(ext):
                return ext
        return None

    def _js_ts_module_prefix(self, file_path: str) -> str:
        fp = file_path.replace("\\", "/")
        lower = fp.lower()
        ext = self._js_ts_suffix(lower)
        if ext:
            return fp[: -len(ext)].lstrip("./")
        return Path(fp).with_suffix("").as_posix().lstrip("./")

    def build_module_name(self, file_path: str) -> str:
        fp = file_path.replace("\\", "/")
        lower = fp.lower()
        if any(lower.endswith(ext) for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
            p = Path(fp)
            stem = p.stem.lower()
            parent_parts = [x for x in p.parent.parts if x not in (".",)]
            if stem == "index":
                return ".".join(parent_parts) if parent_parts else stem
            return ".".join([*parent_parts, p.stem])
        stem = Path(fp).stem
        dir_parts = [x for x in Path(fp).parent.parts if x not in (".",)]
        return ".".join([*dir_parts, stem])

    def resolve_import(
        self,
        import_path: str,
        source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None:
        ip = import_path.strip()
        if not ip.startswith((".", "/")):
            return None
        src = ip.replace("\\", "/")
        sf = source_file.replace("\\", "/")
        src_dir = posixpath.dirname(sf)
        joined = posixpath.normpath(posixpath.join(src_dir, src))
        rel = joined.lstrip("/")
        if rel.startswith("../"):
            parts: list[str] = []
            for seg in rel.split("/"):
                if seg == "..":
                    if parts:
                        parts.pop()
                elif seg and seg != ".":
                    parts.append(seg)
            rel = "/".join(parts)

        base_path = Path(rel)

        def try_file(rel_path: str) -> str | None:
            rp = rel_path.replace("\\", "/")
            if rp in file_index:
                return rp
            return None

        direct = try_file(rel)
        if direct:
            return direct

        for ext in _JS_TS_EXTS_TRY_ORDER:
            hit = try_file(f"{rel}{ext}")
            if hit:
                return hit

        for name in _JS_INDEX_NAMES:
            hit = try_file(f"{rel}/{name}")
            if hit:
                return hit

        for ext in _JS_TS_EXTS_TRY_ORDER:
            hit = try_file(f"{rel}/index{ext}")
            if hit:
                return hit

        stem = base_path.name
        parent = base_path.parent
        if stem:
            mod_key = ".".join([*[p for p in parent.parts if p != "."], stem])
            hit = BaseLanguagePlugin._pick_from_reverse(reverse_index, mod_key)
            if hit:
                return hit

        return None


class TypeScriptPlugin(JavaScriptPlugin):
    @property
    def name(self) -> str:
        return "typescript"

    @property
    def file_extensions(self) -> list[str]:
        return [".ts", ".tsx"]

    def get_queries(self) -> dict[str, str]:
        return dict(_TS_QUERIES)
