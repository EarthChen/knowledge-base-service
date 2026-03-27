"""Markdown and RST document indexer.

Parses documents into sections, creates Document graph nodes,
and establishes REFERENCES edges to code entities mentioned in docs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from log import get_logger

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel

log = get_logger(__name__)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
RST_HEADING_RE = re.compile(r"^(.+)\n([=\-~^\"]+)$", re.MULTILINE)


@dataclass
class DocumentSection:
    title: str
    content: str
    level: int
    start_line: int
    end_line: int


@dataclass
class ParsedDocument:
    title: str
    path: str
    sections: list[DocumentSection] = field(default_factory=list)
    content_hash: str = ""
    code_references: list[str] = field(default_factory=list)


class DocumentIndexer:
    """Indexes Markdown and RST documents into the knowledge graph."""

    SUPPORTED_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}

    def __init__(self, exclude_patterns: list[str] | None = None) -> None:
        self._exclude_dirs = set(exclude_patterns or [])
        self._exclude_dirs.update({"node_modules", ".git", ".venv", "venv", "__pycache__"})

    def parse_document(self, file_path: str, content: str | None = None) -> ParsedDocument:
        if content is None:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        title = Path(file_path).stem

        ext = Path(file_path).suffix.lower()
        if ext == ".rst":
            sections = self._parse_rst_sections(content)
        else:
            sections = self._parse_markdown_sections(content)

        if sections and sections[0].level == 1:
            title = sections[0].title

        code_refs = self._extract_code_references(content)

        return ParsedDocument(
            title=title,
            path=file_path,
            sections=sections,
            content_hash=content_hash,
            code_references=code_refs,
        )

    def build_graph(self, doc: ParsedDocument) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        doc_node = GraphNode(
            label=NodeLabel.DOCUMENT,
            properties={
                "name": doc.title,
                "file": doc.path,
                "start_line": 1,
                "content_hash": doc.content_hash,
                "title": doc.title,
                "code_references": doc.code_references,
            },
        )
        nodes.append(doc_node)

        for section in doc.sections:
            section_content = section.content[:2000]
            section_node = GraphNode(
                label=NodeLabel.DOCUMENT,
                properties={
                    "name": section.title,
                    "file": doc.path,
                    "start_line": section.start_line,
                    "content_hash": doc.content_hash,
                    "section": section.title,
                    "content": section_content,
                    "title": f"{doc.title} > {section.title}",
                    "level": section.level,
                },
            )
            nodes.append(section_node)

            edges.append(GraphEdge(
                edge_type=EdgeType.CONTAINS,
                source_uid=doc_node.uid,
                target_uid=section_node.uid,
            ))

        return nodes, edges

    def index_directory(self, directory: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []
        base = Path(directory)

        for ext in self.SUPPORTED_EXTENSIONS:
            for fpath in base.rglob(f"*{ext}"):
                if any(part in self._exclude_dirs for part in fpath.parts):
                    continue
                try:
                    doc = self.parse_document(str(fpath))
                    nodes, edges = self.build_graph(doc)
                    all_nodes.extend(nodes)
                    all_edges.extend(edges)
                except Exception as exc:
                    log.warning("doc_parse_error", file=str(fpath), error=str(exc))

        log.info("doc_directory_indexed", directory=directory, nodes=len(all_nodes), edges=len(all_edges))
        return all_nodes, all_edges

    def _parse_markdown_sections(self, content: str) -> list[DocumentSection]:
        sections: list[DocumentSection] = []
        lines = content.split("\n")

        heading_positions: list[tuple[int, int, str]] = []
        for i, line in enumerate(lines):
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                heading_positions.append((i, len(m.group(1)), m.group(2).strip()))

        for idx, (line_num, level, title) in enumerate(heading_positions):
            if idx + 1 < len(heading_positions):
                end_line = heading_positions[idx + 1][0]
            else:
                end_line = len(lines)

            section_content = "\n".join(lines[line_num + 1 : end_line]).strip()
            sections.append(DocumentSection(
                title=title,
                content=section_content,
                level=level,
                start_line=line_num + 1,
                end_line=end_line,
            ))

        return sections

    def _parse_rst_sections(self, content: str) -> list[DocumentSection]:
        sections: list[DocumentSection] = []
        rst_chars = {"=": 1, "-": 2, "~": 3, "^": 4, '"': 5}

        lines = content.split("\n")
        heading_positions: list[tuple[int, int, str]] = []

        for i in range(len(lines) - 1):
            title_line = lines[i].strip()
            underline = lines[i + 1].strip()
            if title_line and underline and len(underline) >= len(title_line):
                char = underline[0]
                if char in rst_chars and all(c == char for c in underline):
                    heading_positions.append((i, rst_chars[char], title_line))

        for idx, (line_num, level, title) in enumerate(heading_positions):
            if idx + 1 < len(heading_positions):
                end_line = heading_positions[idx + 1][0]
            else:
                end_line = len(lines)

            section_content = "\n".join(lines[line_num + 2 : end_line]).strip()
            sections.append(DocumentSection(
                title=title,
                content=section_content,
                level=level,
                start_line=line_num + 1,
                end_line=end_line,
            ))

        return sections

    @staticmethod
    def _extract_code_references(content: str) -> list[str]:
        """Extract inline code references that look like identifiers."""
        cleaned = CODE_BLOCK_RE.sub("", content)
        matches = INLINE_CODE_RE.findall(cleaned)

        refs: list[str] = []
        identifier_re = re.compile(r"^[a-zA-Z_]\w*(?:\.\w+)*$")
        for match in matches:
            match = match.strip()
            if identifier_re.match(match) and len(match) > 2:
                parts = match.split(".")
                refs.append(parts[-1])
        return list(set(refs))
