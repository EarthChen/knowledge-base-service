"""Go language plugin — extraction aligned with TreeSitterParser Go branches."""

from __future__ import annotations

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

_GO_QUERIES: dict[str, str] = {
    "function": "(function_declaration name: (identifier) @func.name) @func.def",
    "class": "(type_declaration (type_spec name: (type_identifier) @class.name)) @class.def",
    "import": "(import_spec path: (interpreted_string_literal) @import.name) @import.stmt",
    "call": "(call_expression function: [(identifier) @call.name (selector_expression field: (field_identifier) @call.name)]) @call.expr",
}


class GoPlugin(BaseLanguagePlugin):
    def __init__(self) -> None:
        super().__init__()
        self._package_cache: dict[str, str] = {}

    @staticmethod
    def _normalize_go_file_path(file_path: str) -> str:
        return file_path.replace("\\", "/")

    def _cache_package_from_tree(self, root_node: Node, file_path: str) -> None:
        fp = self._normalize_go_file_path(file_path)
        for child in root_node.children:
            if child.type != "package_clause":
                continue
            for ch in child.children:
                if ch.type == "package_identifier":
                    name = ch.text.decode("utf-8") if ch.text else ""
                    if name:
                        self._package_cache[fp] = name
                    return
            return

    @property
    def name(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> list[str]:
        return [".go"]

    @property
    def concepts(self) -> list[str]:
        return [
            "goroutines",
            "channels",
            "interfaces",
            "defer statements",
            "error-as-return-value",
            "struct embedding",
            "context package",
        ]

    def get_queries(self) -> dict[str, str]:
        return dict(_GO_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        self._cache_package_from_tree(tree.root_node, file_path)
        imports: list[ParsedImport] = []
        lang = get_language("go")
        query_str = _GO_QUERIES["import"]
        try:
            q = Query(lang, query_str)
        except Exception as exc:
            log.warning("query_parse_error", language="go", query_type="import", error=str(exc))
            return imports

        cursor = QueryCursor(q)
        for _pattern_idx, match_captures in cursor.matches(tree.root_node):
            import_nodes = match_captures.get("import.stmt", [])
            name_nodes = match_captures.get("import.name", []) + match_captures.get("import.module", [])
            if not import_nodes or not name_nodes:
                continue
            import_node = import_nodes[0]
            line = import_node.start_point[0] + 1
            raw = name_nodes[0].text.decode("utf-8") if name_nodes[0].text else ""
            module = BaseLanguagePlugin._strip_string_delimiters(raw)
            imp = ParsedImport(
                module=module,
                names=[],
                file=file_path,
                line=line,
                language="go",
            )
            BaseLanguagePlugin._finalize_import_symbols(imp)
            imports.append(imp)
        return imports

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
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
                    names.append(self._node_text(chs[i]))
                    i += 1
                    if i < len(chs) and chs[i].type == ",":
                        i += 1
                        continue
                    break
                break
            typ = "".join(self._node_text(chs[j]) for j in range(i, len(chs))).strip()
            for n in names:
                out.append({"name": n, "type": typ})
        return out

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        return self._extract_return_type_go(func_node)

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
        return "".join(BaseLanguagePlugin._node_text(c) for c in segment[2:]).strip()

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        return [], []

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return self._extract_go_style_docstring(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return self._extract_go_style_docstring(func_node)

    @staticmethod
    def _extract_go_style_docstring(node: Node) -> str:
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
        return self._extract_file_header_comment_go(root_node)

    @staticmethod
    def _extract_file_header_comment_go(root_node: Node) -> str:
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
        fp = self._normalize_go_file_path(file_path)
        pkg = self._package_cache.get(fp) or self._go_package_from_file(fp)
        if label == "Class":
            return f"{pkg}.{entity_name}"
        if parent_class:
            return f"{pkg}.{parent_class}.{entity_name}"
        return f"{pkg}.{entity_name}"

    @staticmethod
    def _go_package_from_file(file_path: str) -> str:
        name = Path(file_path.replace("\\", "/")).parent.name
        return name if name else "main"

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
        imp = import_path.strip().strip('"').strip("`")
        if not imp:
            return None

        imp = imp.replace("\\", "/")
        candidates: list[str] = []
        for path in file_index:
            if not path.endswith(".go"):
                continue
            parent = str(Path(path).parent).replace("\\", "/")
            if parent.endswith(imp) or parent.endswith("/" + imp) or parent == imp:
                candidates.append(path)
        if not candidates:
            return None
        return sorted(candidates)[0]
