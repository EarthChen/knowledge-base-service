"""Swift language plugin — extraction aligned with TreeSitterParser Swift grammar."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language

from core.log import get_logger
from indexer.languages._base import BaseLanguagePlugin
from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

log = get_logger(__name__)

_SWIFT_QUERIES: dict[str, str] = {
    "function": "(function_declaration name: (simple_identifier) @func.name) @func.def",
    "class": """[
      (class_declaration (type_identifier) @class.name) @class.def
      (protocol_declaration (type_identifier) @class.name) @class.def
    ]""",
    "import": "(import_declaration) @import.stmt",
    "call": """[
      (call_expression (simple_identifier) @call.name) @call.expr
      (call_expression (navigation_expression (simple_identifier) @call.name)) @call.expr
    ]""",
}


class SwiftPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "swift"

    @property
    def file_extensions(self) -> list[str]:
        return [".swift"]

    @property
    def interop_group(self) -> str | None:
        return "apple"

    def get_queries(self) -> dict[str, str]:
        return dict(_SWIFT_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language("swift")
        query_str = _SWIFT_QUERIES["import"]
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language="swift", query_type="import", error=str(exc))
            return imports

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            stmt_nodes = match_captures.get("import.stmt", [])
            if not stmt_nodes:
                continue
            decl = stmt_nodes[0]
            line = decl.start_point[0] + 1
            module = self._swift_import_module_name(decl)
            imp = ParsedImport(
                module=module,
                names=[],
                file=file_path,
                line=line,
                language="swift",
            )
            BaseLanguagePlugin._finalize_import_symbols(imp)
            imports.append(imp)
        return imports

    @staticmethod
    def _swift_import_module_name(decl: Node) -> str:
        for ch in decl.named_children:
            if ch.type != "identifier":
                continue
            parts = [
                sub.text.decode("utf-8").strip()
                for sub in ch.named_children
                if sub.type == "simple_identifier" and sub.text
            ]
            if parts:
                return ".".join(parts)
            if ch.text:
                return ch.text.decode("utf-8").strip()
        return ""

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for ch in func_node.children:
            if ch.type != "parameter":
                continue
            pname = self._swift_parameter_internal_name(ch)
            ptype = self._swift_parameter_type(ch)
            out.append({"name": pname, "type": ptype})
        return out

    @staticmethod
    def _swift_parameter_internal_name(param: Node) -> str:
        ids_before_colon: list[str] = []
        for ch in param.children:
            if ch.type == ":":
                break
            if ch.type != "simple_identifier" or not ch.text:
                continue
            ids_before_colon.append(ch.text.decode("utf-8").strip())
        return ids_before_colon[-1] if ids_before_colon else ""

    def _swift_parameter_type(self, param: Node) -> str:
        for ch in param.named_children:
            if ch.type == "user_type":
                return self._swift_user_type_text(ch).strip()
        for ch in param.children:
            if ch.type == "user_type":
                return self._swift_user_type_text(ch).strip()
        return ""

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        children = list(func_node.children)
        for i, ch in enumerate(children):
            if ch.type == "->" and i + 1 < len(children) and children[i + 1].type == "user_type":
                return self._swift_user_type_text(children[i + 1]).strip()
        return ""

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        bases: list[str] = []
        generic_params: list[str] = []
        for child in class_node.named_children:
            if child.type != "inheritance_specifier":
                continue
            if child.text:
                bases.append(child.text.decode("utf-8").strip())
            generic_params.extend(self._swift_type_arguments_recursive(child))
        return bases, generic_params

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        self._swift_collect_attributes(node, out)
        return out

    def _swift_collect_attributes(self, node: Node, out: list[str]) -> None:
        for child in node.children:
            if child.type != "modifiers":
                continue
            for mc in child.named_children:
                if mc.type == "attribute" and mc.text:
                    txt = mc.text.decode("utf-8").strip()
                    if txt:
                        out.append(txt)

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return self._swift_normalize_doc(BaseLanguagePlugin._extract_block_comment_above(class_node))

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return self._swift_normalize_doc(BaseLanguagePlugin._extract_block_comment_above(func_node))

    @staticmethod
    def _swift_normalize_doc(s: str) -> str:
        if not s:
            return s
        t = s.lstrip("/").strip()
        return t if t else s

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        first_cls = None
        for child in root_node.named_children:
            if child.type == "class_declaration":
                first_cls = child
                break
        if first_cls is None:
            return ""

        prev = first_cls.prev_named_sibling
        while prev and prev.type in (
            "attribute",
            "modifiers",
            "import_declaration",
            "line_comment",
        ):
            prev = prev.prev_named_sibling

        if prev and prev.type in ("comment", "block_comment", "multiline_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            cleaned = raw.strip()
            if prev.type in ("block_comment", "multiline_comment"):
                cleaned = cleaned.strip("/* \n\t")
            elif prev.type == "comment" and cleaned.startswith("//"):
                cleaned = cleaned.lstrip("/").strip()
            if BaseLanguagePlugin._is_license_comment(cleaned):
                return ""
            return cleaned

        return ""

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        nav = None
        for ch in call_node.named_children:
            if ch.type == "navigation_expression":
                nav = ch
                break
        if nav is None:
            return ""
        return self._swift_receiver_from_navigation(nav)

    @staticmethod
    def _swift_receiver_from_navigation(nav: Node) -> str:
        nc = list(nav.named_children)
        if not nc:
            return ""
        first = nc[0]
        if first.type == "navigation_expression":
            txt = BaseLanguagePlugin._node_text(first)
            return txt.strip()
        if first.type == "simple_identifier":
            if any(c.type == "navigation_suffix" for c in nc[1:]):
                return BaseLanguagePlugin._node_text(first).strip()
        return ""

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

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        mod = self._swift_module_prefix(file_path.replace("\\", "/"))
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    @staticmethod
    def _swift_module_prefix(normalized_fp: str) -> str:
        fp = normalized_fp.lstrip("./")
        p = Path(fp)
        stem = p.stem
        dir_parts = [x for x in p.parent.parts if x not in (".", "")]
        return ".".join([*dir_parts, stem])

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
        picked = BaseLanguagePlugin._pick_from_reverse(reverse_index, ip)
        if picked:
            return picked
        for path, mod_name in file_index.items():
            if mod_name == ip:
                return path
        return None

    @staticmethod
    def _swift_user_type_text(nt: Node) -> str:
        if nt.text:
            return nt.text.decode("utf-8")
        parts: list[str] = []
        for ch in nt.named_children:
            if ch.type == "type_identifier" and ch.text:
                parts.append(ch.text.decode("utf-8"))
            elif ch.type == "user_type":
                parts.append(SwiftPlugin._swift_user_type_text(ch))
            elif ch.type == "type_arguments":
                inn = "".join(SwiftPlugin._swift_type_projection_text(x) for x in ch.named_children)
                parts.append(f"<{inn}>")
        return "".join(parts)

    @staticmethod
    def _swift_type_projection_text(proj: Node) -> str:
        if proj.text:
            return proj.text.decode("utf-8")
        chunks: list[str] = []
        for ch in proj.named_children:
            if ch.type == "user_type":
                chunks.append(SwiftPlugin._swift_user_type_text(ch))
        return "".join(chunks)

    def _swift_type_arguments_recursive(self, root: Node) -> list[str]:
        out: list[str] = []
        stack = list(root.named_children)
        while stack:
            n = stack.pop()
            if n.type == "type_arguments":
                for elt in n.children:
                    if elt.type == "type_identifier" and elt.text:
                        out.append(elt.text.decode("utf-8").strip())
                    elif elt.type == "user_type":
                        simple = self._swift_type_identifier_simple(elt)
                        if simple:
                            out.append(simple)
            stack.extend(n.named_children)
        return out

    def _swift_type_identifier_simple(self, ut: Node) -> str:
        for ch in ut.named_children:
            if ch.type == "type_identifier" and ch.text:
                return ch.text.decode("utf-8").strip()
        raw = BaseLanguagePlugin._node_text(ut).strip()
        return raw.split("<")[0].split("(")[0].strip().split(".")[-1] if raw else ""
