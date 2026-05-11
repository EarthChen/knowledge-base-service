"""AST → PropertyGraph builder.

Converts parsed AST structures (functions, classes, imports, calls)
into graph nodes and edges for storage in FalkorDB.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING

from indexer.annotation_semantics import classify_annotations, lookup_annotation
from indexer.child_chunker import chunk_code_entity
from indexer.graph_fqn import (
    _JAVA_SRC_MARKERS,
    _is_stdlib_import,
    _java_simple_type_name_from_string,
    _merge_java_constructor_injection_fields,
    compute_fqn,
    compute_java_fqn,
)
from indexer.import_resolver import ImportResolver
from indexer.tree_sitter_parser import ParseResult, TreeSitterParser
from core.log import get_logger
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel, utc_indexed_at_iso

if TYPE_CHECKING:
    from indexer.languages import PluginRegistry

log = get_logger(__name__)

# Sentinel ``file_path`` yielded last by :meth:`CodeGraphBuilder.iter_directory_with_cross_file`;
# ``nodes`` is empty and ``edges`` holds cross-file CALLS / INHERITS / IMPLEMENTS.
CROSS_FILE_RESOLUTION_PATH = "__cross_file_resolution__"


@dataclass
class _CrossFileData:
    file_path: str
    language: str
    imports: list  # list[ParsedImport]
    unresolved_calls: list  # (caller_uid, callee_name, receiver_expr, line)
    unresolved_inherits: list  # (child_uid, base_name)
    unresolved_implements: list = dc_field(default_factory=list)  # (child_uid, iface_name)
    fields: list = dc_field(default_factory=list)  # list[ParsedField] — map field names → types


class CodeGraphBuilder:
    """Builds graph nodes and edges from parsed code AST."""

    CROSS_FILE_RESOLUTION_PATH = CROSS_FILE_RESOLUTION_PATH

    def __init__(
        self,
        parser: TreeSitterParser,
        file_extensions: dict[str, list[str]],
        *,
        registry: PluginRegistry | None = None,
        child_chunk_enabled: bool = False,
        child_chunk_window_chars: int = 800,
        child_chunk_stride_chars: int = 600,
        child_chunk_min_parent_chars: int = 400,
    ) -> None:
        self._parser = parser
        if registry is not None:
            self._registry = registry
        else:
            from indexer.languages import create_default_registry

            self._registry = create_default_registry()
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
            from core.config import get_settings
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
        """UID of the Module node for a file, matching :class:`GraphNode` with ``file``."""
        stem = Path(store_path).stem
        return GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": stem, "file": store_path},
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
        return self.build_from_parse_result(
            parse_result,
            store_path or file_path,
            language,
            import_resolver=import_resolver,
        )

    def build_from_parse_result(
        self,
        parse_result: ParseResult,
        store_path: str,
        language: str,
        *,
        import_resolver: ImportResolver | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Build nodes and edges from an already-parsed :class:`ParseResult` (no second parse)."""
        return self._build_graph(
            parse_result,
            store_path,
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
            from core.config import get_settings
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

    def iter_directory_with_cross_file(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
    ) -> Iterator[tuple[str, list[GraphNode], list[GraphEdge]]]:
        """Like :meth:`iter_directory`, then yield one extra tuple for cross-file edges.

        Yields ``(rel_path, nodes, edges)`` per source file, then
        ``(CROSS_FILE_RESOLUTION_PATH, [], cross_file_edges)`` if any cross-file
        edges were resolved (otherwise the final yield is omitted).
        """
        if exclude_patterns is not None:
            exclude = set(exclude_patterns)
        else:
            from core.config import get_settings
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

        all_nodes: list[GraphNode] = []
        per_file_data: list[_CrossFileData] = []

        for rel, fpath in tasks:
            try:
                language = self.detect_language(str(fpath))
                if not language:
                    continue
                parse_result = self._parser.parse_file(str(fpath), language, None)
                nodes, edges = self.build_from_parse_result(
                    parse_result,
                    rel,
                    language,
                    import_resolver=resolver,
                )
                all_nodes.extend(nodes)
                per_file_data.append(
                    self._cross_file_data_from_parse(rel, language, nodes, parse_result),
                )
                yield rel, nodes, edges
            except Exception as exc:
                log.warning("file_parse_error", file=str(fpath), error=str(exc))

        symbol_tables = self._build_global_symbol_table(all_nodes)
        cross_edges = self._resolve_cross_file_edges(per_file_data, symbol_tables, all_nodes)
        if cross_edges:
            yield CROSS_FILE_RESOLUTION_PATH, [], cross_edges

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

    def _build_global_symbol_table(
        self, all_nodes: list[GraphNode],
    ) -> dict[str, dict[str, str]]:
        """Build per-language {fqn_or_name: node_uid} for all Class and Function nodes.

        FQN entries take precedence. If a node has both fqn and name,
        both are stored but fqn wins (setdefault avoids overwriting).

        Scope: one repository only. Cross-repo resolution (shared libraries used by
        multiple services) could later persist a per-repo SymbolIndex in FalkorDB and
        query it during enrichment (alongside RPC/DI/Kafka edges in cross_repo_enricher).
        """
        tables: dict[str, dict[str, str]] = {}
        for node in all_nodes:
            lang = node.properties.get("language", "")
            if not lang:
                continue
            if node.label not in (NodeLabel.CLASS, NodeLabel.FUNCTION):
                continue
            fqn = node.properties.get("fqn", "")
            if fqn:
                tables.setdefault(lang, {})[fqn] = node.uid
            name = node.properties.get("name", "")
            if name:
                # Use setdefault so FQN entry isn't overwritten by simple name
                tables.setdefault(lang, {}).setdefault(name, node.uid)
            if fqn and node.label == NodeLabel.FUNCTION and "#" in fqn:
                cls_fqn, meth = fqn.split("#", 1)
                simple_cls = cls_fqn.rsplit(".", 1)[-1]
                if simple_cls and meth:
                    tables.setdefault(lang, {}).setdefault(f"{simple_cls}.{meth}", node.uid)
        return tables

    def _build_import_map(
        self,
        imports: list,
        file_path: str,
        symbol_table: dict[str, str],
    ) -> dict[str, str]:
        """Map imported symbol names to their uid for this file's scope."""
        del file_path  # reserved for future file-relative resolution
        result: dict[str, str] = {}
        for imp in imports:
            symbols = getattr(imp, "symbols", []) or getattr(imp, "names", [])
            for sym in symbols:
                candidate_fqn = f"{imp.module}.{sym}" if imp.module else sym
                if candidate_fqn in symbol_table:
                    result[sym] = symbol_table[candidate_fqn]
                elif sym in symbol_table:
                    result[sym] = symbol_table[sym]
        return result

    def _enrich_import_map_from_fields(
        self,
        import_map: dict[str, str],
        fields: list,
        symbol_table: dict[str, str],
    ) -> None:
        """Map field/instance names (e.g. userService) to class UIDs via declared types."""
        for fld in fields:
            ftype = (getattr(fld, "field_type", "") or "").strip()
            if not ftype:
                continue
            simple = _java_simple_type_name_from_string(ftype)
            if not simple:
                continue
            type_uid = import_map.get(simple) or symbol_table.get(simple)
            if not type_uid:
                continue
            fname = (getattr(fld, "name", "") or "").strip()
            if fname:
                import_map.setdefault(fname, type_uid)

    def _resolve_call_target(
        self,
        callee_name: str,
        receiver_expr: str,
        import_map: dict[str, str],
        symbol_table: dict[str, str],
        uid_to_class_fqn: dict[str, str],
    ) -> str | None:
        """Resolve a callee to a target uid using receiver type + import map."""
        if receiver_expr:
            receiver_name = receiver_expr.rsplit(".", 1)[-1] if "." in receiver_expr else receiver_expr
            if receiver_name in ("self", "this"):
                if "." in receiver_expr:
                    parts = receiver_expr.split(".")
                    if len(parts) >= 2:
                        receiver_name = parts[1]
            receiver_class_uid = import_map.get(receiver_name) or symbol_table.get(receiver_name)
            if receiver_class_uid:
                cls_fqn = uid_to_class_fqn.get(receiver_class_uid, "")
                if cls_fqn and callee_name:
                    for candidate in (
                        f"{cls_fqn}#{callee_name}",
                        f"{cls_fqn}.{callee_name}",
                    ):
                        uid = symbol_table.get(candidate)
                        if uid:
                            return uid
                    simple = cls_fqn.rsplit(".", 1)[-1]
                    uid = symbol_table.get(f"{simple}.{callee_name}")
                    if uid:
                        return uid
                method_fqn = f"{receiver_name}.{callee_name}"
                return symbol_table.get(method_fqn)
        return import_map.get(callee_name) or symbol_table.get(callee_name)

    def _resolve_cross_file_edges(
        self,
        per_file_data: list[_CrossFileData],
        symbol_tables: dict[str, dict[str, str]],
        all_nodes: list[GraphNode],
    ) -> list[GraphEdge]:
        uid_to_class_fqn: dict[str, str] = {}
        for n in all_nodes:
            if n.label != NodeLabel.CLASS:
                continue
            fqn = n.properties.get("fqn", "")
            if isinstance(fqn, str) and fqn:
                uid_to_class_fqn[n.uid] = fqn

        edges: list[GraphEdge] = []
        for data in per_file_data:
            lang = data.language
            table = symbol_tables.get(lang, {})
            import_map = self._build_import_map(data.imports, data.file_path, table)
            self._enrich_import_map_from_fields(import_map, data.fields, table)

            for caller_uid, callee_name, receiver_expr, line in data.unresolved_calls:
                target_uid = self._resolve_call_target(
                    callee_name,
                    receiver_expr,
                    import_map,
                    table,
                    uid_to_class_fqn,
                )
                if target_uid and caller_uid != target_uid:
                    edges.append(GraphEdge(
                        edge_type=EdgeType.CALLS,
                        source_uid=caller_uid,
                        target_uid=target_uid,
                        properties={"line": line, "cross_file": True},
                    ))

            for child_uid, base_name in data.unresolved_inherits:
                target_uid = import_map.get(base_name) or table.get(base_name)
                if target_uid and child_uid != target_uid:
                    edges.append(GraphEdge(
                        edge_type=EdgeType.INHERITS,
                        source_uid=child_uid,
                        target_uid=target_uid,
                    ))

            for child_uid, iface_name in data.unresolved_implements:
                target_uid = import_map.get(iface_name) or table.get(iface_name)
                if target_uid and child_uid != target_uid:
                    edges.append(GraphEdge(
                        edge_type=EdgeType.IMPLEMENTS,
                        source_uid=child_uid,
                        target_uid=target_uid,
                    ))

        return edges

    def _cross_file_data_from_parse(
        self,
        file_path: str,
        lang: str,
        nodes: list[GraphNode],
        result: ParseResult,
    ) -> _CrossFileData:
        func_uid_by_name: dict[str, list[str]] = {}
        for n in nodes:
            if n.label == NodeLabel.FUNCTION:
                name = n.properties.get("name", "")
                func_uid_by_name.setdefault(str(name), []).append(n.uid)

        unresolved_calls: list[tuple[str, str, str, int]] = []
        for call in result.calls:
            caller_uids = func_uid_by_name.get(call.caller_name, [])
            callee_uids = func_uid_by_name.get(call.callee_name, [])
            if caller_uids and not callee_uids:
                caller_uid = self._resolve_closest_uid(caller_uids, call.line, result)
                unresolved_calls.append((
                    caller_uid,
                    call.callee_name,
                    getattr(call, "receiver_expr", ""),
                    call.line,
                ))

        unresolved_inherits: list[tuple[str, str]] = []
        for n in nodes:
            if n.label != NodeLabel.CLASS:
                continue
            bases = n.properties.get("base_classes", [])
            if isinstance(bases, str):
                bases = [bases]
            for base in bases:
                base_simple = base.rsplit(".", 1)[-1] if "." in str(base) else str(base)
                same_file_match = any(
                    nn.label == NodeLabel.CLASS
                    and nn.properties.get("name") == base_simple
                    and nn.properties.get("file") == n.properties.get("file")
                    for nn in nodes
                )
                if not same_file_match:
                    unresolved_inherits.append((n.uid, base_simple))

        unresolved_implements: list[tuple[str, str]] = []
        for n in nodes:
            if n.label != NodeLabel.CLASS:
                continue
            interfaces = n.properties.get("interfaces", [])
            if isinstance(interfaces, str):
                interfaces = [interfaces]
            for iface in interfaces:
                iface_simple = iface.rsplit(".", 1)[-1] if "." in str(iface) else str(iface)
                same_file_match = any(
                    nn.label == NodeLabel.CLASS
                    and nn.properties.get("name") == iface_simple
                    and nn.properties.get("file") == n.properties.get("file")
                    for nn in nodes
                )
                if not same_file_match:
                    unresolved_implements.append((n.uid, iface_simple))

        return _CrossFileData(
            file_path=file_path,
            language=lang,
            imports=result.imports,
            unresolved_calls=unresolved_calls,
            unresolved_inherits=unresolved_inherits,
            unresolved_implements=unresolved_implements,
            fields=result.fields,
        )

    def build_from_files(
        self, files: dict[str, str],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Two-phase build: per-file parsing + cross-file resolution.

        Phase 1: Parse each file once, build graph, collect unresolved references.

        Phase 2: Use the global symbol table to resolve cross-file
        CALLS, INHERITS, and IMPLEMENTS edges.
        """
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []
        per_file_data: list[_CrossFileData] = []

        for file_path, content in files.items():
            lang = self.detect_language(file_path)
            if not lang:
                continue

            parse_result = self._parser.parse_file(file_path, lang, content)
            nodes, edges = self.build_from_parse_result(
                parse_result, file_path, lang, import_resolver=None,
            )
            all_nodes.extend(nodes)
            all_edges.extend(edges)
            per_file_data.append(
                self._cross_file_data_from_parse(file_path, lang, nodes, parse_result),
            )

        symbol_tables = self._build_global_symbol_table(all_nodes)
        cross_edges = self._resolve_cross_file_edges(per_file_data, symbol_tables, all_nodes)
        all_edges.extend(cross_edges)

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
        filtered_imports = [
            imp for imp in result.imports
            if imp.module and not _is_stdlib_import(imp.module.strip())
        ]
        import_names = [imp.module for imp in filtered_imports]

        module_name = Path(file_path).stem
        module_props: dict[str, object] = {
            "name": module_name,
            "file": file_path,
            "path": file_path,
            "language": language,
            "imports": import_names,
            "indexed_at": indexed_at,
        }
        module_doc = result.module_docstring
        if module_doc:
            module_props["docstring"] = module_doc[:1000]
        module_node = GraphNode(
            label=NodeLabel.MODULE,
            properties=module_props,
        )
        nodes.append(module_node)

        import_target_by_name: dict[str, GraphNode] = {}
        import_edge_keys: set[tuple[str, str]] = set()
        resolved_imports = 0
        unresolved_imports = 0
        resolved_target_uids: set[str] = set()

        for imp in filtered_imports:
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
            cls_fqn = compute_fqn(file_path, cls.name, "Class", registry=self._registry)
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
            func_fqn = compute_fqn(
                file_path,
                func.name,
                "Function",
                func.parent_class or "",
                registry=self._registry,
            )
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
                field_fqn = compute_fqn(
                    file_path,
                    f"field:{fld.name}",
                    "Function",
                    fld.parent_class,
                    registry=self._registry,
                )
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
