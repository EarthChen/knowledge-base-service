"""Configuration file indexer — YAML, XML, Java properties, .env, TOML."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from indexer.doc_indexer import DocumentIndexer, DocumentSection, ParsedDocument
from log import get_logger

log = get_logger(__name__)

try:  # Python 3.11+
    import tomllib
except ImportError:
    tomllib = None  # pragma: no cover


def _sha256_16(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


CONFIG_FILE_EXTENSIONS = frozenset({".yml", ".yaml", ".xml", ".properties", ".env", ".toml", ".conf"})


def _config_file_extension(path: Path) -> str:
    """Return config extension; handles ``.env`` (Path.suffix is empty for that filename)."""
    suf = path.suffix.lower()
    if suf:
        return suf
    name = path.name.lower()
    for ext in sorted(CONFIG_FILE_EXTENSIONS, key=len, reverse=True):
        if name.endswith(ext):
            return ext
    return ""


class ConfigIndexer:
    """Indexes configuration files (.yml, .yaml, .xml, .properties, .env, .toml)."""

    SUPPORTED_EXTENSIONS = CONFIG_FILE_EXTENSIONS

    def __init__(self, document_indexer: DocumentIndexer | None = None) -> None:
        self._document_indexer = document_indexer or DocumentIndexer()

    def parse_config(self, file_path: str, store_path: str = "") -> ParsedDocument:
        """Parse config file into sections based on format."""
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="replace")
        persist_path = store_path or str(file_path)
        title = Path(persist_path).stem or Path(persist_path).name
        ext = _config_file_extension(path)
        content_hash = _sha256_16(content)
        code_refs = DocumentIndexer._extract_code_references(content)

        if not content.strip():
            return ParsedDocument(
                title=title,
                path=persist_path,
                sections=[],
                content_hash=content_hash,
                code_references=code_refs,
            )

        if ext in (".yml", ".yaml"):
            sections = self._parse_yaml_sections(content)
        elif ext == ".xml":
            sections = self._parse_xml_sections(content, path)
        elif ext in (".properties", ".env", ".conf"):
            sections = self._parse_kv_grouped_sections(content)
        elif ext == ".toml":
            sections = self._parse_toml_sections(content)
        else:
            sections = []

        return ParsedDocument(
            title=title,
            path=persist_path,
            sections=sections,
            content_hash=content_hash,
            code_references=code_refs,
        )

    def build_graph(self, doc: ParsedDocument) -> tuple[list, list]:
        """Build graph nodes and edges for a parsed config document (same shape as DocumentIndexer)."""
        return self._document_indexer.build_graph(doc)

    def _serialize_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).strip()
        return str(value)

    def _parse_yaml_sections(self, content: str) -> list[DocumentSection]:
        try:
            loaded = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            log.warning("yaml_parse_error", error=str(exc))
            return []

        if loaded is None:
            return []

        if not isinstance(loaded, dict):
            lines = content.split("\n")
            return [
                DocumentSection(
                    title="document",
                    content=self._serialize_value(loaded),
                    level=2,
                    start_line=1,
                    end_line=len(lines),
                ),
            ]

        lines = content.split("\n")
        key_order, starts = self._scan_yaml_top_level_keys(content, set(loaded.keys()))
        ordered_keys = list(dict.fromkeys([*key_order, *[k for k in loaded if k not in key_order]]))
        sections: list[DocumentSection] = []
        for key in ordered_keys:
            if key not in loaded:
                continue
            if key not in starts:
                start_line, end_line = 1, len(lines)
            else:
                start_line, end_line = self._yaml_key_span(starts, key_order, key, len(lines))
            body = "\n".join(lines[start_line - 1 : end_line]).strip()
            val = loaded[key]
            section_text = body if body else self._serialize_value(val)
            sections.append(
                DocumentSection(
                    title=str(key),
                    content=section_text,
                    level=2,
                    start_line=start_line,
                    end_line=end_line,
                ),
            )
        return sections

    def _scan_yaml_top_level_keys(self, content: str, keys: set[str]) -> tuple[list[str], dict[str, int]]:
        """Return declaration order of top-level keys and 1-based start line per key."""
        lines = content.split("\n")
        key_order: list[str] = []
        starts: dict[str, int] = {}
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue
            if stripped == "---":
                i += 1
                continue
            if line[:1] in (" ", "\t"):
                i += 1
                continue
            m = re.match(r"^([a-zA-Z_][\w.-]*)\s*:", stripped)
            if m:
                key = m.group(1)
                if key in keys and key not in starts:
                    starts[key] = i + 1
                    key_order.append(key)
                i += 1
            else:
                i += 1
        return key_order, starts

    def _yaml_key_span(
        self, starts: dict[str, int], key_order: list[str], key: str, n_lines: int,
    ) -> tuple[int, int]:
        """start_line: 1-based; end_line: 0-based exclusive (matches DocumentIndexer slices)."""
        idx = key_order.index(key)
        start_line = starts[key]
        if idx + 1 < len(key_order):
            next_key = key_order[idx + 1]
            end_line = starts[next_key] - 1
        else:
            end_line = n_lines
        return (start_line, end_line)

    def _parse_xml_sections(self, content: str, path: Path) -> list[DocumentSection]:
        try:
            parser = ET.XMLParser()
            parser.feed(content)
            root = parser.close()
        except ET.ParseError as exc:
            log.warning("xml_parse_error", file=str(path), error=str(exc))
            return []

        lines = content.split("\n")
        children = list(root)
        if not children and root.text and root.text.strip():
            return [
                DocumentSection(
                    title=root.tag,
                    content=(root.text or "").strip(),
                    level=2,
                    start_line=1,
                    end_line=len(lines),
                ),
            ]

        sections: list[DocumentSection] = []
        for child in children:
            try:
                if hasattr(ET, "indent"):
                    cpy = ET.Element(child.tag, child.attrib)
                    cpy.text = child.text
                    cpy.tail = child.tail
                    for sub in child:
                        cpy.append(sub)
                    ET.indent(cpy, space="  ")
                    blob = ET.tostring(cpy, encoding="unicode")
                else:
                    blob = ET.tostring(child, encoding="unicode")
            except Exception as exc:  # pragma: no cover
                log.warning("xml_serialize_error", error=str(exc))
                blob = ET.tostring(child, encoding="unicode")

            opener = f"<{child.tag}"
            start_line = 1
            for li, line in enumerate(lines, start=1):
                if opener in line or line.strip().startswith(f"<{child.tag}"):
                    start_line = li
                    break
            end_line = len(lines)
            needle = f"</{child.tag}>"
            seen = False
            for li in range(start_line - 1, len(lines)):
                if needle in lines[li]:
                    end_line = li + 1
                    seen = True
                    break
            if not seen:
                end_line = min(start_line + blob.count("\n"), len(lines))
            if end_line < start_line:
                end_line = start_line

            sections.append(
                DocumentSection(
                    title=child.tag,
                    content=blob.strip(),
                    level=2,
                    start_line=start_line,
                    end_line=end_line,
                ),
            )
        return sections

    def _parse_kv_lines(self, content: str) -> list[tuple[str, str, int]]:
        """Return list of (key, value, line_number_starting_at_1)."""
        lines = content.split("\n")
        out: list[tuple[str, str, int]] = []
        i = 0
        while i < len(lines):
            raw = lines[i]
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                i += 1
                continue
            if line.lower().startswith("export ") and "=" in line:
                line = line[7:].strip()
            if "=" not in line:
                i += 1
                continue
            key, _, rest = line.partition("=")
            key = key.strip()
            value = rest
            ln = i + 1
            if raw.rstrip().endswith("\\"):
                chunk = [value.rstrip()[:-1].rstrip() if value.rstrip().endswith("\\") else value]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt.rstrip().endswith("\\"):
                        chunk.append(nxt.rstrip()[:-1].rstrip())
                        j += 1
                    else:
                        chunk.append(nxt.strip())
                        j += 1
                        break
                value = "\n".join(chunk)
                i = j
            else:
                i += 1
            out.append((key, value, ln))
        return out

    def _group_prefix(self, key: str, all_keys: list[str]) -> str:
        parts = key.split(".")
        for j in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:j])
            pd = prefix + "."
            n = sum(1 for k in all_keys if k == prefix or k.startswith(pd))
            if n >= 2:
                return prefix
        return key

    def _parse_kv_grouped_sections(self, content: str) -> list[DocumentSection]:
        pairs = self._parse_kv_lines(content)
        if not pairs:
            return []

        keys = [p[0] for p in pairs]
        groups: dict[str, list[tuple[str, str, int]]] = {}
        for key, val, ln in pairs:
            g = self._group_prefix(key, keys)
            groups.setdefault(g, []).append((key, val, ln))

        sections: list[DocumentSection] = []
        n_lines = len(content.split("\n"))
        for gname in sorted(groups.keys(), key=lambda x: (groups[x][0][2], x)):
            items = groups[gname]
            body = "\n".join(f"{k}={v}" for k, v, _ in items)
            start_line = min(ln for _, _, ln in items)
            max_ln = max(ln for _, _, ln in items)
            end_line = max_ln if max_ln < n_lines else n_lines
            sections.append(
                DocumentSection(
                    title=gname,
                    content=body,
                    level=2,
                    start_line=start_line,
                    end_line=end_line,
                ),
            )
        return sections

    def _parse_toml_sections(self, content: str) -> list[DocumentSection]:
        if tomllib is None:
            log.warning("tomllib_unavailable")
            return []
        try:
            data = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            log.warning("toml_parse_error", error=str(exc))
            return []

        lines = content.split("\n")
        table_spans = self._scan_toml_table_spans(content)
        sections: list[DocumentSection] = []

        for key, value in data.items():
            if isinstance(value, dict):
                title = key
                blob = self._serialize_value(value)
                start_line, end_line = table_spans.get(key, (1, len(lines)))
            else:
                title = key
                blob = f"{key} = {self._toml_scalar_repr(value)}"
                start_line, end_line = self._find_kv_line_span(lines, key)

            sections.append(
                DocumentSection(
                    title=title,
                    content=blob,
                    level=2,
                    start_line=start_line,
                    end_line=end_line,
                ),
            )
        return sections

    def _toml_scalar_repr(self, value: Any) -> str:
        import json as _json

        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return _json.dumps(value, ensure_ascii=False)
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)

    def _find_kv_line_span(self, lines: list[str], key: str) -> tuple[int, int]:
        """1-based start line, 0-based exclusive end (single-line assignment)."""
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i, line in enumerate(lines):
            if pat.match(line):
                s1 = i + 1
                return (s1, s1)
        n = len(lines)
        return (1, n)

    def _scan_toml_table_spans(self, content: str) -> dict[str, tuple[int, int]]:
        lines = content.split("\n")
        headers: list[tuple[str, int]] = []
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("[["):
                continue
            m = re.match(r"^\[([^\]]+)\]\s*$", s)
            if m:
                name = m.group(1).strip()
                if name:
                    headers.append((name, i + 1))

        spans: dict[str, tuple[int, int]] = {}
        for idx, (name, start_ln) in enumerate(headers):
            if idx + 1 < len(headers):
                end_ln = headers[idx + 1][1] - 1
            else:
                end_ln = len(lines)
            spans[name] = (start_ln, end_ln)
        return spans

