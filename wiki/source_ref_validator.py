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
from typing import Any

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


_CJK_RANGE = r"\u4e00-\u9fff\u3400-\u4dbf"

_MERMAID_NODE_RE = re.compile(
    r"(\w+)"
    r"(\[|\{|\(|\(\()"
    r"([^\]})\"]+?)"
    r"(\]|\}|\)|\)\))",
)

_MERMAID_EDGE_LABEL_RE = re.compile(
    r"(\|)([^|\"]+?)(\|)",
)


def fix_mermaid_cjk_quoting(mermaid_code: str) -> str:
    """Add quotes around CJK text in Mermaid node labels and edge labels."""
    cjk_pat = re.compile(f"[{_CJK_RANGE}]")

    def _quote_node(m: re.Match) -> str:
        node_id, open_br, text, close_br = m.group(1), m.group(2), m.group(3), m.group(4)
        if cjk_pat.search(text) and not text.startswith('"'):
            text = f'"{text.strip()}"'
        return f"{node_id}{open_br}{text}{close_br}"

    def _quote_edge(m: re.Match) -> str:
        pipe1, text, pipe2 = m.group(1), m.group(2), m.group(3)
        if cjk_pat.search(text) and not text.startswith('"'):
            text = f'"{text.strip()}"'
        return f"{pipe1}{text}{pipe2}"

    result = _MERMAID_NODE_RE.sub(_quote_node, mermaid_code)
    result = _MERMAID_EDGE_LABEL_RE.sub(_quote_edge, result)
    return result


_MERMAID_BLOCK_RE = re.compile(r"(```mermaid\n)(.*?)(```)", re.DOTALL)

_MERMAID_SUBGRAPH_CJK_RE = re.compile(
    r"(subgraph\s+)([^\n\"]+)", re.MULTILINE
)

_CJK_CHECK = re.compile(f"[{_CJK_RANGE}]")


def _fix_subgraph_labels(code: str) -> str:
    """Quote subgraph labels containing CJK."""
    def _quote_sub(m: re.Match) -> str:
        prefix, label = m.group(1), m.group(2)
        if _CJK_CHECK.search(label) and not label.strip().startswith('"'):
            return f'{prefix}"{label.strip()}"'
        return m.group(0)
    return _MERMAID_SUBGRAPH_CJK_RE.sub(_quote_sub, code)


def _fix_mermaid_blocks(content: str) -> str:
    """Fix CJK quoting in mermaid blocks; remove blocks that remain broken."""
    def _replace(m: re.Match) -> str:
        prefix, code, suffix = m.group(1), m.group(2), m.group(3)
        fixed = fix_mermaid_cjk_quoting(code)
        fixed = _fix_subgraph_labels(fixed)
        try:
            from wiki.mermaid_validator import validate_mermaid_block

            result = validate_mermaid_block(fixed)
            if not result.is_valid:
                return (
                    "<details><summary>图表源码（渲染失败）</summary>\n\n"
                    f"```\n{code}```\n\n</details>"
                )
        except Exception:
            pass
        return prefix + fixed + suffix

    return _MERMAID_BLOCK_RE.sub(_replace, content)


_COLLAPSED_MERMAID_RE = re.compile(
    r"<details><summary>图表源码（渲染失败）</summary>\n\n"
    r"```\n(.*?)```\n\n</details>",
    re.DOTALL,
)

_MERMAID_REPAIR_SYSTEM = (
    "You are a Mermaid diagram syntax expert. "
    "The user will give you a broken Mermaid diagram. "
    "Fix the syntax errors and return ONLY the corrected Mermaid code. "
    "No markdown fences, no explanations. Return ONLY valid Mermaid code.\n\n"
    "Common issues to fix:\n"
    "- Unquoted CJK labels in nodes/edges/subgraphs\n"
    "- Invalid arrow syntax\n"
    "- Missing or extra brackets\n"
    "- Invalid participant/node identifiers (use alphanumeric only)\n"
    "- Malformed subgraph blocks\n"
    "If the diagram is completely unsalvageable, return exactly: UNFIXABLE"
)

_MERMAID_REPAIR_MAX_RETRIES = 1


async def repair_broken_mermaid_blocks(
    content: str,
    llm: "Any",
) -> str:
    """Use LLM to repair collapsed (broken) Mermaid blocks in wiki content.

    Finds ``<details>`` blocks produced by ``_fix_mermaid_blocks`` for diagrams
    that failed validation, sends the original code to the LLM for correction,
    validates the result, and restores the block if fixed successfully.
    """
    from wiki.mermaid_validator import validate_mermaid_block

    matches = list(_COLLAPSED_MERMAID_RE.finditer(content))
    if not matches or llm is None:
        return content

    result = content
    for m in reversed(matches):
        original_code = m.group(1)
        if not original_code.strip():
            continue

        prompt = (
            f"Fix this broken Mermaid diagram:\n\n{original_code.strip()}\n\n"
            "Return ONLY the corrected Mermaid code."
        )

        try:
            fixed_raw = await llm.generate(
                prompt, system=_MERMAID_REPAIR_SYSTEM, max_tokens=2000,
            )
        except Exception:
            continue

        if not fixed_raw or "UNFIXABLE" in fixed_raw.strip():
            continue

        fixed = fixed_raw.strip()
        if fixed.startswith("```"):
            first_nl = fixed.find("\n")
            if first_nl != -1:
                fixed = fixed[first_nl + 1:]
            if fixed.endswith("```"):
                fixed = fixed[:-3]
            fixed = fixed.strip()

        if not fixed:
            continue

        validation = validate_mermaid_block(fixed)
        if validation.is_valid:
            replacement = f"```mermaid\n{fixed}\n```"
            result = result[:m.start()] + replacement + result[m.end():]

    return result


def sanitize_wiki_content(
    content: str,
    known_entities: list[dict[str, str | int]] | None = None,
) -> str:
    """Full sanitization pass: strip hallucinated refs, fix Mermaid CJK quoting.

    ``known_entities`` is used to build the ``known_paths`` set for
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
    cleaned = re.sub(r"\n## 源码位置\n.*", "", cleaned, flags=re.DOTALL)

    cleaned = _fix_mermaid_blocks(cleaned)

    return cleaned
