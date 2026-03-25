"""AST → PropertyGraph builder.

Converts parsed AST structures (functions, classes, imports, calls)
into graph nodes and edges for storage in FalkorDB.
"""

from __future__ import annotations

from pathlib import Path

from log import get_logger

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from indexer.tree_sitter_parser import ParseResult, TreeSitterParser

log = get_logger(__name__)


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

    def build_from_file(self, file_path: str, content: str | None = None) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a single file and return graph nodes + edges."""
        language = self.detect_language(file_path)
        if not language:
            return [], []

        parse_result = self._parser.parse_file(file_path, language, content)
        return self._build_graph(parse_result, file_path, language)

    def build_from_directory(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Recursively parse all supported files in a directory."""
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []
        exclude = set(exclude_patterns or [])
        default_excludes = {
            "__pycache__", "node_modules", ".git", ".venv", "venv",
            "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
            "vendor", "target",
        }
        exclude.update(default_excludes)

        base = Path(directory)
        for ext in self._ext_to_lang:
            for fpath in base.rglob(f"*{ext}"):
                if any(part in exclude for part in fpath.parts):
                    continue
                try:
                    nodes, edges = self.build_from_file(str(fpath))
                    all_nodes.extend(nodes)
                    all_edges.extend(edges)
                except Exception as exc:
                    log.warning("file_parse_error", file=str(fpath), error=str(exc))

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

        module_name = Path(file_path).stem
        module_node = GraphNode(
            label=NodeLabel.MODULE,
            properties={
                "name": module_name,
                "path": file_path,
                "language": language,
            },
        )
        nodes.append(module_node)

        func_uid_map: dict[str, str] = {}

        for cls in result.classes:
            class_node = GraphNode(
                label=NodeLabel.CLASS,
                properties={
                    "name": cls.name,
                    "file": file_path,
                    "start_line": cls.start_line,
                    "end_line": cls.end_line,
                    "docstring": cls.docstring[:1000] if cls.docstring else "",
                    "language": language,
                    "base_classes": cls.base_classes,
                },
            )
            nodes.append(class_node)

            edges.append(GraphEdge(
                edge_type=EdgeType.CONTAINS,
                source_uid=module_node.uid,
                target_uid=class_node.uid,
            ))

            for base in cls.base_classes:
                base_uid = f"{NodeLabel.CLASS}:{file_path}:{base}:0"
                edges.append(GraphEdge(
                    edge_type=EdgeType.INHERITS,
                    source_uid=class_node.uid,
                    target_uid=base_uid,
                ))

        for func in result.functions:
            func_node = GraphNode(
                label=NodeLabel.FUNCTION,
                properties={
                    "name": func.name,
                    "file": file_path,
                    "start_line": func.start_line,
                    "end_line": func.end_line,
                    "signature": func.signature,
                    "docstring": func.docstring[:1000] if func.docstring else "",
                    "code_snippet": func.code_snippet,
                    "language": language,
                },
            )
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

        for imp in result.imports:
            imported_uid = f"{NodeLabel.MODULE}::{imp.module}:0"
            edges.append(GraphEdge(
                edge_type=EdgeType.IMPORTS,
                source_uid=module_node.uid,
                target_uid=imported_uid,
            ))

        return nodes, edges
