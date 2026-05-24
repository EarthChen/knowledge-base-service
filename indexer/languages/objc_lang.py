"""Objective-C language plugin — Tree-sitter `objc` grammar."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language

from core.log import get_logger
from indexer.languages._base import (
    DEFAULT_SIGNATURE_BODY_TYPES,
    BaseLanguagePlugin,
)
from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

log = get_logger(__name__)

_OBJ_SIGNATURE_BODIES: frozenset[str] = DEFAULT_SIGNATURE_BODY_TYPES | frozenset({
    "compound_statement",
})

_OBJC_QUERIES: dict[str, str] = {
    "function": """[
      (implementation_definition) @func.def
      (function_definition) @func.def
    ]""",
    "class": """[
      (class_interface (identifier) @class.name) @class.def
      (class_implementation (identifier) @class.name) @class.def
      (protocol_declaration (identifier) @class.name) @class.def
    ]""",
    "import": "(preproc_include) @import.stmt",
    "call": "(message_expression) @call.expr",
}


class ObjectiveCPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "objc"

    @property
    def file_extensions(self) -> list[str]:
        return [".m", ".h"]

    @property
    def concepts(self) -> list[str]:
        return [
            "protocols",
            "categories",
            "blocks",
            "ARC memory management",
            "message passing",
        ]

    @property
    def interop_group(self) -> str | None:
        return "apple"

    def get_queries(self) -> dict[str, str]:
        return dict(_OBJC_QUERIES)

    def accept_class_query_capture(self, class_node: Node, name_node: Node) -> bool:
        if class_node.type in ("class_interface", "class_implementation"):
            for ch in class_node.named_children:
                if ch.type == "identifier":
                    return ch.start_byte == name_node.start_byte
            return False
        return True

    def extract_function_name_from_node(self, func_node: Node, source: bytes) -> str:
        if func_node.type == "implementation_definition":
            for ch in func_node.named_children:
                if ch.type != "method_definition":
                    continue
                for gc in ch.named_children:
                    if gc.type in ("-", "+"):
                        continue
                    if gc.type == "method_type":
                        continue
                    if gc.type == "identifier":
                        return self._node_text(gc).strip()
                    if gc.type != "compound_statement":
                        continue

        if func_node.type == "function_definition":
            for c in func_node.named_children:
                if c.type != "function_declarator":
                    continue
                for sub in c.named_children:
                    if sub.type == "identifier":
                        return self._node_text(sub).strip()
                dc = c.child_by_field_name("declarator")
                if dc and dc.type == "identifier":
                    return self._node_text(dc).strip()

        for c in func_node.named_children:
            if c.type == "identifier":
                return self._node_text(c).strip()

        return ""

    def extract_call_name_from_node(self, call_node: Node, source: bytes) -> str:
        if call_node.type != "message_expression":
            return ""

        sel: list[str] = []
        for ch in call_node.named_children:
            if ch.type == "identifier":
                sel.append(self._node_text(ch).strip())

        if not sel:
            return ""
        if len(sel) == 1:
            return sel[0]
        return sel[-1]

    def extract_signature(self, func_node: Node, source: bytes) -> str:
        return BaseLanguagePlugin._extract_signature_generic(
            func_node,
            source,
            _OBJ_SIGNATURE_BODIES,
        )

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language(self.name)
        try:
            q = Query(lang, _OBJC_QUERIES["import"])
        except Exception as exc:
            log.warning(
                "query_parse_error",
                language=self.name,
                query_type="import",
                error=str(exc),
            )
            return imports

        cursor = QueryCursor(q)
        for _, match_captures in cursor.matches(tree.root_node):
            stmt_nodes = match_captures.get("import.stmt", [])
            if not stmt_nodes:
                continue
            node = stmt_nodes[0]
            line = node.start_point[0] + 1
            path_txt = ""

            named = getattr(node, "named_children", None)
            iterable = named if isinstance(named, list) else node.named_children

            for child in iterable:
                if child.type == "system_lib_string" and child.text:
                    inner = child.text.decode("utf-8").strip()
                    inner = inner.lstrip("<").rstrip(">")
                    path_txt = f"<{inner}>"
                    break
                if child.type == "string_literal" and child.text:
                    path_txt = BaseLanguagePlugin._strip_string_delimiters(
                        child.text.decode("utf-8"),
                    )
                    break

            if path_txt.strip():
                imports.append(
                    ParsedImport(
                        module=path_txt.strip(),
                        names=[],
                        file=file_path,
                        line=line,
                        language=self.name,
                    ),
                )
        for imp in imports:
            BaseLanguagePlugin._finalize_import_symbols(imp)
        return imports

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if func_node.type != "implementation_definition":
            return out
        md = None
        for ch in func_node.named_children:
            if ch.type == "method_definition":
                md = ch
                break
        if md is None:
            return out
        for ch in md.named_children:
            if ch.type == "method_parameter":
                typ = ""
                name = ""
                for sub in ch.named_children:
                    if sub.type == "method_type":
                        typ = self._node_text(sub).strip()
                    elif sub.type == "identifier":
                        name = self._node_text(sub).strip()
                if typ or name:
                    out.append({"name": name, "type": typ})
        return out

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        if func_node.type == "implementation_definition":
            md = None
            for ch in func_node.named_children:
                if ch.type == "method_definition":
                    md = ch
                    break
            if md is None:
                return ""
            for ch in md.named_children:
                if ch.type == "method_type":
                    return self._node_text(ch).strip().strip("()").strip()

        if func_node.type == "function_definition":
            t = func_node.child_by_field_name("type")
            return self._node_text(t).strip()

        blob = func_node.text.decode("utf-8") if func_node.text else ""
        if blob.lstrip().startswith(("-", "+")):
            lpar = blob.find("(")
            rpar = blob.find(")", lpar + 1) if lpar != -1 else -1
            if lpar != -1 and rpar != -1:
                return blob[lpar + 1 : rpar].strip()
        return ""

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        identifiers = [ch for ch in class_node.named_children if ch.type == "identifier"]
        if class_node.type in ("class_interface", "class_implementation") and len(identifiers) >= 2:
            return [self._node_text(identifiers[1]).strip()], []
        return [], []

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        return []

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return BaseLanguagePlugin._extract_block_comment_above(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return BaseLanguagePlugin._extract_block_comment_above(func_node)

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        anchor = None
        for child in root_node.named_children:
            if child.type in ("class_interface", "protocol_declaration"):
                anchor = child
                break

        if anchor is None:
            return ""

        prev = anchor.prev_named_sibling
        while prev:
            raw = ""
            cleaned = ""

            if prev.type in ("block_comment", "multiline_comment") and prev.text:
                raw = prev.text.decode("utf-8")
                cleaned = raw.strip().strip("/* \n\t")
            elif prev.type == "comment" and prev.text:
                raw = prev.text.decode("utf-8").strip()
                cleaned = raw[2:].strip() if raw.startswith("//") else raw.strip()
            elif prev.type == "line_comment" and prev.text:
                raw = prev.text.decode("utf-8").strip()
                cleaned = raw[2:].strip() if raw.startswith("//") else raw.strip()
            elif prev.type == "preproc_include":
                prev = prev.prev_named_sibling
                continue

            if cleaned and prev.type in (
                "block_comment",
                "multiline_comment",
                "comment",
                "line_comment",
            ):
                if BaseLanguagePlugin._is_license_comment(cleaned):
                    prev = prev.prev_named_sibling
                    continue
                return cleaned.strip()

            if prev.type not in ("preproc_include", "macro_type", "declaration"):
                break
            prev = prev.prev_named_sibling

        return ""

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        if call_node.type != "message_expression":
            return ""

        kids = getattr(call_node, "children", [])
        for i, ch in enumerate(kids):
            if ch.text == b"[" or getattr(ch, "type", "") == "[":
                if i + 1 < len(kids):
                    recv = kids[i + 1]
                    return recv.text.decode("utf-8").strip() if recv.text else ""
                break

        nc = getattr(call_node, "named_children", ())
        return self._node_text(nc[0]) if nc else ""

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        if label == "Class":
            return entity_name
        if label == "Function" and parent_class:
            return f"{parent_class}.{entity_name}"
        mod = self.build_module_name(file_path)
        if mod:
            return f"{mod}.{entity_name}"
        return entity_name

    def build_module_name(self, file_path: str) -> str:
        fp = file_path.replace("\\", "/")
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
        if not ip:
            return None
        if ip.startswith("<") and ip.endswith(">"):
            return None

        target = Path(ip).name
        if not target.endswith(".h"):
            target = f"{target}.h"
        posix_src = source_file.replace("\\", "/")

        ranked: list[tuple[int, int, str]] = []
        for path in file_index:
            posix_p = path.replace("\\", "/")
            if posix_p.endswith("/" + target) or Path(posix_p).name == target:
                common = sum(
                    1
                    for a, b in zip(posix_src.split("/")[:-1], posix_p.split("/")[:-1])
                    if a == b
                )
                depth_score = posix_p.count("/")
                ranked.append((common, -depth_score, path))
        ranked.sort(reverse=True)
        return ranked[0][2] if ranked else BaseLanguagePlugin._pick_from_reverse(
            reverse_index,
            Path(target).stem,
        )

    def should_include_function(self, func_node: Node) -> bool:
        return True

    def extract_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        result: ParseResult,
    ) -> list[ParsedField]:
        return []
