"""Markdown and RST document indexer.

Parses documents into sections, creates Document graph nodes, and records
inline code reference names on each document node (no phantom Class/Function
nodes from backticks).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from indexer.child_chunker import chunk_document_section
from indexer.smart_chunker import Chunk, smart_chunk_markdown
from log import get_logger
from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel, utc_indexed_at_iso

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

    SUPPORTED_EXTENSIONS = {
        ".md",
        ".markdown",
        ".rst",
        ".txt",
        ".yml",
        ".yaml",
        ".xml",
        ".properties",
        ".env",
        ".toml",
        ".conf",
    }

    @staticmethod
    def iter_supported_paths(base: Path) -> Iterator[Path]:
        """Yield paths under *base* matching any supported extension (single walk)."""
        exts = DocumentIndexer.SUPPORTED_EXTENSIONS
        for fpath in base.rglob("*"):
            if not fpath.is_file():
                continue
            name_lower = fpath.name.lower()
            if name_lower == ".env" or name_lower.endswith(".env"):
                yield fpath
            elif fpath.suffix.lower() in exts:
                yield fpath

    def __init__(
        self,
        exclude_patterns: list[str] | None = None,
        *,
        child_chunk_enabled: bool = False,
        child_chunk_window_chars: int = 800,
        child_chunk_stride_chars: int = 600,
        child_chunk_min_parent_chars: int = 400,
    ) -> None:
        if exclude_patterns is not None:
            self._exclude_dirs = set(exclude_patterns)
        else:
            from config import get_settings
            self._exclude_dirs = set(get_settings().exclude_dirs)
        self._config_indexer = None  # lazy: indexer.config_indexer.ConfigIndexer
        self._child_chunk_enabled = child_chunk_enabled
        self._child_chunk_window = child_chunk_window_chars
        self._child_chunk_stride = child_chunk_stride_chars
        self._child_chunk_min = child_chunk_min_parent_chars

    def _get_config_indexer(self):
        from indexer.config_indexer import ConfigIndexer

        if self._config_indexer is None:
            self._config_indexer = ConfigIndexer(self)
        return self._config_indexer

    def parse_document(
        self, file_path: str, content: str | None = None, *, store_path: str | None = None,
    ) -> ParsedDocument:
        """Parse a document.  *store_path* is what gets stored as the
        persistent file path (relative to repo root).  Falls back to
        *file_path* when not supplied."""
        persist_path = store_path or file_path
        from indexer.config_indexer import ConfigIndexer, _config_file_extension

        ext = _config_file_extension(Path(file_path))
        if ext in ConfigIndexer.SUPPORTED_EXTENSIONS:
            return self._get_config_indexer().parse_config(file_path, persist_path)

        if content is None:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        title = Path(persist_path).stem

        if ext == ".rst":
            sections = self._parse_rst_sections(content)
        else:
            sections = self._parse_markdown_sections(content)

        if sections and sections[0].level == 1:
            title = sections[0].title

        code_refs = self._extract_code_references(content)

        return ParsedDocument(
            title=title,
            path=persist_path,
            sections=sections,
            content_hash=content_hash,
            code_references=code_refs,
        )

    def build_graph(self, doc: ParsedDocument) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        indexed_at = utc_indexed_at_iso()
        doc_node = GraphNode(
            label=NodeLabel.DOCUMENT,
            properties={
                "name": doc.title,
                "file": doc.path,
                "start_line": 1,
                "content_hash": doc.content_hash,
                "title": doc.title,
                "code_references": doc.code_references,
                "indexed_at": indexed_at,
            },
        )
        nodes.append(doc_node)

        for section in doc.sections:
            chunks = smart_chunk_markdown(section.content, target_chars=2000)
            if not chunks:
                chunks = [
                    Chunk(
                        text=section.content or "",
                        start_line=0,
                        end_line=0,
                        heading_context="",
                    )
                ]
            for chunk in chunks:
                chunk_start_line = section.start_line + 1 + chunk.start_line
                section_node = GraphNode(
                    label=NodeLabel.DOCUMENT,
                    properties={
                        "name": section.title,
                        "file": doc.path,
                        "start_line": chunk_start_line,
                        "content_hash": doc.content_hash,
                        "section": section.title,
                        "content": chunk.text,
                        "title": f"{doc.title} > {section.title}",
                        "level": section.level,
                        "heading_context": chunk.heading_context,
                        "document_title": doc.title,
                        "indexed_at": indexed_at,
                    },
                )
                nodes.append(section_node)

                edges.append(GraphEdge(
                    edge_type=EdgeType.CONTAINS,
                    source_uid=doc_node.uid,
                    target_uid=section_node.uid,
                ))

        if self._child_chunk_enabled:
            self._generate_doc_child_chunks(nodes, edges, doc, indexed_at)

        return nodes, edges

    def _generate_doc_child_chunks(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        doc: ParsedDocument,
        indexed_at: str,
    ) -> None:
        """Generate Chunk nodes for large document sections."""
        section_nodes = [
            n for n in list(nodes)
            if n.label == NodeLabel.DOCUMENT and n.properties.get("section")
        ]
        for section_node in section_nodes:
            props = section_node.properties
            content = props.get("content", "")
            if not content or not isinstance(content, str):
                continue
            section_title = str(props.get("section", ""))
            start_line = int(props.get("start_line", 0))

            children = chunk_document_section(
                content=content,
                section_title=section_title,
                doc_title=doc.title,
                start_line=start_line,
                window_chars=self._child_chunk_window,
                stride_chars=self._child_chunk_stride,
                min_parent_chars=self._child_chunk_min,
            )
            for child in children:
                chunk_uid = f"{NodeLabel.CHUNK}:{section_node.uid}:c{child.chunk_index}"
                chunk_node = GraphNode(
                    label=NodeLabel.CHUNK,
                    uid=chunk_uid,
                    properties={
                        "name": f"{section_title}:chunk_{child.chunk_index}",
                        "text": child.text,
                        "parent_uid": section_node.uid,
                        "parent_label": str(NodeLabel.DOCUMENT),
                        "parent_name": section_title,
                        "chunk_index": child.chunk_index,
                        "file": doc.path,
                        "start_line": child.start_line,
                        "end_line": child.end_line,
                        "indexed_at": indexed_at,
                    },
                )
                nodes.append(chunk_node)
                edges.append(GraphEdge(
                    edge_type=EdgeType.PART_OF,
                    source_uid=chunk_uid,
                    target_uid=section_node.uid,
                ))

    def index_directory(self, directory: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []
        base = Path(directory)

        for fpath in type(self).iter_supported_paths(base):
            if any(part in self._exclude_dirs for part in fpath.parts):
                continue
            try:
                rel = str(fpath.relative_to(base))
                doc = self.parse_document(str(fpath), store_path=rel)
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
                simple = parts[-1]
                if len(parts) > 1:
                    refs.append(match)
                refs.append(simple)
        seen: set[str] = set()
        ordered: list[str] = []
        for r in refs:
            if r not in seen:
                seen.add(r)
                ordered.append(r)
        return ordered
