"""Unified content quality detection rules — Single Source of Truth.

All quality checks (hallucination, boilerplate, meta-sections, CN ratio,
code-block integrity) are defined here and imported by:
  - scripts/audit_wiki_data.py (audit)
  - wiki/nodes/quality_gate.py  (soft heal)
  - wiki/nodes/finalize.py      (hard reject / sanitize)
  - wiki/page_agent.py          (post-generation cleanup)
"""

from __future__ import annotations

import re

_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")

# ---------------------------------------------------------------------------
# Hallucination detection
# ---------------------------------------------------------------------------

HALLUCINATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fabricated_percentage", re.compile(r"\d+\.\d+%")),
    ("fabricated_round_percentage", re.compile(r"\b\d{2,3}%")),
    ("fabricated_latency_sla", re.compile(r"(?:P\d{2}|SLA|RTO|RPO)\s*[<≤≥>]\s*\d")),
    ("fabricated_trend", re.compile(r"[↑↓+\-]\s*\d+\.?\d*\s*%")),
    ("fabricated_sla", re.compile(r"[≤<>≥]\s*\d+\s*(?:ms|秒|s)\b")),
    ("fabricated_availability", re.compile(r"\d+\.9{2,}%")),
    ("narrative_date", re.compile(r"\d{4}-\d{2}-\d{2}")),
    ("fabricated_tech_roadmap", re.compile(r"GNN|\b联邦学习|LSTM|Transformer|GDPR")),
    ("fabricated_timeline", re.compile(r"Phase\s+\d|\d+-\d+个月")),
    ("meta_self_reference", re.compile(r"中文字符占比|字符比例")),
    ("fabricated_scenario", re.compile(r"共同采购|节日准备|婚恋平台")),
]


def detect_hallucination_flags(content: str) -> list[str]:
    """Return list of hallucination flag names found in *prose* (code blocks excluded)."""
    if not content:
        return []
    text = _CODE_FENCE_RE.sub("", content)
    flags: list[str] = []
    seen: set[str] = set()
    for name, pattern in HALLUCINATION_PATTERNS:
        if name not in seen and pattern.search(text):
            flags.append(name)
            seen.add(name)
    return flags


# ---------------------------------------------------------------------------
# Boilerplate detection
# ---------------------------------------------------------------------------

BOILERPLATE_PHRASES: list[str] = [
    "高内聚",
    "低耦合",
    "显著提升",
    "核心价值在于",
    "分层架构设计",
    "充分体现",
    "架构设计遵循",
    "可维护性和可扩展性",
]


def count_boilerplate_hits(content: str) -> int:
    """Count total boilerplate phrase occurrences in prose (code blocks excluded)."""
    if not content:
        return 0
    text = _CODE_FENCE_RE.sub("", content)
    total = 0
    for phrase in BOILERPLATE_PHRASES:
        total += len(re.findall(re.escape(phrase), text))
    return total


def boilerplate_ratio(content: str) -> float:
    """Ratio of boilerplate hits to total Chinese characters."""
    if not content:
        return 0.0
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", content))
    if cn_chars == 0:
        return 0.0
    hits = count_boilerplate_hits(content)
    avg_phrase_len = sum(len(p) for p in BOILERPLATE_PHRASES) / len(BOILERPLATE_PHRASES)
    return (hits * avg_phrase_len) / cn_chars


# ---------------------------------------------------------------------------
# Meta-section detection & stripping
# ---------------------------------------------------------------------------

META_H2_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^##\s*改进建议"),
    re.compile(r"^##\s*优化方向"),
    re.compile(r"^##\s*中文术语表"),
    re.compile(r"^##\s*术语对照"),
    re.compile(r"^##\s*总结与展望"),
    re.compile(r"^##\s*建议$"),
    re.compile(r"^##\s*章节导航"),
    re.compile(r"^##\s*Section Navigation"),
    re.compile(r"^##\s*待完善项"),
    re.compile(r"^##\s*待完善与风险提示"),
    re.compile(r"^##\s*补充说明"),
    re.compile(r"^##\s*中文说明补充"),
    re.compile(r"^##\s*CONTEXT_GAP"),
    re.compile(r"^##\s*中英对照"),
    re.compile(r"^##\s*术语表（中英对照）"),
    re.compile(r"^##\s*术语表$"),
    re.compile(r"^##\s*.*(?:增强建议|使用建议|完善建议)$"),
    re.compile(r"^##\s*中文.*建议"),
    re.compile(r"^##\s*术语使用建议"),
    re.compile(r"^##\s*中文内容增强"),
    re.compile(r"^##\s*术语补充说明"),
    re.compile(r"^##\s*内容增强建议"),
]


