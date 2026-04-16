"""Index quality report — statistics collected during indexing operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IndexReport:
    """Statistics about an indexing operation."""

    total_files: int = 0
    success_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    failed_file_list: list[dict[str, str]] = field(default_factory=list)
    node_counts: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)
    annotation_counts: dict[str, int] = field(default_factory=dict)
    type_coverage: float = 0.0
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        self._typed_functions: int = 0
        self._total_functions: int = 0

    def record_file_success(self, _file_path: str, nodes: list, edges: list) -> None:
        """Record a successfully indexed file and accumulate node/edge stats."""
        self.success_files += 1
        for node in nodes:
            label = str(node.label)
            self.node_counts[label] = self.node_counts.get(label, 0) + 1
            # Count annotations
            annotations = node.properties.get("annotations", [])
            for ann in annotations:
                # Strip @ and arguments for counting
                name = ann.lstrip("@").split("(")[0].strip()
                if name:
                    self.annotation_counts[name] = self.annotation_counts.get(name, 0) + 1
            # Track type coverage for functions
            if str(node.label) == "Function":
                if node.properties.get("return_type") or node.properties.get("parameters"):
                    self._typed_functions += 1
                self._total_functions += 1
        for edge in edges:
            etype = str(edge.edge_type)
            self.edge_counts[etype] = self.edge_counts.get(etype, 0) + 1

    def record_file_failure(self, file_path: str, error: str) -> None:
        """Record a file that failed to index."""
        self.failed_files += 1
        self.failed_file_list.append({"file": file_path, "error": error})

    def record_file_skipped(self) -> None:
        """Record a file that was skipped (e.g. unsupported language)."""
        self.skipped_files += 1

    def finalize(self) -> None:
        """Compute derived metrics after all files are processed."""
        self.total_files = self.success_files + self.failed_files + self.skipped_files
        if self._total_functions > 0:
            self.type_coverage = self._typed_functions / self._total_functions
        else:
            self.type_coverage = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "total_files": self.total_files,
            "success_files": self.success_files,
            "skipped_files": self.skipped_files,
            "failed_files": self.failed_files,
            "failed_file_list": self.failed_file_list[:50],  # cap for API response size
            "node_counts": self.node_counts,
            "edge_counts": self.edge_counts,
            "annotation_counts": self.annotation_counts,
            "type_coverage": round(self.type_coverage, 4),
            "duration_seconds": round(self.duration_seconds, 2),
        }
