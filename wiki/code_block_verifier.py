"""Verify and reconcile wiki fenced code blocks against known snippets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

MAX_CODE_LINES = 20

_INJECT_SENTINEL = "<!-- __INJECTED_CODE_REF__ -->\n"

_CODE_REF_RE = re.compile(
    r"<!--\s*CODE_REF:\s*([^\s@>]+)\s*(?:@\s*([^>]+?))?\s*-->",
    re.IGNORECASE,
)

_FENCED_BLOCK_RE = re.compile(r"(```(\w*)\n(.*?)\n```)", re.DOTALL)

_TOKEN_RE = re.compile(r"[A-Za-z_]\w{2,}")

_LANG_BY_EXT: dict[str, str] = {
    ".java": "java",
    ".py": "python",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".rb": "ruby",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".h": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".sql": "sql",
    ".sh": "bash",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass
class CodeBlock:
    start: int
    end: int
    language: str
    code: str


@dataclass
class VerificationStats:
    injected: int = 0
    replaced: int = 0
    verified: int = 0
    unverified: int = 0


def parse_code_ref(marker: str) -> tuple[str | None, str | None]:
    m = _CODE_REF_RE.fullmatch(marker.strip())
    if not m:
        return (None, None)
    entity = m.group(1).strip()
    raw_hint = m.group(2)
    file_hint = raw_hint.strip() if raw_hint else None
    return (entity or None, file_hint)


def extract_code_blocks(content: str) -> list[CodeBlock]:
    out: list[CodeBlock] = []
    for m in _FENCED_BLOCK_RE.finditer(content):
        out.append(
            CodeBlock(
                start=m.start(1),
                end=m.end(1),
                language=m.group(2),
                code=m.group(3),
            )
        )
    return out


def _token_set(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text))


def _token_jaccard(a: str, b: str) -> float:
    sa, sb = _token_set(a), _token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def compute_similarity(code: str, snippet_code: str, snippet_entity: str) -> float:
    ent = snippet_entity.strip().lower()
    identifier_overlap = 1.0 if ent and ent in code.lower() else 0.0
    token_jaccard = _token_jaccard(code, snippet_code)
    return 0.4 * identifier_overlap + 0.6 * token_jaccard


def _parse_snippet_header(snippet: str) -> tuple[str, str]:
    s = snippet.lstrip("\ufeff")
    if not s.startswith("["):
        return "", snippet
    sep_newline = s.find("]\n")
    if sep_newline != -1:
        header = s[1:sep_newline]
        body = s[sep_newline + 2 :].lstrip("\n")
        return _split_header_rest(header, body)
    close = s.find("]")
    if close == -1:
        return "", snippet
    header = s[1:close]
    remainder = s[close + 1 :].lstrip("\n\r")
    return _split_header_rest(header, remainder)


def _split_header_rest(header: str, body: str) -> tuple[str, str]:
    if " @ " not in header:
        return "", header + body if body else ""
    ent, fp = header.split(" @ ", 1)
    return ent.strip(), body


def _extract_file_from_snippet(snippet: str) -> tuple[str, str]:
    ent, body = _parse_snippet_header(snippet)
    if not ent:
        return "", ""
    s = snippet.lstrip("\ufeff")
    if not s.startswith("["):
        return "", ""
    sep_newline = s.find("]\n")
    header_end = sep_newline if sep_newline != -1 else s.find("]")
    if header_end == -1:
        return "", ""
    header = s[1:header_end]
    if " @ " not in header:
        return "", ""
    _, fp = header.split(" @ ", 1)
    return ent, fp.strip()


def _snippet_body(snippet: str) -> str:
    _, body = _parse_snippet_header(snippet)
    return body


def match_snippet(code: str, snippets: list[str]) -> tuple[str | None, float]:
    best_snip: str | None = None
    best_score = 0.0
    seen = False
    for raw in snippets:
        ent, body = _parse_snippet_header(raw)
        if not ent:
            continue
        seen = True
        sc = compute_similarity(code, body, ent)
        if sc > best_score or best_snip is None:
            best_score = sc
            best_snip = raw
    if not seen:
        return (None, 0.0)
    if best_score >= 0.5 and best_snip is not None:
        return (best_snip, best_score)
    return (None, best_score)


def infer_language(file_path: str) -> str:
    if not file_path:
        return ""
    lower = file_path.lower()
    for ext in sorted(_LANG_BY_EXT, key=len, reverse=True):
        if lower.endswith(ext):
            return _LANG_BY_EXT[ext]
    return ""


def format_code_block(code: str, entity: str, file_path: str, language: str) -> str:
    lines = code.splitlines()
    max_body = MAX_CODE_LINES - 1
    if max_body < 1:
        max_body = 1
    truncated = "\n".join(lines[:max_body])
    inner = f"// {entity} @ {file_path}\n{truncated}"
    return f"```{language}\n{inner}\n```"


def _find_in_snippets(entity: str, file_hint: str | None, snippets: list[str]) -> tuple[str, str]:
    ent_low = entity.strip().lower()
    matches: list[tuple[str, str]] = []
    for s in snippets:
        ent, fp = _extract_file_from_snippet(s)
        if not ent or ent.lower() != ent_low:
            continue
        body = _snippet_body(s).strip()
        matches.append((body, fp))
    if not matches:
        return "", ""

    if file_hint and file_hint.strip():
        fh = file_hint.strip().lower().replace("\\", "/")
        for body, fp in matches:
            pl = fp.lower().replace("\\", "/")
            if fh in pl or pl.endswith(fh) or fh.endswith(pl):
                return body, fp
        return "", ""

    return matches[0]


_GRAPH_LOOKUP_CY = (
    "MATCH (f:Function) WHERE f.name CONTAINS $name "
    "RETURN f.code_snippet, f.file_path LIMIT 1"
)


async def _lookup_in_graph(
    entity: str,
    file_hint: str | None,
    graph_store: Any,
) -> tuple[str, str]:
    if graph_store is None:
        return "", ""
    try:
        result = await graph_store.execute_query(
            _GRAPH_LOOKUP_CY,
            {"name": entity},
        )
    except Exception:
        log.warning("code_block_graph_lookup_failed", entity=entity, exc_info=True)
        return "", ""
    rows = getattr(result, "data", None) or []
    if not rows:
        return "", ""
    row = rows[0]
    code = (
        str(row.get("f.code_snippet") or row.get("code_snippet") or "").strip()
    )
    path = str(row.get("f.file_path") or row.get("file_path") or "").strip()
    if not code:
        return "", ""
    if file_hint and file_hint.strip():
        fh = file_hint.strip().lower().replace("\\", "/")
        pl = path.lower().replace("\\", "/")
        if fh not in pl and not pl.endswith(fh) and not fh.endswith(pl):
            return "", ""
    return code, path


def _blocked_by_phase1_injection(content: str, block_start: int) -> bool:
    n = len(_INJECT_SENTINEL)
    if block_start < n:
        return False
    return content[block_start - n : block_start] == _INJECT_SENTINEL


def _apply_replacements(content: str, spans: list[tuple[int, int, str]]) -> str:
    out = content
    for start, end, repl in sorted(spans, key=lambda x: x[0], reverse=True):
        out = out[:start] + repl + out[end:]
    return out


async def verify_and_inject(
    content: str,
    code_snippets: list[str],
    graph_store: Any | None = None,
) -> tuple[str, VerificationStats]:
    stats = VerificationStats()
    if not content:
        return content, stats

    phase1: list[tuple[int, int, str]] = []
    for m in _CODE_REF_RE.finditer(content):
        marker = m.group(0)
        entity, file_hint = parse_code_ref(marker)
        if not entity:
            continue
        code_txt, fp = _find_in_snippets(entity, file_hint, code_snippets)
        if not code_txt:
            code_txt, fp = await _lookup_in_graph(entity, file_hint, graph_store)
        if code_txt:
            fp = fp or ""
            repl = (
                _INJECT_SENTINEL
                + format_code_block(code_txt, entity.strip(), fp, infer_language(fp))
            )
            phase1.append((m.start(), m.end(), repl))
            stats.injected += 1

    content = _apply_replacements(content, phase1)

    fence_blocks = [
        b
        for b in extract_code_blocks(content)
        if not _blocked_by_phase1_injection(content, b.start)
    ]

    replacements: list[tuple[int, int, str]] = []
    unverified_positions: list[int] = []
    for block in fence_blocks:
        matched, score = match_snippet(block.code, code_snippets)
        if score >= 0.9:
            stats.verified += 1
        elif score >= 0.5 and matched is not None:
            ent, snippet_code = _parse_snippet_header(matched)
            _, fp = _extract_file_from_snippet(matched)
            new_block = format_code_block(
                snippet_code.strip(),
                ent,
                fp or "",
                infer_language(fp),
            )
            replacements.append((block.start, block.end, new_block))
            stats.replaced += 1
        else:
            unverified_positions.append(block.start)
            stats.unverified += 1

    for start, end, new_block in sorted(replacements, key=lambda t: t[0], reverse=True):
        content = content[:start] + new_block + content[end:]

    warn = "<!-- UNVERIFIED_CODE -->\n"
    for pos in sorted(unverified_positions, reverse=True):
        content = content[:pos] + warn + content[pos:]

    return content, stats