def has_meta_sections(content: str) -> bool:
    """Return True if content contains LLM self-prompt meta sections."""
    if not content:
        return False
    for line in content.split("\n"):
        if any(p.match(line) for p in META_H2_PATTERNS):
            return True
    return False


def strip_meta_sections(content: str) -> str:
    """Remove meta H2 sections from content, preserving everything else."""
    if not content:
        return ""
    lines = content.split("\n")
    result: list[str] = []
    skipping = False

    for line in lines:
        is_h2 = line.startswith("## ")
        if is_h2:
            if any(p.match(line) for p in META_H2_PATTERNS):
                skipping = True
                continue
            else:
                skipping = False
        if not skipping:
            result.append(line)

    return "\n".join(result)


# ---------------------------------------------------------------------------
# H1 title stripping
# ---------------------------------------------------------------------------

_H1_LINE_RE = re.compile(r"^# .+\n?")


def strip_h1_title(content: str | None) -> str:
    """Remove a leading H1 title line when it appears outside fenced code blocks."""
    if not content:
        return ""
    stripped = content.lstrip("\n ")
    if stripped.startswith("```"):
        return content
    if not _H1_LINE_RE.match(stripped):
        return content
    first_line = stripped.split("\n", 1)[0]
    if first_line.startswith("## ") or not first_line.startswith("# "):
        return content
    remainder = stripped[len(first_line) :]
    if remainder.startswith("\n"):
        remainder = remainder[1:]
    return remainder


# ---------------------------------------------------------------------------
# Blockquote deduplication & LLM trace removal
# ---------------------------------------------------------------------------

_LLM_TRACE_BLOCKQUOTE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^>\s*\*\*Overview\*\*："),
    re.compile(r"^>\s*\*\*说明\*\*：为提升中文读者理解"),
    re.compile(r"^>\s*本页内容已强化中文表达"),
    re.compile(r"^>\s*术语说明：为提升中文读者理解"),
    re.compile(r"^>\s*\*\*术语使用建议\*\*[：:]"),
    re.compile(r"^>\s*\*\*建议\*\*[：:]"),
    re.compile(r"^>\s*建议[：:]"),
    re.compile(r"^>\s*\*\*说明\*\*[：:]"),
    re.compile(r"^>\s*术语说明[：:]"),
    re.compile(r"^>\s*\*\*Overview\*\*[：:]"),
    re.compile(r"^>\s*注[：:]本页技术"),
]

_ENGLISH_SELF_REFLECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^>\s*\*\*Note\*\*:\s*The headings", re.IGNORECASE),
    re.compile(r"^>\s*This section is", re.IGNORECASE),
    re.compile(r"^>\s*The following.*(?:placeholder|overview)", re.IGNORECASE),
]


def _is_blockquote_line(line: str) -> bool:
    return line.startswith("> ")


def _normalize_blockquote(line: str) -> str:
    return line[2:].strip()


def _is_llm_trace_blockquote(line: str) -> bool:
    return any(p.search(line) for p in _LLM_TRACE_BLOCKQUOTE_PATTERNS)


def strip_repeated_blockquotes(content: str | None) -> str:
    """Remove LLM trace blockquotes — entire contiguous block, not just the matching line."""
    if not content:
        return ""
    lines = content.split("\n")
    result: list[str] = []
    prev_blockquote: str | None = None
    skip_block = False

    for line in lines:
        if _is_llm_trace_blockquote(line):
            skip_block = True
            prev_blockquote = None
            continue
        if skip_block:
            if _is_blockquote_line(line):
                continue
            else:
                skip_block = False
        if _is_blockquote_line(line):
            normalized = _normalize_blockquote(line)
            if prev_blockquote is not None and normalized == prev_blockquote:
                continue
            prev_blockquote = normalized
            result.append(line)
            continue
        prev_blockquote = None
        result.append(line)

    return "\n".join(result)


def strip_english_self_reflection(content: str | None) -> str:
    """Remove English LLM self-reflection blockquote lines."""
    if not content:
        return ""
    lines = content.split("\n")
    result: list[str] = []
    for line in lines:
        if any(p.search(line) for p in _ENGLISH_SELF_REFLECTION_PATTERNS):
            continue
        result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Code fence deduplication
