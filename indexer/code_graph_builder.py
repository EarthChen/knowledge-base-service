"""AST → PropertyGraph builder.

Converts parsed AST structures (functions, classes, imports, calls)
into graph nodes and edges for storage in FalkorDB.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from indexer.annotation_semantics import classify_annotations, lookup_annotation
from indexer.child_chunker import chunk_code_entity
from indexer.import_resolver import ImportResolver
from indexer.tree_sitter_parser import ParsedField, ParseResult, TreeSitterParser
from log import get_logger
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel, utc_indexed_at_iso

log = get_logger(__name__)


_JAVA_SRC_MARKERS = ("src/main/java/", "src/test/java/")

_SPRING_BEAN_SEMANTIC_ROLES = frozenset({
    "service", "repository", "component", "http_controller",
})


def _java_class_is_spring_di_bean(decorators: list[str]) -> bool:
    roles = set(classify_annotations(decorators))
    return bool(roles & _SPRING_BEAN_SEMANTIC_ROLES)


def _java_simple_type_name_from_string(ftype: str) -> str:
    t = ftype.strip()
    if not t:
        return ""
    if "<" in t:
        t = t.split("<", 1)[0].strip()
    return t.split(".")[-1]


def _java_constructors_for_class(result: ParseResult, cls_name: str) -> list:
    out = []
    for f in result.functions:
        if f.language != "java" or f.parent_class != cls_name:
            continue
        if f.name == cls_name and not (f.return_type or "").strip():
            out.append(f)
    return out


def _merge_java_constructor_injection_fields(result: ParseResult, file_path: str, language: str) -> list[ParsedField]:
    """Append ctor-parameter deps when a Spring bean has a single constructor (Lombok-free DI)."""
    if language != "java":
        return list(result.fields)
    merged = list(result.fields)
    existing = {(f.parent_class, f.name) for f in merged}
    for cls in result.classes:
        if not _java_class_is_spring_di_bean(cls.decorators):
            continue
        ctors = _java_constructors_for_class(result, cls.name)
        if len(ctors) != 1:
            continue
        ctor = ctors[0]
        for p in ctor.parameters:
            pname = (p.get("name") or "").strip()
            ptype = (p.get("type") or "").strip()
            if not pname:
                continue
            key = (cls.name, pname)
            if key in existing:
                continue
            simple = _java_simple_type_name_from_string(ptype)
            if not TreeSitterParser._java_type_looks_like_spring_bean(simple):
                continue
            merged.append(ParsedField(
                name=pname,
                field_type=ptype,
                file=file_path,
                line=ctor.start_line,
                annotations=[],
                parent_class=cls.name,
                injection_type="constructor",
            ))
            existing.add(key)
    return merged


def compute_java_fqn(file_path: str, entity_name: str, is_method: bool = False, parent_class: str = "") -> str:
    """Derive a Java fully-qualified name from the file path.

    For standard Maven/Gradle layouts the package maps to the directory
    structure after ``src/main/java/`` or ``src/test/java/``.
    """
    for marker in _JAVA_SRC_MARKERS:
        idx = file_path.find(marker)
        if idx == -1:
            continue
        rel = file_path[idx + len(marker):]
        class_fqn = rel.replace("/", ".").removesuffix(".java")
        if is_method:
            if parent_class:
                return f"{class_fqn}#{entity_name}"
            pkg = class_fqn.rsplit(".", 1)[0] if "." in class_fqn else ""
            return f"{pkg}.{entity_name}" if pkg else entity_name
        return class_fqn
    return ""


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


def _go_package_from_file(file_path: str) -> str:
    """Heuristic: use parent directory as Go package name.

    Limitation: real Go packages come from the `package` declaration, not
    the directory.  For a more precise FQN, parse the `package` line from
    the source file during the AST pass.
    """
    name = Path(file_path.replace("\\", "/")).parent.name
    return name if name else "main"


_JS_TS_EXTS_LONGEST_FIRST = (
    ".tsx", ".jsx", ".mjs", ".cjs", ".d.ts", ".ts", ".js",
)


def _js_ts_suffix(lower_name: str) -> str | None:
    for ext in _JS_TS_EXTS_LONGEST_FIRST:
        if lower_name.endswith(ext):
            return ext
    return None


def _js_ts_module_prefix(file_path: str) -> str:
    fp = file_path.replace("\\", "/")
    lower = fp.lower()
    ext = _js_ts_suffix(lower)
    if ext:
        return fp[: -len(ext)].lstrip("./")
    return Path(fp).with_suffix("").as_posix().lstrip("./")


def compute_fqn(file_path: str, entity_name: str, label: str, parent_class: str = "") -> str:
    """Compute a stable fully-qualified–style name from file path and entity hierarchy."""
    if file_path.endswith(".java"):
        return compute_java_fqn(file_path, entity_name, is_method=(label == "Function"), parent_class=parent_class)

    fp = file_path.replace("\\", "/")
    lower = fp.lower()

    if lower.endswith(".py"):
        mod = _python_module_from_file(fp)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    if lower.endswith(".go"):
        pkg = _go_package_from_file(fp)
        if label == "Class":
            return f"{pkg}.{entity_name}"
        if parent_class:
            return f"{pkg}.{parent_class}.{entity_name}"
        return f"{pkg}.{entity_name}"

    if _js_ts_suffix(lower):
        mod = _js_ts_module_prefix(fp)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    return ""


class CodeGraphBuilder:
    """Builds graph nodes and edges from parsed code AST."""

    def __init__(
        self,
        parser: TreeSitterParser,
        file_extensions: dict[str, list[str]],
        *,
        child_chunk_enabled: bool = False,
        child_chunk_window_chars: int = 800,
        child_chunk_stride_chars: int = 600,
        child_chunk_min_parent_chars: int = 400,
    ) -> None:
        self._parser = parser
        self._ext_to_lang: dict[str, str] = {}
        for lang, exts in file_extensions.items():
            for ext in exts:
                self._ext_to_lang[ext] = lang
        self._child_chunk_enabled = child_chunk_enabled
        self._child_chunk_window = child_chunk_window_chars
        self._child_chunk_stride = child_chunk_stride_chars
        self._child_chunk_min = child_chunk_min_parent_chars

    def detect_language(self, file_path: str) -> str | None:
        suffix = Path(file_path).suffix
        return self._ext_to_lang.get(suffix)

    def collect_relative_source_paths(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
    ) -> list[str]:
        """List supported code files (relative to *directory*) for import resolution."""
        if exclude_patterns is not None:
            exclude = set(exclude_patterns)
        else:
            from config import get_settings
            exclude = set(get_settings().exclude_dirs)

        base = Path(directory)
        out: list[str] = []
        for ext in self._ext_to_lang:
            for fpath in base.rglob(f"*{ext}"):
                if any(part in exclude for part in fpath.parts):
                    continue
                out.append(str(fpath.relative_to(base)))
        return out

    @staticmethod
    def _module_uid_for_store_path(store_path: str) -> str:
        """UID of the Module node for a file, matching :class:`GraphNode` without ``file``."""
        stem = Path(store_path).stem
        return GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": stem},
        ).uid

    def build_from_file(
        self,
        file_path: str,
        content: str | None = None,
        *,
        store_path: str | None = None,
        import_resolver: ImportResolver | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a single file and return graph nodes + edges.

        ``store_path`` is what gets persisted as the ``file`` property.
        When *None* it equals *file_path* (backward compatible).
        """
        language = self.detect_language(file_path)
        if not language:
            return [], []

        parse_result = self._parser.parse_file(file_path, language, content)
        return self._build_graph(
            parse_result,
            store_path or file_path,
            language,
            import_resolver=import_resolver,
        )

    def iter_directory(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
    ) -> Iterator[tuple[str, list[GraphNode], list[GraphEdge]]]:
        """Yield ``(file_path, nodes, edges)`` per file — constant memory."""
        if exclude_patterns is not None:
            exclude = set(exclude_patterns)
        else:
            from config import get_settings
            exclude = set(get_settings().exclude_dirs)

        base = Path(directory)
        tasks: list[tuple[str, Path]] = []
        for ext in self._ext_to_lang:
            for fpath in base.rglob(f"*{ext}"):
                if any(part in exclude for part in fpath.parts):
                    continue
                rel = str(fpath.relative_to(base))
                tasks.append((rel, fpath))

        resolver: ImportResolver | None = None
        if tasks:
            resolver = ImportResolver(ImportResolver.build_file_index([t[0] for t in tasks]))

        for rel, fpath in tasks:
            try:
                nodes, edges = self.build_from_file(
                    str(fpath),
                    store_path=rel,
                    import_resolver=resolver,
                )
                yield rel, nodes, edges
            except Exception as exc:
                log.warning("file_parse_error", file=str(fpath), error=str(exc))

    def build_from_directory(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse all supported files in a directory (loads everything into memory).

        Prefer :meth:`iter_directory` for large repositories.
        """
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []
        for _fpath, nodes, edges in self.iter_directory(directory, exclude_patterns):
            all_nodes.extend(nodes)
            all_edges.extend(edges)

        log.info(
            "directory_parsed",
            directory=directory,
            nodes=len(all_nodes),
            edges=len(all_edges),
        )
        return all_nodes, all_edges

    @staticmethod
    def _resolve_closest_uid(uids: list[str], call_line: int, result: ParseResult) -> str:
        """Pick the overload whose line range contains *call_line*."""
        if len(uids) == 1:
            return uids[0]
        for func in result.functions:
            for uid in uids:
                if uid.endswith(f":{func.name}:{func.start_line}") and func.start_line <= call_line <= func.end_line:
                    return uid
        return uids[0]

    def _build_graph(
        self,
        result: ParseResult,
        file_path: str,
        language: str,
        *,
        import_resolver: ImportResolver | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        indexed_at = utc_indexed_at_iso()
        import_names = [imp.module for imp in result.imports]

        module_name = Path(file_path).stem
        module_node = GraphNode(
            label=NodeLabel.MODULE,
            properties={
                "name": module_name,
                "path": file_path,
                "language": language,
                "imports": import_names,
                "indexed_at": indexed_at,
            },
        )
        nodes.append(module_node)

        import_target_by_name: dict[str, GraphNode] = {}
        import_edge_keys: set[tuple[str, str]] = set()
        resolved_imports = 0
        unresolved_imports = 0
        resolved_target_uids: set[str] = set()

        for imp in result.imports:
            raw_mod = imp.module.strip() if imp.module else ""
            mod_name = raw_mod.split(".")[-1] if raw_mod else ""
            if not raw_mod:
                continue
            # ``from ..x`` yields empty last segment; keep a stable short name for stubs
            if not mod_name:
                mod_name = raw_mod.strip(".")

            resolved_path: str | None = None
            if import_resolver and raw_mod:
                resolved_path = import_resolver.resolve(raw_mod, file_path, language)

            if resolved_path:
                resolved_imports += 1
                tgt_uid = self._module_uid_for_store_path(resolved_path)
                resolved_target_uids.add(tgt_uid)
            else:
                unresolved_imports += 1
                stub_uid = GraphNode(
                    label=NodeLabel.MODULE,
                    properties={"name": mod_name},
                ).uid
                if stub_uid in resolved_target_uids:
                    tgt_uid = stub_uid
                elif mod_name not in import_target_by_name:
                    ext_path = f"<import:{mod_name}>"
                    import_target_by_name[mod_name] = GraphNode(
                        label=NodeLabel.MODULE,
                        properties={
                            "name": mod_name,
                            "path": ext_path,
                            "language": language,
                            "indexed_at": indexed_at,
                        },
                    )
                    nodes.append(import_target_by_name[mod_name])
                    tgt_uid = import_target_by_name[mod_name].uid
                else:
                    tgt_uid = import_target_by_name[mod_name].uid

            pair = (module_node.uid, tgt_uid)
            if pair not in import_edge_keys:
                import_edge_keys.add(pair)
                edges.append(GraphEdge(
                    edge_type=EdgeType.IMPORTS,
                    source_uid=module_node.uid,
                    target_uid=tgt_uid,
                ))

        if import_resolver and result.imports:
            total = resolved_imports + unresolved_imports
            rate = (resolved_imports / total) if total else 0.0
            log.debug(
                "import_resolve_stats",
                file=file_path,
                resolved=resolved_imports,
                unresolved=unresolved_imports,
                total_imports=len(result.imports),
                resolution_rate=round(rate, 4),
            )

        func_uid_by_name: dict[str, list[str]] = {}
        class_uid_by_name: dict[str, str] = {}

        for cls in result.classes:
            cls_props: dict[str, object] = {
                "name": cls.name,
                "file": file_path,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "docstring": cls.docstring[:1000] if cls.docstring else "",
                "language": language,
                "base_classes": cls.base_classes,
                "is_interface": cls.is_interface,
            }
            if cls.generic_type_params:
                cls_props["generic_type_params"] = cls.generic_type_params
            if cls.code_snippet:
                cls_props["code_snippet"] = cls.code_snippet
            if cls.interfaces:
                cls_props["interfaces"] = cls.interfaces
            cls_fqn = compute_fqn(file_path, cls.name, "Class")
            if cls_fqn:
                cls_props["fqn"] = cls_fqn
            if cls.decorators:
                cls_props["annotations"] = cls.decorators
            semantic_roles = classify_annotations(cls.decorators)
            if semantic_roles:
                cls_props["semantic_roles"] = semantic_roles
            cls_props["indexed_at"] = indexed_at
            class_node = GraphNode(label=NodeLabel.CLASS, properties=cls_props)
            nodes.append(class_node)
            class_uid_by_name[cls.name] = class_node.uid

            edges.append(GraphEdge(
                edge_type=EdgeType.CONTAINS,
                source_uid=module_node.uid,
                target_uid=class_node.uid,
            ))

            if "rpc_provider" in semantic_roles:
                edges.append(GraphEdge(
                    edge_type=EdgeType.PROVIDES_RPC,
                    source_uid=class_node.uid,
                    target_uid=module_node.uid,
                ))

        for cls in result.classes:
            child_uid = class_uid_by_name.get(cls.name)
            if not child_uid:
                continue
            for base in cls.base_classes:
                parent_uid = class_uid_by_name.get(base)
                if parent_uid and parent_uid != child_uid:
                    edges.append(GraphEdge(
                        edge_type=EdgeType.INHERITS,
                        source_uid=child_uid,
                        target_uid=parent_uid,
                    ))

        for cls in result.classes:
            child_uid = class_uid_by_name.get(cls.name)
            if not child_uid:
                continue
            for iface in cls.interfaces:
                iface_uid = class_uid_by_name.get(iface)
                if iface_uid and iface_uid != child_uid:
                    edges.append(GraphEdge(
                        edge_type=EdgeType.IMPLEMENTS,
                        source_uid=child_uid,
                        target_uid=iface_uid,
                    ))

        for func in result.functions:
            func_props: dict[str, object] = {
                "name": func.name,
                "file": file_path,
                "start_line": func.start_line,
                "end_line": func.end_line,
                "signature": func.signature,
                "docstring": func.docstring[:1000] if func.docstring else "",
                "code_snippet": func.code_snippet,
                "language": language,
            }
            func_fqn = compute_fqn(file_path, func.name, "Function", parent_class=func.parent_class or "")
            if func_fqn:
                func_props["fqn"] = func_fqn
            if func.decorators:
                func_props["annotations"] = func.decorators
            semantic_roles = classify_annotations(func.decorators)
            if semantic_roles:
                func_props["semantic_roles"] = semantic_roles
            if func.parameters:
                func_props["parameters"] = [
                    f"{p['name']}:{p['type']}" if p.get("type") else p["name"]
                    for p in func.parameters
                ]
            if func.return_type:
                func_props["return_type"] = func.return_type
            func_props["indexed_at"] = indexed_at
            func_node = GraphNode(label=NodeLabel.FUNCTION, properties=func_props)
            nodes.append(func_node)
            func_uid_by_name.setdefault(func.name, []).append(func_node.uid)

            if func.parent_class:
                parent_uid = f"{NodeLabel.CLASS}:{file_path}:{func.parent_class}:{0}"
                for cls in result.classes:
                    if cls.name == func.parent_class:
                        parent_uid = f"{NodeLabel.CLASS}:{file_path}:{cls.name}:{cls.start_line}"
                        break
                edges.append(GraphEdge(
                    edge_type=EdgeType.CONTAINS,
                    source_uid=parent_uid,
                    target_uid=func_node.uid,
                ))
            else:
                edges.append(GraphEdge(
                    edge_type=EdgeType.CONTAINS,
                    source_uid=module_node.uid,
                    target_uid=func_node.uid,
                ))

            if "rpc_consumer" in semantic_roles:
                edges.append(GraphEdge(
                    edge_type=EdgeType.CONSUMES_RPC,
                    source_uid=func_node.uid,
                    target_uid=module_node.uid,
                ))

        di_fields = _merge_java_constructor_injection_fields(result, file_path, language)

        for fld in di_fields:
            parent_uid = class_uid_by_name.get(fld.parent_class, "")
            if not parent_uid:
                continue

            field_annotations = fld.annotations
            field_semantic_roles = classify_annotations(field_annotations)

            has_di = any(
                lookup_annotation(a) is not None and lookup_annotation(a).role.value == "di_inject"
                for a in field_annotations
            )
            has_rpc_consumer = any(
                lookup_annotation(a) is not None and lookup_annotation(a).role.value == "rpc_consumer"
                for a in field_annotations
            )
            has_ctor_di = fld.injection_type == "constructor"

            if has_di or has_rpc_consumer or has_ctor_di:
                field_props: dict[str, object] = {
                    "name": f"field:{fld.name}",
                    "file": file_path,
                    "start_line": fld.line,
                    "end_line": fld.line,
                    "signature": f"{fld.field_type} {fld.name}",
                    "docstring": "",
                    "code_snippet": "",
                    "language": language,
                    "is_field": True,
                    "field_type": fld.field_type,
                }
                if has_di:
                    field_props["injection_type"] = "field"
                elif has_ctor_di:
                    field_props["injection_type"] = "constructor"
                if field_annotations:
                    field_props["annotations"] = field_annotations
                if has_ctor_di and "di_inject" not in field_semantic_roles:
                    field_semantic_roles = [*field_semantic_roles, "di_inject"]
                if field_semantic_roles:
                    field_props["semantic_roles"] = field_semantic_roles
                field_fqn = compute_fqn(file_path, f"field:{fld.name}", "Function", parent_class=fld.parent_class)
                if field_fqn:
                    field_props["fqn"] = field_fqn

                field_props["indexed_at"] = indexed_at
                field_node = GraphNode(label=NodeLabel.FUNCTION, properties=field_props)
                nodes.append(field_node)
                func_uid_by_name.setdefault(f"field:{fld.name}", []).append(field_node.uid)

                edges.append(GraphEdge(
                    edge_type=EdgeType.CONTAINS,
                    source_uid=parent_uid,
                    target_uid=field_node.uid,
                ))

                if has_rpc_consumer:
                    edges.append(GraphEdge(
                        edge_type=EdgeType.CONSUMES_RPC,
                        source_uid=field_node.uid,
                        target_uid=module_node.uid,
                    ))

        for call in result.calls:
            caller_uids = func_uid_by_name.get(call.caller_name, [])
            callee_uids = func_uid_by_name.get(call.callee_name, [])
            if not caller_uids or not callee_uids:
                continue
            caller_uid = self._resolve_closest_uid(caller_uids, call.line, result)
            callee_uid = callee_uids[0]
            if caller_uid != callee_uid:
                edges.append(GraphEdge(
                    edge_type=EdgeType.CALLS,
                    source_uid=caller_uid,
                    target_uid=callee_uid,
                    properties={"line": call.line},
                ))

        if self._child_chunk_enabled:
            self._generate_child_chunks(nodes, edges, file_path, indexed_at)

        return nodes, edges

    def _generate_child_chunks(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        file_path: str,
        indexed_at: str,
    ) -> None:
        """Generate Chunk nodes and PART_OF edges for large Function/Class entities."""
        parent_nodes = [
            n for n in list(nodes)
            if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS)
        ]
        for parent in parent_nodes:
            props = parent.properties
            code = props.get("code_snippet", "")
            if not code or not isinstance(code, str):
                continue
            signature = str(props.get("signature", ""))
            name = str(props.get("name", ""))
            start_line = int(props.get("start_line", 0))

            children = chunk_code_entity(
                code_snippet=code,
                signature=signature,
                entity_name=name,
                start_line=start_line,
                window_chars=self._child_chunk_window,
                stride_chars=self._child_chunk_stride,
                min_parent_chars=self._child_chunk_min,
            )
            for child in children:
                parent_start = int(props.get("start_line", 0))
                chunk_uid = f"{NodeLabel.CHUNK}:{file_path}:{name}:{parent_start}:c{child.chunk_index}"
                chunk_node = GraphNode(
                    label=NodeLabel.CHUNK,
                    uid=chunk_uid,
                    properties={
                        "name": f"{name}:chunk_{child.chunk_index}",
                        "text": child.text,
                        "parent_uid": parent.uid,
                        "parent_label": str(parent.label),
                        "parent_name": name,
                        "chunk_index": child.chunk_index,
                        "file": file_path,
                        "start_line": child.start_line,
                        "end_line": child.end_line,
                        "indexed_at": indexed_at,
                    },
                )
                nodes.append(chunk_node)
                edges.append(GraphEdge(
                    edge_type=EdgeType.PART_OF,
                    source_uid=chunk_uid,
                    target_uid=parent.uid,
                ))
