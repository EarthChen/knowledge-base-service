"""Post-generation validator for source:// references in wiki content.

Strips fabricated source references (wrong line numbers, non-existent paths)
and optionally appends a verified "源码定位" section from graph data.

Design rationale: LLMs hallucinate line numbers and file paths when prompted to
generate source:// links.  DeepWiki-style systems solve this by injecting
references programmatically from AST/graph data *after* narrative generation.
This module implements the same pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SOURCE_REF_BACKTICK = re.compile(r"`source://([^/`]+)/([^`]+)`")

_SOURCE_REF_BARE = re.compile(r"(?<![`])source://(\S+)")


@dataclass(frozen=True)
class ParsedRef:
    repository: str
    file_path: str
    line: int


@dataclass(frozen=True)
class VerifiedRef:
    repository: str
    file_path: str
    start_line: int
    label: str


def _parse_ref_body(repo: str, body: str) -> ParsedRef:
    parts = body.rsplit(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return ParsedRef(repository=repo, file_path=parts[0], line=int(parts[1]))
    return ParsedRef(repository=repo, file_path=body, line=0)


def extract_source_refs(content: str) -> list[ParsedRef]:
    """Extract all source:// references from Markdown content."""
    refs: list[ParsedRef] = []
    for m in _SOURCE_REF_BACKTICK.finditer(content):
        refs.append(_parse_ref_body(m.group(1), m.group(2)))
    return refs


def _is_hallucinated(ref: ParsedRef, known_paths: set[str] | None) -> bool:
    if "..." in ref.file_path:
        return True
    if known_paths is not None and ref.file_path not in known_paths:
        return True
    return False


def strip_hallucinated_refs(
    content: str,
    known_file_paths: set[str] | None = None,
) -> str:
    """Remove source:// references that cannot be verified.

    A reference is considered hallucinated when:
    - Its file_path uses ``...`` (ellipsis shorthand, always fabricated)
    - Its file_path is not in ``known_file_paths`` (if provided)
    """
    refs = extract_source_refs(content)
    result = content
    for ref in refs:
        if not _is_hallucinated(ref, known_file_paths):
            continue
        line_suffix = f":{ref.line}" if ref.line > 0 else ""
        literal = f"`source://{ref.repository}/{ref.file_path}{line_suffix}`"
        result = result.replace(literal, "")

    result = re.sub(r"^([-*]\s+)[^:\n]*：\s*\n", "", result, flags=re.MULTILINE)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def build_verified_source_section(
    refs: list[VerifiedRef],
    *,
    header: str = "## 源码定位",
) -> str:
    """Build a Markdown section with verified source references."""
    if not refs:
        return ""
    lines = [header, ""]
    for ref in refs:
        loc = f"`source://{ref.repository}/{ref.file_path}"
        if ref.start_line > 0:
            loc += f":{ref.start_line}"
        loc += "`"
        lines.append(f"- {ref.label}：{loc}")
    return "\n".join(lines)


def sanitize_wiki_content(
    content: str,
    known_entities: list[dict[str, str | int]] | None = None,
) -> str:
    """Full sanitization pass: strip hallucinated refs.

    The verified ``## 源码定位`` section is no longer appended here because
    the dashboard UI already renders ``WikiSourceLocRow`` (interactive IDE
    links) and ``Related Code Entities`` from graph ``SOURCE_ENTITY`` edges,
    which provide the same information with better UX.

    ``known_entities`` is still used to build the ``known_paths`` set for
    hallucination detection.
    """
    known_paths: set[str] | None = None

    if known_entities:
        known_paths = set()
        for ent in known_entities:
            fp = str(ent.get("file_path") or "").strip()
            if fp:
                known_paths.add(fp)

    cleaned = strip_hallucinated_refs(content, known_paths)

    cleaned = re.sub(r"\n## 源码定位\n.*", "", cleaned, flags=re.DOTALL)

    return cleaned