# ---------------------------------------------------------------------------

_FENCE_BLOCK_RE = re.compile(r"```[\w]*\n[\s\S]*?```")


def dedup_code_fences(content: str | None) -> str:
    """Remove duplicate fenced code blocks, keeping only the first occurrence."""
    if not content:
        return ""
    seen: set[str] = set()

    def _replace(match: re.Match[str]) -> str:
        block = match.group(0)
        if block in seen:
            return ""
        seen.add(block)
        return block

    result = _FENCE_BLOCK_RE.sub(_replace, content)
    return re.sub(r"\n{3,}", "\n\n", result)


# ---------------------------------------------------------------------------
# CN ratio
# ---------------------------------------------------------------------------


def compute_cn_ratio(content: str) -> float:
    """Compute Chinese character ratio, stripping fenced code blocks first."""
    text = _CODE_FENCE_RE.sub("", content)
    if len(text) < 10:
        return 1.0 if any("\u4e00" <= c <= "\u9fff" for c in text) else 0.0
    cn_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cn_count / len(text) if text else 0.0


# ---------------------------------------------------------------------------
# Code block integrity
# ---------------------------------------------------------------------------

_EMPTY_CODE_BLOCK_RE = re.compile(r"```\w*\s*\n\s*```")
_EMPTY_WIKILINK_RE = re.compile(r"\[\[\s*\]\]")
_DOUBLE_FENCE_RE = re.compile(
    r"(```\w*)\s*\n\s*\n\s*(```\w*\n)",
)


def count_empty_code_blocks(content: str) -> int:
    """Count empty code blocks (``` with no content)."""
    return len(_EMPTY_CODE_BLOCK_RE.findall(content))


def repair_code_fences(content: str) -> str:
    """Remove empty code blocks, empty WikiLinks, and merge double fences."""
    content = _DOUBLE_FENCE_RE.sub(r"\1\n", content)
    content = _EMPTY_CODE_BLOCK_RE.sub("", content)
    content = _EMPTY_WIKILINK_RE.sub("", content)
    content = re.sub(r"\n{4,}", "\n\n\n", content)
    return content.strip()


# ---------------------------------------------------------------------------
# H2 trailing whitespace
# ---------------------------------------------------------------------------


