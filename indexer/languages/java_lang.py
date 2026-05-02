"""Java language plugin — extraction aligned with TreeSitterParser Java branches."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language

from indexer.languages._base import BaseLanguagePlugin
from indexer.languages._jvm_common import compute_jvm_fqn
from indexer.tree_sitter_parser import ParsedField, ParsedImport, ParseResult

from core.log import get_logger

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

log = get_logger(__name__)

_JAVA_QUERIES: dict[str, str] = {
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
}

_JAVA_DI_NON_BEAN_SIMPLE_TYPES: frozenset[str] = frozenset({
    "String",
    "Boolean",
    "Byte",
    "Character",
    "Double",
    "Float",
    "Integer",
    "Long",
    "Short",
    "Object",
    "Void",
    "Class",
    "Throwable",
    "Exception",
    "RuntimeException",
    "List",
    "Map",
    "Set",
    "Collection",
    "Iterable",
    "Optional",
    "Stream",
})


class JavaPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "java"

    @property
    def file_extensions(self) -> list[str]:
        return [".java"]

    @property
    def interop_group(self) -> str | None:
        return "jvm"

    def get_queries(self) -> dict[str, str]:
        return dict(_JAVA_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language("java")
        query_str = _JAVA_QUERIES["import"]
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language="java", query_type="import", error=str(exc))
            return imports

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            import_nodes = match_captures.get("import.stmt", [])
            name_nodes = match_captures.get("import.name", []) + match_captures.get("import.module", [])
            if not import_nodes or not name_nodes:
                continue
            import_node = import_nodes[0]
            line = import_node.start_point[0] + 1
            module = name_nodes[0].text.decode("utf-8").strip() if name_nodes[0].text else ""
            imp = ParsedImport(
                module=module,
                names=[],
                file=file_path,
                line=line,
                language="java",
            )
            BaseLanguagePlugin._finalize_import_symbols(imp)
            imports.append(imp)
        return imports

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
            if ch.type == "formal_parameter":
                t = ch.child_by_field_name("type")
                n = ch.child_by_field_name("name")
                out.append({
                    "name": self._node_text(n),
                    "type": self._node_text(t),
                })
            elif ch.type == "spread_parameter":
                typ = ""
                pname = ""
                for sp in ch.children:
                    if sp.type == "variable_declarator":
                        for vv in sp.children:
                            if vv.type == "identifier":
                                pname = self._node_text(vv)
                    else:
                        typ += self._node_text(sp)
                out.append({"name": pname, "type": typ})
        return out

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        return self._node_text(func_node.child_by_field_name("type")).strip()

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        bases: list[str] = []
        generic_params: list[str] = []
        for child in class_node.children:
            if child.type == "superclass":
                if child.text:
                    raw = child.text.decode("utf-8").replace("extends ", "").strip()
                    bases.append(raw)
                    generic_params.extend(self._java_type_arguments_from_super_ref(child))
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
                        generic_params.extend(self._java_type_arguments_from_type_list_child(tl_child))
            elif child.type == "super_interfaces":
                for sub in child.children:
                    if sub.type != "type_list":
                        continue
                    for tl_child in sub.children:
                        if tl_child.type == ",":
                            continue
                        generic_params.extend(self._java_type_arguments_from_type_list_child(tl_child))
        return bases, generic_params

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
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
                    name = self._java_type_list_simple_name(tl_child)
                    if name:
                        out.append(name)
        return out

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        return self._extract_java_annotations_from_node(node)

    @staticmethod
    def _extract_java_annotations_from_node(node: Node) -> list[str]:
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

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return self._extract_java_style_docstring(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return self._extract_java_style_docstring(func_node)

    @staticmethod
    def _extract_java_style_docstring(node: Node) -> str:
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
        return self._extract_file_header_comment_java(root_node)

    @staticmethod
    def _extract_file_header_comment_java(root_node: Node) -> str:
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

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        obj = call_node.child_by_field_name("object")
        if obj is not None and obj.text:
            return obj.text.decode("utf-8")
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
            file_suffix=".java",
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
        suffix = ip.replace(".", "/") + ".java"
        for path in file_index:
            if path.endswith(suffix):
                return path
        return BaseLanguagePlugin._pick_from_reverse(reverse_index, ip)

    def extract_fields(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        result: ParseResult,
    ) -> list[ParsedField]:
        fields: list[ParsedField] = []

        def _visit(node: Node) -> None:
            if node.type == "field_declaration":
                annotations = self._extract_java_annotations_from_node(node)
                inferred_ctor = False
                if not annotations:
                    if self._java_field_is_private_final_bean_candidate(node):
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
                fields.append(
                    ParsedField(
                        name=field_name,
                        field_type=field_type,
                        file=file_path,
                        line=node.start_point[0] + 1,
                        annotations=annotations,
                        parent_class=parent_class,
                        injection_type=inj,
                    ),
                )
                return

            for child in node.children:
                _visit(child)

        _visit(tree.root_node)
        return fields

    def _java_field_modifiers_private_final(self, node: Node) -> tuple[bool, bool]:
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

    def _java_field_decl_type_simple_name(self, node: Node) -> str:
        for child in node.children:
            if child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                return self._java_di_simple_name_from_type_node(child)
        return ""

    def _java_di_simple_name_from_type_node(self, tnode: Node) -> str:
        if tnode.type == "type_identifier":
            return self._node_text(tnode).strip()
        if tnode.type == "scoped_type_identifier":
            id_nodes = [c for c in tnode.children if c.type == "type_identifier"]
            if id_nodes:
                return self._node_text(id_nodes[-1]).strip()
            raw = self._node_text(tnode).strip()
            return raw.split(".")[-1] if raw else ""
        if tnode.type == "generic_type":
            for c in tnode.children:
                if c.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                    return self._java_di_simple_name_from_type_node(c)
        return ""

    @staticmethod
    def _java_type_looks_like_spring_bean(simple_name: str) -> bool:
        if not simple_name or not simple_name[0].isupper():
            return False
        return simple_name not in _JAVA_DI_NON_BEAN_SIMPLE_TYPES

    def _java_field_is_private_final_bean_candidate(self, node: Node) -> bool:
        if node.type != "field_declaration":
            return False
        priv, fin = self._java_field_modifiers_private_final(node)
        if not (priv and fin):
            return False
        simple = self._java_field_decl_type_simple_name(node)
        return self._java_type_looks_like_spring_bean(simple)

    def _java_type_arguments_from_super_ref(self, super_node: Node) -> list[str]:
        for ch in super_node.children:
            if ch.type == "generic_type":
                return self._java_type_arguments_from_generic_type(ch)
        return []

    def _java_type_arguments_from_type_list_child(self, tl_child: Node) -> list[str]:
        if tl_child.type == "generic_type":
            return self._java_type_arguments_from_generic_type(tl_child)
        return []

    def _java_type_arguments_from_generic_type(self, gt: Node) -> list[str]:
        out: list[str] = []
        for ch in gt.children:
            if ch.type != "type_arguments":
                continue
            for arg in ch.children:
                if arg.type == ",":
                    continue
                name = self._java_type_argument_simple_name(arg)
                if name:
                    out.append(name)
        return out

    def _java_type_argument_simple_name(self, node: Node) -> str:
        if node.type == "type_identifier":
            return self._node_text(node).strip()
        if node.type == "generic_type":
            for c in node.children:
                if c.type in ("type_identifier", "scoped_type_identifier"):
                    return self._java_type_identifier_simple(c)
        if node.type == "scoped_type_identifier":
            return self._java_type_identifier_simple(node)
        return ""

    def _java_type_identifier_simple(self, node: Node) -> str:
        if node.type == "type_identifier":
            return self._node_text(node).strip()
        if node.type == "scoped_type_identifier":
            id_nodes = [c for c in node.children if c.type == "type_identifier"]
            if id_nodes:
                return self._node_text(id_nodes[-1]).strip()
        return self._node_text(node).strip()

    def _java_type_list_simple_name(self, type_node: Node) -> str:
        if type_node.type == "type_identifier":
            return self._node_text(type_node).strip()
        if type_node.type == "scoped_type_identifier":
            id_nodes = [c for c in type_node.children if c.type == "type_identifier"]
            if id_nodes:
                return self._node_text(id_nodes[-1]).strip()
            raw = self._node_text(type_node).strip()
            return raw.split(".")[-1] if raw else ""
        if type_node.type == "generic_type":
            for c in type_node.children:
                if c.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                    return self._java_type_list_simple_name(c)
        return ""
