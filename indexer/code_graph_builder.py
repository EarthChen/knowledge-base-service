"""AST → PropertyGraph builder.

Converts parsed AST structures (functions, classes, imports, calls)
into graph nodes and edges for storage in FalkorDB.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from log import get_logger

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from indexer.tree_sitter_parser import ParseResult, TreeSitterParser

log = get_logger(__name__)


_JAVA_SRC_MARKERS = ("src/main/java/", "src/test/java/")


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


def compute_fqn(file_path: str, entity_name: str, label: str, parent_class: str = "") -> str:
    """Compute FQN for any supported language. Currently Java only."""
    if file_path.endswith(".java"):
        return compute_java_fqn(file_path, entity_name, is_method=(label == "Function"), parent_class=parent_class)
    return ""


class CodeGraphBuilder:
    """Builds graph nodes and edges from parsed code AST."""

    def __init__(self, parser: TreeSitterParser, file_extensions: dict[str, list[str]]) -> None:
        self._parser = parser
        self._ext_to_lang: dict[str, str] = {}
        for lang, exts in file_extensions.items():
            for ext in exts:
                self._ext_to_lang[ext] = lang

    def detect_language(self, file_path: str) -> str | None:
        suffix = Path(file_path).suffix
        return self._ext_to_lang.get(suffix)

    def build_from_file(
        self, file_path: str, content: str | None = None, *, store_path: str | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a single file and return graph nodes + edges.

        ``store_path`` is what gets persisted as the ``file`` property.
        When *None* it equals *file_path* (backward compatible).
        """
        language = self.detect_language(file_path)
        if not language:
            return [], []

        parse_result = self._parser.parse_file(file_path, language, content)
        return self._build_graph(parse_result, store_path or file_path, language)

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
        for ext in self._ext_to_lang:
            for fpath in base.rglob(f"*{ext}"):
                if any(part in exclude for part in fpath.parts):
                    continue
                try:
                    rel = str(fpath.relative_to(base))
                    nodes, edges = self.build_from_file(str(fpath), store_path=rel)
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

    def _build_graph(
        self, result: ParseResult, file_path: str, language: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        import_names = [imp.module for imp in result.imports]

        module_name = Path(file_path).stem
        module_node = GraphNode(
            label=NodeLabel.MODULE,
            properties={
                "name": module_name,
                "path": file_path,
                "language": language,
                "imports": import_names,
            },
        )
        nodes.append(module_node)

        func_uid_map: dict[str, str] = {}

        for cls in result.classes:
            cls_props: dict[str, object] = {
                "name": cls.name,
                "file": file_path,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "docstring": cls.docstring[:1000] if cls.docstring else "",
                "language": language,
                "base_classes": cls.base_classes,
            }
            cls_fqn = compute_fqn(file_path, cls.name, "Class")
            if cls_fqn:
                cls_props["fqn"] = cls_fqn
            class_node = GraphNode(label=NodeLabel.CLASS, properties=cls_props)
            nodes.append(class_node)

            edges.append(GraphEdge(
                edge_type=EdgeType.CONTAINS,
                source_uid=module_node.uid,
                target_uid=class_node.uid,
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
            func_node = GraphNode(label=NodeLabel.FUNCTION, properties=func_props)
            nodes.append(func_node)
            func_uid_map[func.name] = func_node.uid

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

        for call in result.calls:
            caller_uid = func_uid_map.get(call.caller_name)
            callee_uid = func_uid_map.get(call.callee_name)
            if caller_uid and callee_uid and caller_uid != callee_uid:
                edges.append(GraphEdge(
                    edge_type=EdgeType.CALLS,
                    source_uid=caller_uid,
                    target_uid=callee_uid,
                    properties={"line": call.line},
                ))

        return nodes, edges