def strip_h2_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from H2 headings: '## 概述  ' → '## 概述'."""
    if not content:
        return ""
    return re.sub(r"^(## .+?)[ \t]+$", r"\1", content, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Topic overview section detection
# ---------------------------------------------------------------------------

_TOPIC_OVERVIEW_H2_RE = re.compile(r"^##\s*(?:概述|Overview|业务概述)\s*$", re.MULTILINE)


def has_topic_overview_section(content: str) -> bool:
    """Return True if content has a topic overview H2 (## 概述 / ## Overview / ## 业务概述)."""
    if not content:
        return False
    return _TOPIC_OVERVIEW_H2_RE.search(content) is not None


# ---------------------------------------------------------------------------
# H2 whitelist section cleanup
# ---------------------------------------------------------------------------

ALLOWED_OVERVIEW_H2_PREFIXES: tuple[str, ...] = (
    "概述",
    "核心业务流程",
    "核心模块",
    "模块详解",
    "依赖关系",
    "子域职责矩阵",
    "跨子域协作",
    "核心数据流",
    "子域导航",
    "Overview",
    "Core Business",
    "Core Modules",
    "Module Detail",
    "Dependencies",
    "Sub-Domain",
    "Cross Sub-Domain",
    "Core Data Flow",
    "重要约束",
    "语言规范",
)

ALLOWED_TOPIC_H2_PREFIXES: tuple[str, ...] = (
    "概述",
    "架构设计",
    "核心流程",
    "关键实现",
    "相关主题",
    "Overview",
    "Architecture",
    "Core Flow",
    "Key Implementation",
    "Related Topic",
    "语言约束",
)


def _h2_title_allowed(title: str, allowed_prefixes: tuple[str, ...]) -> bool:
    """Check if an H2 title matches any allowed prefix."""
    title_stripped = title.strip()
    return any(title_stripped.startswith(prefix) for prefix in allowed_prefixes)


def strip_unauthorized_sections(
    content: str | None,
    allowed_prefixes: tuple[str, ...],
) -> str:
    """Remove H2 sections whose title doesn't match any allowed prefix.

    Content before the first H2 is always preserved. H3+ subsections
    within allowed H2 sections are preserved.
    """
    if not content:
        return ""
    lines = content.split("\n")
    result: list[str] = []
    skipping = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            h2_title = stripped[3:].strip()
            if _h2_title_allowed(h2_title, allowed_prefixes):
                skipping = False
            else:
                skipping = True
                continue
        if not skipping:
            result.append(line)

    return "\n".join(result)


_FENCE_LINE_RE = re.compile(r"^( {0,3})?```")
_BARE_CLOSE_FENCE_RE = re.compile(r"^```\s*$")


def _is_fence_line(line: str) -> bool:
    """True for markdown fenced-code delimiter lines (0–3 leading spaces)."""
    return bool(_FENCE_LINE_RE.match(line))


def _count_unclosed_fence_blocks(content: str) -> int:
    """Count closing fences missing at EOF after line-by-line fence tracking."""
    depth = 0
    in_fence = False
    open_lang = ""

    for line in content.split("\n"):
        if not _is_fence_line(line):
            continue
        stripped = line.strip()
        if _BARE_CLOSE_FENCE_RE.match(stripped):
            if in_fence:
                in_fence = False
                open_lang = ""
                depth = max(0, depth - 1)
            continue
        if not stripped.startswith("```"):
            continue
        lang = stripped[3:].strip()
        if not in_fence:
            in_fence = True
            open_lang = lang
            depth += 1
        elif lang and lang == open_lang:
            in_fence = False
            open_lang = ""
            depth = max(0, depth - 1)
        else:
            open_lang = lang
            depth += 1

    return depth if in_fence else 0


def detect_truncated_code_blocks(content: str | None) -> list[dict]:
    """Detect unclosed code fences indicating truncated code blocks."""
    if not content:
        return []
    truncated: list[dict] = []
    in_fence = False
    fence_start_line = 0
    fence_lang = ""
    open_lang = ""

    for i, line in enumerate(content.split("\n")):
        if not _is_fence_line(line):
            continue
        stripped = line.strip()
        if _BARE_CLOSE_FENCE_RE.match(stripped):
            if in_fence:
                in_fence = False
                open_lang = ""
            continue
        if not stripped.startswith("```"):
            continue
        lang = stripped[3:].strip()
        if not in_fence:
            in_fence = True
            open_lang = lang
            fence_start_line = i
            fence_lang = lang
        elif lang and lang == open_lang:
            in_fence = False
            open_lang = ""
        else:
            open_lang = lang
            fence_start_line = i
            fence_lang = lang

    if in_fence:
        truncated.append(
            {
                "start_line": fence_start_line,
                "language": fence_lang,
                "unclosed": True,
            }
        )
    return truncated


def detect_unclosed_code_blocks(content: str) -> bool:
    """Detect if content has unclosed fenced code blocks."""
    if not content:
        return False
    return _count_unclosed_fence_blocks(content) > 0


def repair_unclosed_code_blocks(content: str) -> str:
    """Close unclosed fenced code blocks by appending closing fences."""
    if not content:
        return content
    closes_needed = _count_unclosed_fence_blocks(content)
    if closes_needed == 0:
        return content
    return content.rstrip() + "\n" + ("```\n" * closes_needed)


def repair_truncated_code_blocks(content: str) -> str:
    """Close truncated code blocks detected by ``detect_truncated_code_blocks``."""
    if not content or not detect_truncated_code_blocks(content):
        return content
    return repair_unclosed_code_blocks(content)


def sanitize_content(content: str | None) -> str:
    """Run standard content sanitization (H2 whitespace, etc.)."""
    if not content:
        return ""
    return strip_h2_trailing_whitespace(content)


# ---------------------------------------------------------------------------
# CJK title similarity (bigram overlap)
# ---------------------------------------------------------------------------


def _extract_cjk_bigrams(title: str) -> set[str]:
    """Extract CJK character bigrams for fuzzy title matching."""
    chars = [c for c in title if "\u4e00" <= c <= "\u9fff"]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def cjk_bigram_similarity(a: str, b: str) -> float:
    """Return Jaccard-like bigram overlap ratio in ``[0.0, 1.0]``."""
    bigrams_a = _extract_cjk_bigrams(a)
    bigrams_b = _extract_cjk_bigrams(b)
    if not bigrams_a and not bigrams_b:
        return 1.0 if a == b else 0.0
    if not bigrams_a or not bigrams_b:
        return 0.0
    return len(bigrams_a & bigrams_b) / max(len(bigrams_a), len(bigrams_b), 1)
