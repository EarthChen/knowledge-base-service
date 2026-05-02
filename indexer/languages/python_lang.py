"""Python language plugin — extraction aligned with TreeSitterParser Python branches."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from indexer.languages._base import BaseLanguagePlugin
from indexer.tree_sitter_parser import ParsedImport

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


_PYTHON_QUERIES: dict[str, str] = {
    "function": "(function_definition name: (identifier) @func.name) @func.def",
    "class": "(class_definition name: (identifier) @class.name) @class.def",
    "import": """[
            (import_statement name: (dotted_name) @import.name) @import.stmt
            (import_from_statement module_name: (dotted_name) @import.module) @import.stmt
        ]""",
    "call": "(call function: [(identifier) @call.name (attribute attribute: (identifier) @call.name)]) @call.expr",
}


class PythonPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        return [".py"]

    def get_queries(self) -> dict[str, str]:
        return dict(_PYTHON_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
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
            BaseLanguagePlugin._finalize_import_symbols(imp)
        return imports

    def _python_import_statement_entries(self, node: Node, file_path: str) -> list[ParsedImport]:
        line = node.start_point[0] + 1
        out: list[ParsedImport] = []
        for child in node.children:
            if child.type in ("import", ","):
                continue
            if child.type == "dotted_name":
                mod = self._python_dotted_name_text(child)
                loc = self._python_import_stmt_local_name(child)
                out.append(
                    ParsedImport(
                        module=mod,
                        names=[loc],
                        file=file_path,
                        line=line,
                        language="python",
                    ),
                )
            elif child.type == "aliased_import":
                dn = child.child_by_field_name("name")
                al = child.child_by_field_name("alias")
                mod = self._python_dotted_name_text(dn) if dn else ""
                loc = self._node_text(al) if al else mod
                out.append(
                    ParsedImport(
                        module=mod,
                        names=[loc],
                        file=file_path,
                        line=line,
                        language="python",
                    ),
                )
        return out

    def _python_import_from_statement_entry(self, node: Node, file_path: str) -> ParsedImport:
        mod = self._python_import_from_module_string(node)
        line = node.start_point[0] + 1
        bindings = self._python_from_import_bindings(node)
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

    def _python_import_stmt_local_name(self, dn: Node) -> str:
        ids = [self._node_text(c) for c in dn.children if c.type == "identifier"]
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

    def _python_from_import_bindings(self, node: Node) -> list[str]:
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
                ids = [self._node_text(c) for c in child.children if c.type == "identifier"]
                bindings.append(ids[-1] if ids else self._python_dotted_name_text(child))
            elif child.type == "aliased_import":
                al = child.child_by_field_name("alias")
                bindings.append(self._node_text(al) if al else "")
        return [b for b in bindings if b]

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        params = func_node.child_by_field_name("parameters")
        if params is None:
            return out
        for child in params.children:
            if child.type in ("typed_parameter", "typed_default_parameter"):
                pname = self._python_parameter_name(child)
                ptype = self._python_parameter_type(child)
                if pname and pname not in ("self", "cls"):
                    out.append({"name": pname, "type": ptype})
            elif child.type == "default_parameter":
                for gc in child.children:
                    if gc.type == "identifier":
                        n = self._node_text(gc)
                        if n and n not in ("self", "cls"):
                            out.append({"name": n, "type": ""})
                        break
            elif child.type == "identifier":
                n = self._node_text(child)
                if n and n not in ("self", "cls"):
                    out.append({"name": n, "type": ""})
            elif child.type == "list_splat_pattern":
                for gc in child.children:
                    if gc.type == "identifier":
                        out.append({"name": self._node_text(gc), "type": ""})
                        break
            elif child.type == "dictionary_splat_pattern":
                for gc in child.children:
                    if gc.type == "identifier":
                        out.append({"name": self._node_text(gc), "type": ""})
                        break
        return out

    def _python_parameter_name(self, param: Node) -> str:
        for ch in param.children:
            if ch.type == "identifier":
                return self._node_text(ch)
            if ch.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                for gc in ch.children:
                    if gc.type == "identifier":
                        return self._node_text(gc)
        return ""

    def _python_parameter_type(self, param: Node) -> str:
        t = param.child_by_field_name("type")
        if t is not None:
            return self._node_text(t).strip()
        for ch in param.children:
            if ch.type == "type":
                return self._node_text(ch).strip()
        return ""

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        rt = func_node.child_by_field_name("return_type")
        return self._node_text(rt).strip() if rt else ""

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        bases: list[str] = []
        generic_params: list[str] = []
        for child in class_node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type == "identifier" and arg.text:
                        bases.append(arg.text.decode("utf-8"))
        return bases, generic_params

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return self._python_docstring_from_body(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        return self._python_docstring_from_body(func_node)

    @staticmethod
    def _python_docstring_from_body(node: Node) -> str:
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
        if first_stmt.type == "expression_statement":
            expr = first_stmt.children[0] if first_stmt.children else None
            if expr and expr.type in ("string", "concatenated_string"):
                raw = expr.text.decode("utf-8") if expr.text else ""
                return raw.strip("'\"").strip()
        return ""

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
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

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
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

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        func_child = call_node.child_by_field_name("function")
        if func_child is not None and func_child.type == "attribute":
            obj = func_child.child_by_field_name("object")
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
        fp = file_path.replace("\\", "/")
        mod = self._python_module_from_file(fp)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    @staticmethod
    def _python_module_from_file(file_path: str) -> str:
        p = Path(file_path.replace("\\", "/"))
        stem = p.stem
        dir_parts = [x for x in p.parent.parts if x not in ("/", "\\", ".", "")]
        cleaned: list[str] = []
        for x in dir_parts:
            if len(x) == 2 and x[1] == ":":
                continue
            cleaned.append(x)
        return ".".join(cleaned + [stem])

    def build_module_name(self, file_path: str) -> str:
        fp = file_path.replace("\\", "/")
        stem = Path(fp).stem
        dir_parts = [x for x in Path(fp).parent.parts if x not in (".",)]
        if stem == "__init__":
            return ".".join(dir_parts) if dir_parts else "__init__"
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
        sf = source_file.replace("\\", "/")
        if ip.startswith("."):
            return self._resolve_python_relative(ip, sf, file_index, reverse_index)
        parts = ip.split(".")
        base = "/".join(parts)

        cand = f"{base}.py"
        if cand in file_index:
            return cand

        mod_key = ".".join(parts)
        hit = BaseLanguagePlugin._pick_from_reverse(reverse_index, mod_key)
        if hit:
            return hit

        init_path = f"{base}/__init__.py"
        if init_path in file_index:
            return init_path

        return BaseLanguagePlugin._pick_from_reverse(reverse_index, ip)

    def _resolve_python_relative(
        self,
        import_path: str,
        source_file: str,
        file_index: dict[str, str],
        reverse_index: dict[str, list[str]],
    ) -> str | None:
        src = Path(source_file)
        dir_parts = list(src.parent.parts)

        m = re.match(r"^(\.+)(.*)$", import_path)
        if not m:
            return None
        dots, rest = m.group(1), m.group(2).strip(".")
        level = len(dots) - 1
        if level > len(dir_parts):
            return None
        base_dir_parts = dir_parts[: len(dir_parts) - level] if level else dir_parts

        if rest:
            sub_parts = [p for p in rest.split(".") if p]
            path_parts = base_dir_parts + sub_parts
        else:
            path_parts = base_dir_parts

        if not path_parts:
            return None

        base = "/".join(path_parts)
        cand = f"{base}.py"
        if cand in file_index:
            return cand

        mod_key = ".".join(path_parts)
        hit = BaseLanguagePlugin._pick_from_reverse(reverse_index, mod_key)
        if hit:
            return hit

        init_path = f"{base}/__init__.py"
        if init_path in file_index:
            return init_path

        return BaseLanguagePlugin._pick_from_reverse(reverse_index, mod_key)
