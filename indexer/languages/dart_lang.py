"""Dart language plugin — extraction aligned with TreeSitterParser Dart grammar."""

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

_DART_QUERIES: dict[str, str] = {
    "function": "(function_signature name: (identifier) @func.name) @func.def",
    "class": """[
        (class_definition name: (identifier) @class.name) @class.def
        (mixin_declaration (identifier) @class.name) @class.def
        ]""",
    "import": "(import_or_export) @import.stmt",
    "call": "",
}

_DART_SUFFIX_TRY = (".dart", ".g.dart")

_DART_ROOT_DECL_HINT: frozenset[str] = frozenset({
    "class_definition",
    "mixin_declaration",
    "extension_declaration",
    "enum_declaration",
    "function_signature",
})


class DartPlugin(BaseLanguagePlugin):
    @property
    def name(self) -> str:
        return "dart"

    @property
    def file_extensions(self) -> list[str]:
        return [".dart"]

    def get_queries(self) -> dict[str, str]:
        return dict(_DART_QUERIES)

    def extract_imports(self, tree: Tree, source: bytes, file_path: str) -> list[ParsedImport]:
        imports: list[ParsedImport] = []
        lang = get_language(self.name)
        try:
            q_obj = Query(lang, _DART_QUERIES["import"])
        except Exception as exc:
            log.warning(
                "query_parse_error",
                language=self.name,
                query_type="import",
                error=str(exc),
            )
            return imports

        qc = QueryCursor(q_obj)
        for _, captures in qc.matches(tree.root_node):
            blocks = captures.get("import.stmt", [])
            if not blocks:
                continue
            n0 = blocks[0]
            line = n0.start_point[0] + 1
            uri_lit = DartPlugin._import_uri_literal(n0)
            imp = ParsedImport(
                module=uri_lit,
                names=[],
                file=file_path,
                line=line,
                language=self.name,
            )
            BaseLanguagePlugin._finalize_import_symbols(imp)
            imports.append(imp)
        return imports

    @staticmethod
    def _import_uri_literal(import_or_export_node: Node) -> str:
        def walk(x: Node) -> str:
            if x.type == "string_literal" and x.text:
                return BaseLanguagePlugin._strip_string_delimiters(x.text.decode("utf-8"))
            for kid in x.children:
                hit = walk(kid)
                if hit:
                    return hit
            return ""

        cfg = next((c for c in import_or_export_node.children if c.type == "configurable_uri"), None)
        if cfg:
            uri = cfg.child_by_field_name("uri")
            return walk(uri or cfg).strip()
        return walk(import_or_export_node).strip()

    def extract_parameters(self, func_node: Node, source: bytes) -> list[dict[str, str]]:
        plist = self._formal_parameter_list_for_signature(func_node)
        if plist is None:
            return []
        rows: list[dict[str, str]] = []
        for ch in plist.named_children:
            if ch.type != "formal_parameter":
                continue
            nid = self._param_binding_identifier(ch)
            if nid is None or not nid.text:
                continue
            pname = nid.text.decode("utf-8")
            raw_t = source[ch.start_byte : nid.start_byte].decode("utf-8")
            ptyp = raw_t.replace("\n", " ").strip(" ,").rstrip(",").strip()
            rows.append({"name": pname, "type": ptyp})
        return rows

    @staticmethod
    def _formal_parameter_list_for_signature(func_node: Node) -> Node | None:
        probe: Node | None = func_node
        while probe is not None:
            hit = next((c for c in probe.children if c.type == "formal_parameter_list"), None)
            if hit:
                return hit
            probe = probe.parent
        return None

    @staticmethod
    def _param_binding_identifier(formal_parameter: Node) -> Node | None:
        leaves: list[Node] = []

        def visit(n: Node) -> None:
            if n.type != "identifier":
                for kid in n.children:
                    visit(kid)
                return
            if n.named_children or n.children:
                for kid in n.children:
                    visit(kid)
                return
            leaves.append(n)

        visit(formal_parameter)
        return leaves[-1] if leaves else None

    def extract_return_type(self, func_node: Node, source: bytes) -> str:
        if func_node.type != "function_signature":
            return ""
        fname: Node | None = None
        for kid in func_node.children:
            if kid.type == "formal_parameter_list":
                break
            if kid.type == "identifier":
                fname = kid
        if fname is None:
            return ""
        return (
            source[func_node.start_byte : fname.start_byte].decode("utf-8").replace("\n", " ").strip()
        )

    def extract_base_classes(self, class_node: Node, source: bytes) -> tuple[list[str], list[str]]:
        gens: list[str] = []
        tp = next((c for c in class_node.named_children if c.type == "type_parameters"), None)
        if tp:
            for tpar in tp.named_children:
                if tpar.type != "type_parameter":
                    continue
                ti = next(
                    (x for x in tpar.named_children if x.type == "type_identifier" and x.text),
                    None,
                )
                if ti and ti.text:
                    gens.append(ti.text.decode("utf-8"))

        bases: list[str] = []
        superclass = next((c for c in class_node.named_children if c.type == "superclass"), None)
        if superclass:
            xt = next(
                (x for x in superclass.named_children if x.type == "type_identifier" and x.text),
                None,
            )
            if xt and xt.text:
                bases.append(xt.text.decode("utf-8").strip())

            mixes = next((x for x in superclass.named_children if x.type == "mixins"), None)
            if mixes:
                for sub in mixes.named_children:
                    if sub.type == "type_identifier" and sub.text:
                        bases.append(sub.text.decode("utf-8").strip())
        return bases, gens

    def extract_interfaces(self, class_node: Node, source: bytes) -> list[str]:
        iface = next((c for c in class_node.named_children if c.type == "interfaces"), None)
        if iface is None:
            return []
        ordered: list[str] = []
        seen: set[str] = set()
        stack: list[Node] = list(iface.children)
        while stack:
            nd = stack.pop()
            if nd.type == "type_identifier" and nd.text:
                s = nd.text.decode("utf-8").strip()
                if s and s not in seen:
                    ordered.append(s)
                    seen.add(s)
            stack.extend(reversed(nd.children))
        return ordered

    def extract_annotations(self, node: Node, source: bytes) -> list[str]:
        target = node
        if (
            node.type == "function_signature"
            and node.parent is not None
            and node.parent.type == "method_signature"
        ):
            target = node.parent
        ann: list[str] = []
        for child in target.children:
            if child.type != "annotation" or not child.text:
                continue
            txt = child.text.decode("utf-8").strip()
            if txt:
                ann.append(txt)
        return ann

    @staticmethod
    def _doc_body(raw: bytes) -> str:
        text = raw.decode("utf-8").strip("\n")
        lines_out: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("///"):
                lines_out.append(stripped[3:].strip())
            elif stripped.startswith("//"):
                lines_out.append(stripped[2:].strip())
            else:
                lines_out.append(line.rstrip())
        return "\n".join(lines_out).strip()

    def _docs_above_declaration(self, anchor: Node) -> str:
        cur = anchor.prev_named_sibling
        while cur and cur.type == "annotation":
            cur = cur.prev_named_sibling
        parts: list[str] = []
        while cur and cur.type == "documentation_comment":
            if cur.text:
                formatted = DartPlugin._doc_body(cur.text)
                if formatted:
                    parts.append(formatted)
            cur = cur.prev_named_sibling
        merged = "\n".join(parts)
        if merged and BaseLanguagePlugin._is_license_comment(merged):
            return ""
        return merged

    def extract_class_docstring(self, class_node: Node, source: bytes) -> str:
        return self._docs_above_declaration(class_node)

    def extract_function_docstring(self, func_node: Node, source: bytes) -> str:
        anchor = (
            func_node.parent
            if (
                func_node.type == "function_signature"
                and func_node.parent is not None
                and func_node.parent.type == "method_signature"
            )
            else func_node
        )
        return self._docs_above_declaration(anchor)

    def extract_module_docstring(self, root_node: Node, source: bytes) -> str:
        nt = getattr(root_node, "named_children", ()) or ()
        seq = nt if nt else root_node.children
        cutoff = len(seq)
        for idx, kid in enumerate(seq):
            if self._dart_is_root_declaration(kid):
                cutoff = idx
                break
        chunks: list[str] = []
        for kid in seq[:cutoff]:
            if kid.type != "documentation_comment" or not kid.text:
                continue
            body = DartPlugin._doc_body(kid.text)
            if body:
                chunks.append(body)
        merged = "\n".join(chunks)
        if merged and BaseLanguagePlugin._is_license_comment(merged):
            return ""
        return merged

    @staticmethod
    def _dart_is_root_declaration(node: Node) -> bool:
        if node.type in _DART_ROOT_DECL_HINT:
            return True
        if node.type == "labeled_statement":
            nc = getattr(node, "named_children", None) or node.children
            if nc and getattr(nc[0], "type", "") == "function_signature":
                return True
        return False

    def compute_fqn(
        self,
        file_path: str,
        entity_name: str,
        label: str,
        parent_class: str = "",
    ) -> str:
        mod = self.build_module_name(file_path)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    def build_module_name(self, file_path: str) -> str:
        fp = file_path.replace("\\", "/")
        stem = Path(fp).stem
        dirs = [p for p in Path(fp).parent.parts if p not in (".", "")]
        return ".".join([*dirs, stem])

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
        low = ip.lower()
        if low.startswith("dart:"):
            return None

        def nkey(pth: str) -> str:
            return pth.replace(chr(92), "/")

        def shortest_hits(paths: list[str]) -> str | None:
            if not paths:
                return None
            keyed = sorted((len(nkey(p)), p) for p in paths)
            return keyed[0][1]

        def endings_for(rel: str) -> list[str]:
            r = nkey(rel.strip())
            ends = ["/" + r, r]
            if not r.endswith(".dart"):
                ends.append("/" + r + ".dart")
                ends.append("/" + r + ".g.dart")
                ends.append("/lib/" + r)
                ends.append("/lib/" + r + ".dart")
            return ends

        def match_paths_by_suffix(rem: str) -> list[str]:
            hit: list[str] = []
            for fk in file_index:
                nk = nkey(fk)
                if nk == rem or nk.endswith("/" + rem) or nk.endswith(rem):
                    hit.append(fk)
                elif rem.startswith("lib/") and nk.endswith(rem[len("lib/") :]):
                    hit.append(fk)
            return hit

        if low.startswith("package:"):
            rem = ip[len("package:") :].strip()
            pool = []
            pool.extend(match_paths_by_suffix(rem))
            for suf in endings_for(rem):
                for fk in file_index:
                    if nkey(fk).endswith(suf):
                        pool.append(fk)
            best = shortest_hits(list(dict.fromkeys(pool)))
            if best:
                return best
            stem = Path(rem).stem
            dotted = ".".join(Path(rem).with_suffix("").parts)
            via = BaseLanguagePlugin._pick_from_reverse(reverse_index, dotted)
            if via:
                return via
            via2 = BaseLanguagePlugin._pick_from_reverse(reverse_index, stem)
            return via2

        src_dir = posixpath.dirname(nkey(source_file))
        joined = posixpath.normpath(posixpath.join(src_dir, ip.replace(chr(92), "/")))
        rel_join = joined.lstrip("/")

        cand: list[str] = []
        for fk in sorted(file_index):
            nk = nkey(fk)
            if nk == joined or nk == rel_join:
                cand.append(fk)
        if not cand:
            for ext in _DART_SUFFIX_TRY:
                jp = joined if joined.endswith(ext) else joined + ext
                rj = rel_join + ext
                for fk in sorted(file_index):
                    nk = nkey(fk)
                    if nk == jp or nk == rj:
                        cand.append(fk)
        sel = shortest_hits(cand)
        if sel:
            return sel
        dotted = ".".join(Path(rel_join.replace(".dart", "").replace(".g.dart", "")).parts)
        return BaseLanguagePlugin._pick_from_reverse(reverse_index, dotted)

    def extract_receiver_expr(self, call_node: Node, source: bytes) -> str:
        return ""

    def should_include_function(self, func_node: Node) -> bool:
        return True
