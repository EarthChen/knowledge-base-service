"""Orchestrate writing wiki pages to disk with index generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wiki.exporter import WikiExporter
from wiki.models import WikiPage, WikiStructure, WikiStructureNode


@dataclass
class ExportResult:
    """Result of exporting wiki Markdown to a directory."""

    files_created: list[str]
    total_size_bytes: int
    index_path: str


class WikiDiskExporter:
    """Orchestrates writing wiki pages to disk in a git-friendly structure."""

    def __init__(self, exporter: WikiExporter) -> None:
        self._exporter = exporter

    def export_to_disk(
        self,
        pages: list[WikiPage],
        structure: WikiStructure,
        output_dir: str,
    ) -> ExportResult:
        """Write wiki pages and ``index.md`` under ``output_dir``.

        Pages are rendered via :meth:`WikiExporter.export_markdown_fileset` so
        cross-reference links match standalone Markdown export behavior.
        """
        created = self._exporter.export_markdown_fileset(pages, structure, output_dir)
        out_root = Path(output_dir)
        index_path = out_root / "index.md"
        index_path.write_text(self.generate_index(pages, structure), encoding="utf-8")

        all_paths = [*created, str(index_path.resolve())]
        total_size = sum(Path(p).stat().st_size for p in all_paths)
        return ExportResult(
            files_created=sorted(all_paths),
            total_size_bytes=total_size,
            index_path=str(index_path.resolve()),
        )

    def generate_index(self, pages: list[WikiPage], structure: WikiStructure) -> str:
        """Generate ``index.md`` content with a tree-shaped table of contents."""
        lines: list[str] = [
            f"# {structure.repository} Wiki",
            "",
            "## Contents",
            "",
        ]

        def walk(node: WikiStructureNode, depth: int) -> None:
            indent = "  " * depth
            rel = node.path.replace("\\", "/").rstrip("/")
            if node.path.endswith(".md"):
                lines.append(f"{indent}- [{node.title}]({rel})")
            else:
                lines.append(f"{indent}- **{node.title}**")
            for child in sorted(node.children, key=lambda n: (n.title.lower(), n.path)):
                walk(child, depth + 1)

        walk(structure.root, 0)

        lines.extend(["", "## All pages", ""])
        for page in sorted(pages, key=lambda p: p.path.lower()):
            pl = page.path.replace("\\", "/")
            lines.append(f"- [{page.title}]({pl})")

        return "\n".join(lines).rstrip() + "\n"
