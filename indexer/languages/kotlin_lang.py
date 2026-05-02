"""Kotlin language plugin — extraction aligned with TreeSitterParser Kotlin grammar."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language

from core.log import get_logger
from indexer.languages._base import BaseLanguagePlugin
from indexer.languages._jvm_common import _ALL_JVM_SRC_MARKERS, compute_jvm_fqn
from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

log = get_logger(__name__)

_KOTLIN_QUERIES: dict[str, str] = {
    "function": "(function_declaration (simple_identifier) @func.name) @func.def",
    "class": """[
      (class_declaration (type_identifier) @class.name) @class.def
      (object_declaration (type_identifier) @class.name) @class.def
    ]""",
    "import": "(import_header) @import.stmt",
    "call": """[
      (call_expression (simple_identifier) @call.name) @call.expr
      (call_expression (navigation_expression (simple_identifier) @call.name)) @call.expr
    ]""",
}


class KotlinPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "kotlin"

    @property
    def file_extensions(self) -> list[str]:
        return [".kt", ".kts"]

    @property
    def interop_group(self) -> str | None:
        return "jvm"

    def get_queries(self) -> dict[str, str]:
        return dict(_KOTLIN_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language("kotlin")
        query_str = _KOTLIN_QUERIES["import"]
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language="kotlin", query_type="import", error=str(exc))
            return imports

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            stmt_nodes = match_captures.get("import.stmt", [])
            if not stmt_nodes:
                continue
            header = stmt_nodes[0]
            line = header.start_point[0] + 1
            module = ""
            alias = ""
            for ch in header.named_children:
                if ch.type == "identifier" and ch.text:
                    module = ch.text.decode("utf-8").strip()
                elif ch.type == "import_alias":
                    for sub in ch.named_children:
                        if sub.type == "type_identifier" and sub.text:
                            alias = sub.text.decode("utf-8").strip()
                            break
                elif ch.type == "wildcard_import":
                    if module and not module.endswith(".*"):
                        module = f"{module}.*"
            imp = ParsedImport(
                module=module,
                names=[],
                file=file_path,
                line=line,
                language="kotlin",
                alias=alias,
            )
            BaseLanguagePlugin._finalize_import_symbols(imp)
            imports.append(imp)
        return imports

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        params_node = None
        for ch in func_node.children:
            if ch.type == "function_value_parameters":
                params_node = ch
                break
        if params_node is None:
            return out
        for ch in params_node.named_children:
            if ch.type != "parameter":
                continue
            pname = ""
            ptype = ""
            for sub in ch.named_children:
                if sub.type == "simple_identifier" and sub.text:
                    pname = sub.text.decode("utf-8").strip()
                elif sub.type in ("user_type", "function_type", "nullable_type"):
                    ptype = self._kotlin_user_type_text(sub).strip()
            out.append({"name": pname, "type": ptype})
        return out

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        seen_params = False
        for ch in func_node.named_children:
            if ch.type == "function_value_parameters":
                seen_params = True
                continue
            if not seen_params:
                continue
            if ch.type == "user_type":
                return self._kotlin_user_type_text(ch).strip()
        return ""

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        bases: list[str] = []
        generic_params: list[str] = []
        for child in class_node.named_children:
            if child.type not in ("delegation_specifier", "inheritance_specifier"):
                continue
            if child.text:
                bases.append(child.text.decode("utf-8").strip())
                generic_params.extend(self._kotlin_type_arguments_rec(child))
        return bases, generic_params

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in class_node.named_children:
            if child.type not in ("delegation_specifier", "inheritance_specifier"):
                continue
            nm = self._kotlin_delegation_simple_name(child)
            if nm:
                out.append(nm)
        return out

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        self._kotlin_collect_annotation_nodes(node, out)
        return out

    def _kotlin_collect_annotation_nodes(self, node: Node, out: list[str]) -> None:
        for child in node.children:
            if child.type != "modifiers":
                continue
            for mc in child.named_children:
                if mc.type == "annotation" and mc.text:
                    txt = mc.text.decode("utf-8").strip()
                    if txt:
                        out.append(txt)

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return BaseLanguagePlugin._extract_block_comment_above(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return BaseLanguagePlugin._extract_block_comment_above(func_node)

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        first_cls = None
        for child in root_node.named_children:
            if child.type in ("class_declaration", "object_declaration"):
                first_cls = child
                break
        if first_cls is None:
            return ""

        prev = first_cls.prev_named_sibling
        while prev and prev.type in (
            "annotation",
            "marker_annotation",
            "modifiers",
            "line_comment",
        ):
            prev = prev.prev_named_sibling

        if prev and prev.type in ("comment", "block_comment", "multiline_comment"):
            raw = prev.text.decode("utf-8") if prev.text else ""
            cleaned = raw.strip()
            if prev.type in ("block_comment", "multiline_comment"):
                cleaned = cleaned.strip("/* \n\t")
            elif prev.type == "comment" and cleaned.startswith("//"):
                cleaned = cleaned[2:].strip()
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
        return self._kotlin_receiver_from_nav(nav)

    def _kotlin_receiver_from_nav(self, nav: Node) -> str:
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

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        return compute_jvm_fqn(
            file_path,
            entity_name,
            is_method=(label == "Function"),
            parent_class=parent_class,
            file_suffix=".kt",
            src_markers=_ALL_JVM_SRC_MARKERS,
        )

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
        if ip.endswith(".*"):
            return None
        suffix_kt = ip.replace(".", "/") + ".kt"
        suffix_java = ip.replace(".", "/") + ".java"
        for path in file_index:
            if path.endswith(suffix_kt):
                return path
        for path in file_index:
            if path.endswith(suffix_java):
                return path
        return BaseLanguagePlugin._pick_from_reverse(reverse_index, ip)

    def should_include_function(self, func_node: Node) -> bool:
        return True

    def extract_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        result: ParseResult,
    ) -> list[ParsedField]:
        fields: list[ParsedField] = []

        def _parent_class_name(node: Node) -> str:
            parent = node.parent
            while parent:
                if parent.type in ("class_declaration", "object_declaration"):
                    for ch in parent.named_children:
                        if ch.type == "type_identifier" and ch.text:
                            return ch.text.decode("utf-8").strip()
                    break
                parent = parent.parent
            return ""

        def _visit(node: Node) -> None:
            if node.type == "property_declaration":
                annotations: list[str] = []
                self._kotlin_collect_annotation_nodes(node, annotations)
                field_name = ""
                field_type = ""
                for ch in node.named_children:
                    if ch.type == "variable_declaration":
                        for sub in ch.named_children:
                            if sub.type == "simple_identifier" and sub.text:
                                field_name = sub.text.decode("utf-8").strip()
                            elif sub.type in ("user_type", "nullable_type", "function_type"):
                                field_type = self._kotlin_user_type_text(sub).strip()

                if not field_name:
                    for child in node.children:
                        if child.type == "variable_declaration":
                            for sub in child.named_children:
                                if sub.type == "simple_identifier" and sub.text:
                                    field_name = sub.text.decode("utf-8").strip()
                                elif sub.type in ("user_type", "nullable_type", "function_type"):
                                    field_type = self._kotlin_user_type_text(sub).strip()

                if not field_name:
                    for grand in node.named_children:
                        if grand.type == "multi_variable_declaration":
                            for sub in grand.named_children:
                                if sub.type == "variable_declaration":
                                    for s2 in sub.named_children:
                                        if s2.type == "simple_identifier" and s2.text:
                                            field_name = s2.text.decode("utf-8").strip()

                if field_name:
                    pc = _parent_class_name(node)
                    fields.append(
                        ParsedField(
                            name=field_name,
                            field_type=field_type,
                            file=file_path,
                            line=node.start_point[0] + 1,
                            annotations=annotations,
                            parent_class=pc,
                            injection_type="",
                        ),
                    )

            for child in node.children:
                _visit(child)

        _visit(tree.root_node)
        return fields

    @staticmethod
    def _kotlin_user_type_text(nt: Node) -> str:
        if nt.text:
            return nt.text.decode("utf-8")
        parts: list[str] = []
        for ch in nt.named_children:
            if ch.type == "type_identifier" and ch.text:
                parts.append(ch.text.decode("utf-8"))
            elif ch.type in ("user_type", "nullable_type"):
                parts.append(KotlinPlugin._kotlin_user_type_text(ch))
            elif ch.type == "type_arguments":
                inn = "".join(KotlinPlugin._kotlin_type_projection_text(x) for x in ch.named_children)
                parts.append(f"<{inn}>")
        return "".join(parts)

    @staticmethod
    def _kotlin_type_projection_text(proj: Node) -> str:
        if proj.text:
            return proj.text.decode("utf-8")
        chunks: list[str] = []
        for ch in proj.named_children:
            if ch.type in ("user_type", "nullable_type"):
                chunks.append(KotlinPlugin._kotlin_user_type_text(ch))
            elif ch.type == "projection_type":
                chunks.append(KotlinPlugin._kotlin_projection_raw(ch))
        return "".join(chunks)

    @staticmethod
    def _kotlin_projection_raw(n: Node) -> str:
        return n.text.decode("utf-8") if n.text else ""

    def _kotlin_type_arguments_rec(self, root: Node) -> list[str]:
        out: list[str] = []
        stack = list(root.named_children)
        while stack:
            n = stack.pop()
            if n.type == "type_arguments":
                for arg in n.named_children:
                    if arg.type == "type_projection":
                        nm = self._kotlin_projection_type_name(arg)
                        if nm:
                            out.append(nm)
            stack.extend(n.named_children)
        return out

    def _kotlin_projection_type_name(self, proj: Node) -> str:
        for ch in proj.named_children:
            if ch.type == "user_type":
                return self._kotlin_type_identifier_simple(ch)
        return ""

    def _kotlin_type_identifier_simple(self, ut: Node) -> str:
        for ch in ut.named_children:
            if ch.type == "type_identifier" and ch.text:
                return ch.text.decode("utf-8").strip()
        raw = BaseLanguagePlugin._node_text(ut).strip()
        return raw.split(".")[-1] if raw else ""

    def _kotlin_delegation_simple_name(self, spec: Node) -> str:
        for ch in spec.named_children:
            if ch.type == "constructor_invocation":
                for sub in ch.named_children:
                    if sub.type == "user_type":
                        return self._kotlin_type_identifier_simple(sub)
            if ch.type == "user_type":
                return self._kotlin_type_identifier_simple(ch)
            if ch.type == "type_identifier" and ch.text:
                return ch.text.decode("utf-8").strip()
        raw = BaseLanguagePlugin._node_text(spec).strip()
        token = raw.split("<")[0].split("(")[0].strip().split(".")[-1]
        return token
