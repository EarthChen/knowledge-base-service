"""Finalize node for wiki pipeline."""

from __future__ import annotations

import re
from typing import Any

from core.log import get_logger
from wiki.content_guards import (
    apply_compound_title_fallback,
    cjk_bigram_similarity,
    compute_cn_ratio,
    dedup_code_fences,
    derive_semantic_title,
    detect_hallucination_flags,
    is_compound_module_title,
    repair_code_fences,
    repair_truncated_code_blocks,
    repair_unclosed_code_blocks,
    strip_english_self_reflection,
    strip_h1_title,
    strip_meta_sections,
    strip_repeated_blockquotes,
)

log = get_logger(__name__)

_MIN_PAGE_CHARS = 200


def _get_overview_reject_threshold() -> int:
    """Get minimum chars threshold for domain overview rejection."""
    from core.config import get_settings

    return get_settings().wiki.overview_min_content_chars

_FAKE_SOURCE_RE = re.compile(r"com/xxx/")
_SOURCE_PROTOCOL_RE = re.compile(r"source://[^\s)>\]]+", re.IGNORECASE)
_CODE_REF_COMMENT_RE = re.compile(r"<!--\s*(?:CODE_REF|UNVERIFIED_CODE)\s*:?.*?-->", re.DOTALL)
_INTERNAL_URL_RE = re.compile(
    r"https?://(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|internal\.|localhost)\S*",
    re.IGNORECASE,
)
_CREDENTIAL_RE = re.compile(r"((?:password|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*)\S+", re.IGNORECASE)
_EMPTY_CODE_BLOCK_RE = re.compile(r"```\w*\n\s*```")
_EMPTY_WIKILINK_RE = re.compile(r"\[\[\s*\]\]")
_INJECTED_REF_RE = re.compile(r"<!-- __INJECTED_CODE_REF__[^>]* -->")
_EXCESS_NEWLINES_RE = re.compile(r"\n{4,}")
_ENGLISH_OVERVIEW_RE = re.compile(
    r"^>\s*\*\*Overview\*\*\s*:.*?(?=\n(?!\s*>)|\n##|\Z)",
    re.DOTALL | re.MULTILINE,
)
_REDACT_PATTERNS = [
    (_INTERNAL_URL_RE, "[INTERNAL_URL]"),
    (_CREDENTIAL_RE, r"\1[REDACTED]"),
]


def _strip_quality_checklist_tables(content: str) -> str:
    lines = content.split("\n")
    result: list[str] = []
    in_table = False
    table_has_emoji = False
    table_buf: list[str] = []
    for line in lines:
        is_table_line = line.strip().startswith("|")
        if is_table_line:
            if not in_table:
                in_table = True
                table_has_emoji = False
                table_buf = []
            table_buf.append(line)
            if any(e in line for e in ("✅", "⚠️", "❌")):
                table_has_emoji = True
        else:
            if in_table:
                in_table = False
                if not table_has_emoji:
                    result.extend(table_buf)
            result.append(line)
    if in_table and not table_has_emoji:
        result.extend(table_buf)
    return "\n".join(result)


def _strip_fake_source_lines(content: str) -> str:
    lines = content.split("\n")
    result: list[str] = []
    in_code_block = False
    code_block_has_fake = False
    code_buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                if stripped == "```":
                    code_buf.append(line)
                    in_code_block = False
                    if not code_block_has_fake:
                        result.extend(code_buf)
                    code_buf = []
                else:
                    code_buf.append(line)
                    if _FAKE_SOURCE_RE.search(line):
                        code_block_has_fake = True
            else:
                in_code_block = True
                code_block_has_fake = False
                code_buf = [line]
            continue
        if in_code_block:
            code_buf.append(line)
            if _FAKE_SOURCE_RE.search(line):
                code_block_has_fake = True
        elif not _FAKE_SOURCE_RE.search(line):
            result.append(line)
    if code_buf and not code_block_has_fake:
        result.extend(code_buf)
    return "\n".join(result)


def _sanitize_published_content(content: str, *, page_type: str = "") -> str:
    """Remove internal pipeline artifacts from published content."""
    # 1. Remove CONTEXT_GAP HTML comments
    content = re.sub(r"<!--\s*CONTEXT_GAP:.*?-->", "", content, flags=re.DOTALL)

    # 2. Remove CONTEXT_GAP text markers
    content = re.sub(r"\[CONTEXT_GAP:.*?\]", "", content, flags=re.DOTALL)

    # 3. Remove redacted thinking tags
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

    # 4. Remove quality checklist tables with emoji
    content = _strip_quality_checklist_tables(content)

    # 5. Remove fake source path lines/blocks
    content = _strip_fake_source_lines(content)

    # 5.5. Remove source:// protocol links
    content = _SOURCE_PROTOCOL_RE.sub("", content)

    # 5.6. Remove CODE_REF / UNVERIFIED_CODE HTML comments
    content = _CODE_REF_COMMENT_RE.sub("", content)

    # 5.7. Remove [undefined] text markers
    content = re.sub(r"\[undefined\]", "", content)

    # 6. Deduplicate consecutive identical headings (keep first occurrence + content)
    lines = content.split("\n")
    result = []
    prev_heading = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped == prev_heading:
                continue
            prev_heading = stripped
        else:
            if stripped:
                prev_heading = None
        result.append(line)
    content = "\n".join(result)

    # 7. Close unclosed code blocks (safety net after quality_gate heal cycles)
    content = repair_unclosed_code_blocks(content)
    content = repair_truncated_code_blocks(content)

    # 8. Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    for pattern, replacement in _REDACT_PATTERNS:
        content = pattern.sub(replacement, content)

    # V9 content guards (F10): ordered sanitize pipeline
    content = strip_h1_title(content)
    content = strip_meta_sections(content)
    content = strip_repeated_blockquotes(content)
    content = dedup_code_fences(content)
    content = strip_english_self_reflection(content)
    # Repair code fences (remove empty blocks, empty wikilinks)
    content = repair_code_fences(content)

    # H2 whitelist cleanup (after all other sanitization)
    if page_type == "domain_overview":
        from wiki.content_guards import ALLOWED_OVERVIEW_H2_PREFIXES, strip_unauthorized_sections

        content = strip_unauthorized_sections(content, ALLOWED_OVERVIEW_H2_PREFIXES)
    elif page_type == "topic":
        from wiki.content_guards import ALLOWED_TOPIC_H2_PREFIXES, strip_unauthorized_sections

        content = strip_unauthorized_sections(content, ALLOWED_TOPIC_H2_PREFIXES)

    return content.strip()


def _sanitize_render_issues(content: str) -> str:
    """Remove empty code blocks, empty wikilinks, injection residuals."""
    content = _EMPTY_CODE_BLOCK_RE.sub("", content)
    content = _EMPTY_WIKILINK_RE.sub("", content)
    content = _INJECTED_REF_RE.sub("", content)
    content = _EXCESS_NEWLINES_RE.sub("\n\n\n", content)
    return content.strip()


def _dedup_h2_sections(content: str) -> str:
    """Deduplicate H2 sections with identical titles; keep the last occurrence."""
    lines = content.split("\n")
    h2_indices: list[int] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            h2_indices.append(i)

    if not h2_indices:
        return content

    sections: list[tuple[int, int, str]] = []
    for idx, start in enumerate(h2_indices):
        end = h2_indices[idx + 1] if idx + 1 < len(h2_indices) else len(lines)
        h2_title = lines[start].strip()
        sections.append((start, end, h2_title))

    title_last: dict[str, int] = {}
    for i, (_, _, title) in enumerate(sections):
        title_last[title] = i

    to_remove = {i for i, (_, _, title) in enumerate(sections) if title_last[title] != i}

    if not to_remove:
        return content

    pre_section = lines[: h2_indices[0]] if h2_indices else []
    new_lines = list(pre_section)
    for i, (start, end, _) in enumerate(sections):
        if i not in to_remove:
            new_lines.extend(lines[start:end])

    return "\n".join(new_lines)


def _sanitize_english_overview(content: str) -> str:
    """Remove English-dominant Overview blockquote."""
    match = _ENGLISH_OVERVIEW_RE.search(content)
    if match:
        text = match.group(0)
        cn_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        if cn_chars / max(len(text), 1) < 0.15:
            content = content[: match.start()] + content[match.end() :]
    return content


def _extract_class_references(content: str) -> set[str]:
    """Extract backtick-quoted class names from content."""
    return set(
        re.findall(
            r"`([A-Z][a-zA-Z0-9]*(?:Service|Controller|Handler|Impl|Wrapper|Provider|Factory|Repository|Dao|Mapper|Config|Manager|Helper|Util|Builder|Adapter|Proxy|Listener|Filter|Interceptor))`",
            content,
        )
    )


def _wikilink_target_is_valid(target: str, valid_lower: set[str]) -> bool:
    """True when target exactly matches or is a known short-title variant of a page title."""
    t = target.strip().lower()
    if not t or not valid_lower:
        return False
    if t in valid_lower:
        return True
    min_suffix_len = 4
    for v in valid_lower:
        if v.endswith(t) and len(t) >= min_suffix_len:
            return True
        if "/" in v and v.split("/")[-1] == t:
            return True
    return False


def _remove_invalid_wikilinks(content: str, valid_targets: set[str]) -> str:
    """Remove wikilinks pointing to non-existent pages."""
    valid_lower = {t.lower() for t in valid_targets if t}

    def replace_link(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        return m.group(0) if _wikilink_target_is_valid(target, valid_lower) else target

    return re.sub(r"\[\[([^\]]+)\]\]", replace_link, content)


_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
_FABRICATED_PERCENT_RE = re.compile(r"[↑↓+\-]\s*\d+\.?\d*\s*%")
_FABRICATED_SLA_RE = re.compile(r"(?:SLA|P\d{2}|RTO|RPO)\s*[<≤≥>]\s*\d")
_NARRATIVE_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FABRICATED_TECH_ROADMAP_RE = re.compile(r"GNN|\b联邦学习|LSTM|Transformer|GDPR")
_FABRICATED_TIMELINE_RE = re.compile(r"Phase\s+\d|\d+-\d+个月")
_META_SELF_REFERENCE_RE = re.compile(r"中文字符占比|字符比例")
_FABRICATED_SCENARIO_RE = re.compile(r"共同采购|节日准备|婚恋平台")


def _strip_code_fences(content: str) -> str:
    return _CODE_FENCE_RE.sub("", content)


def _detect_hallucination_patterns(content: str) -> list[str]:
    """Flag fabricated metrics, SLA claims, and narrative dates outside code blocks."""
    text = _strip_code_fences(content)
    flags: list[str] = []
    if _FABRICATED_PERCENT_RE.search(text):
        flags.append("fabricated_percentage")
    if _FABRICATED_SLA_RE.search(text):
        flags.append("fabricated_sla")
    if _NARRATIVE_DATE_RE.search(text):
        flags.append("narrative_date")
    if _FABRICATED_TECH_ROADMAP_RE.search(text):
        flags.append("fabricated_tech_roadmap")
    if _FABRICATED_TIMELINE_RE.search(text):
        flags.append("fabricated_timeline")
    if _META_SELF_REFERENCE_RE.search(text):
        flags.append("meta_self_reference")
    if _FABRICATED_SCENARIO_RE.search(text):
        flags.append("fabricated_scenario")
    return flags


def _compute_cn_ratio(content: str) -> float:
    """Estimate Chinese character ratio, stripping fenced code blocks first."""
    text = _CODE_FENCE_RE.sub("", content)
    if len(text) < 100:
        return 1.0
    cn_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cn_count / len(text) if text else 0.0


_ENGLISH_TO_CHINESE_HEADINGS: dict[str, str] = {
    "## Overview": "## 概述",
    "## Architecture": "## 架构设计",
    "## Key Components": "## 核心组件",
    "## Key components": "## 核心组件",
    "## Key components and methods": "## 核心组件与方法",
    "## Component Relationships": "## 组件关系",
    "## Component relationships": "## 组件关系",
    "## Data Flow": "## 数据流",
    "## Data flow": "## 数据流",
    "## Implementation Details": "## 实现细节",
    "## Implementation details": "## 实现细节",
    "## Usage": "## 使用方式",
    "## Configuration": "## 配置",
    "## Dependencies": "## 依赖关系",
    "## API Reference": "## API 参考",
    "## Error Handling": "## 错误处理",
    "## Testing": "## 测试",
    "## Performance": "## 性能",
    "## Security": "## 安全",
    "### Overview": "### 概述",
    "### Architecture": "### 架构设计",
    "### Key Components": "### 核心组件",
    "### Key components": "### 核心组件",
    "### Implementation Details": "### 实现细节",
    "### Implementation details": "### 实现细节",
}


def _normalize_headings_to_chinese(content: str) -> str:
    """Replace common English H2/H3 headings with Chinese equivalents."""
    if not content:
        return content
    lines = content.split("\n")
    result: list[str] = []
    in_code_fence = False
    for line in lines:
        if line.startswith("```"):
            in_code_fence = not in_code_fence
        if not in_code_fence:
            for eng, chn in _ENGLISH_TO_CHINESE_HEADINGS.items():
                if line.strip() == eng or line == eng:
                    line = chn
                    break
        result.append(line)
    return "\n".join(result)


def _is_chinese_lang(lang: str) -> bool:
    return lang.lower() in ("zh", "zh-cn", "zh-tw", "chinese", "简体中文", "繁體中文", "zh-hans")


def _resolve_page_content_language(page: dict[str, Any], state: dict[str, Any]) -> str:
    lang = str(page.get("content_language") or "")
    if not lang:
        meta = page.get("metadata") or {}
        if isinstance(meta, dict):
            lang = str(meta.get("content_language") or "")
    if not lang:
        cfg = state.get("config") or {}
        lang = str(cfg.get("content_language") or "")
    return lang


_STUB_PLACEHOLDER_RE = re.compile(
    r"(?:\bTODO\b|\bTBD\b|\bFIXME\b|待补充|待完善|占位|placeholder)",
    re.IGNORECASE,
)


def _heading_line_ratio(content: str) -> float:
    """Fraction of non-empty lines that are markdown headings."""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    heading_count = sum(1 for ln in lines if re.match(r"^#{1,6}\s", ln))
    return heading_count / len(lines)


def _detect_stub_topic(content: str, *, raw_len: int, wiki: Any) -> tuple[bool, str]:
    """Return (is_stub, reason) for topic publish rejection."""
    min_publish = wiki.topic_min_publish_chars
    if raw_len < min_publish:
        return True, "min_chars"

    heading_max = getattr(wiki, "topic_stub_heading_ratio_max", 0.5)
    if not isinstance(heading_max, (int, float)):
        heading_max = 0.5
    ratio = _heading_line_ratio(content)
    if ratio > heading_max:
        return True, "heading_ratio"

    if _STUB_PLACEHOLDER_RE.search(content):
        return True, "placeholder"

    return False, ""


def _rewrite_part_n_title(title: str, content: str) -> str:
    """Rewrite 'DomainName - Part N' titles with content-based semantic title."""
    if not re.search(r"- Part \d+$", title):
        return title
    h2_match = re.search(r"^## (.+)", content, re.MULTILINE)
    if h2_match:
        h2_title = h2_match.group(1).strip()
        if h2_title and h2_title not in ("概述", "Overview"):
            domain_prefix = title.rsplit(" - Part", 1)[0]
            return f"{domain_prefix} - {h2_title}"
    return title


def _rewrite_compound_title(
    title: str,
    page: dict,
    content: str,
    state: dict | None = None,
) -> str:
    """Rewrite repo/path|ClassName compound keys into human-readable titles."""
    if not is_compound_module_title(title):
        return title
    meta = page.get("metadata") or {}
    covered = meta.get("covered_modules") or []
    modules = [str(m) for m in covered if m] if covered else [title]
    state = state or {}
    domain_slug = str(page.get("business_domain") or _extract_domain_from_path(page.get("path", "")))
    display_names = state.get("domain_display_names") or {}
    domain_display = str(
        page.get("domain_display_name")
        or display_names.get(domain_slug, "")
        or domain_slug
    )
    summaries = state.get("module_summaries") or {}
    result = derive_semantic_title(modules, domain_display, summaries, content)
    primary = modules[0] if modules else title
    clean_name = primary.split("|", 1)[1] if "|" in primary else primary
    if is_compound_module_title(result) or "|" in result:
        result = apply_compound_title_fallback(clean_name, domain_display)
    return result or apply_compound_title_fallback(clean_name, domain_display)


def _get_skeleton_threshold(page_type: str = "domain_overview") -> int:
    from core.config import get_settings

    if page_type == "topic":
        return get_settings().wiki.topic_min_content_chars
    return get_settings().wiki.overview_min_content_chars


def _extract_domain_from_path(path: str) -> str:
    """Extract domain slug from a wiki page path."""
    if not path:
        return ""
    parts = path.strip("/").split("/")
    if parts and parts[0] == "__domains__" and len(parts) >= 2:
        return parts[1]
    if parts and parts[0] == "wiki" and len(parts) >= 3:
        return parts[2]
    return ""


_PAGE_TYPE_LABELS: dict[str, str] = {
    "domain_overview": "概览",
    "topic": "专题",
}

_NEAR_DUP_SIMILARITY_THRESHOLD = 0.8
_MAX_TITLE_LEN = 50
_KEBAB_SLUG_TOKEN_RE = re.compile(r"[a-z]+(?:-[a-z]+)+")
_TITLE_EXPOSED_SLUG_RE = re.compile(r"[a-z]+-[a-z]+")


def _page_domain(page: dict) -> str:
    return str(page.get("business_domain", "") or _extract_domain_from_path(page.get("path", "")))


def _page_type_label(page: dict) -> str:
    page_type = str(page.get("page_type", "") or "")
    return _PAGE_TYPE_LABELS.get(page_type, page_type)


def _path_topic_slug(path: str) -> str:
    """Extract a human-readable slug from a wiki page path."""
    if not path:
        return ""
    parts = [part for part in path.strip("/").split("/") if part and not part.startswith("_")]
    if "topics" in parts:
        topic_idx = parts.index("topics")
        if topic_idx + 1 < len(parts):
            return parts[topic_idx + 1]
    return parts[-1] if parts else ""


def _humanize_path_segment(segment: str) -> str:
    """Turn a path module segment into a short human-readable label."""
    if not segment:
        return ""
    if re.search(r"[\u4e00-\u9fff]", segment):
        return segment.strip()
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", segment)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    if re.fullmatch(r"[a-z0-9-]+", spaced) and "-" in spaced:
        if _KEBAB_SLUG_TOKEN_RE.fullmatch(spaced):
            return spaced.split("-")[-1]
        return spaced.replace("-", " ")
    return spaced.strip()


def _path_module_label(path: str) -> str:
    """Module-name suffix candidate from the last meaningful path segment."""
    slug = _path_topic_slug(path)
    if not slug:
        return ""
    return _sanitize_title_suffix(_humanize_path_segment(slug))


def _sanitize_title_suffix(suffix: str) -> str:
    """Drop kebab-case slugs and page-type labels from a title suffix fragment."""
    if not suffix:
        return ""
    page_type_labels = set(_PAGE_TYPE_LABELS.values())
    kept: list[str] = []
    for part in suffix.split("·"):
        token = part.strip()
        if not token:
            continue
        if token in page_type_labels:
            continue
        if _KEBAB_SLUG_TOKEN_RE.fullmatch(token) or _KEBAB_SLUG_TOKEN_RE.search(token):
            continue
        kept.append(token)
    return "·".join(kept)


def _title_has_exposed_slug(title: str) -> bool:
    """True when a user-visible title still contains a kebab-case slug fragment."""
    return bool(_TITLE_EXPOSED_SLUG_RE.search(title))


def _truncate_title(title: str, *, max_len: int = _MAX_TITLE_LEN) -> str:
    if len(title) <= max_len:
        return title
    return title[: max_len - 3] + "…）"


def _title_with_suffix(base: str, *parts: str) -> str:
    suffix_parts = [_sanitize_title_suffix(part) for part in parts if part]
    suffix_parts = [part for part in suffix_parts if part]
    if not suffix_parts:
        return base
    return _truncate_title(f"{base}（{'·'.join(suffix_parts)}）")


_GENERIC_H2_TITLES = frozenset({
    "概述", "总结", "简介", "背景", "参考", "引用",
    "Overview", "Summary", "Introduction", "Background", "References",
})


def _extract_first_h2_theme(page: dict) -> str:
    """Extract the first non-generic H2 heading as a thematic label."""
    content = page.get("content", "")
    if not content:
        return ""

    in_fence = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            if title and title not in _GENERIC_H2_TITLES:
                return title

    return ""


def _disambiguation_parts(page: dict, *, level: int, seq: int) -> tuple[str, ...]:
    h2_theme = _extract_first_h2_theme(page)
    if level == 0:
        return (h2_theme,) if h2_theme else ()
    if level == 1:
        return (str(seq),)
    parts = [part for part in (h2_theme, str(seq)) if part]
    return tuple(parts) if parts else (str(seq),)


def _candidate_titles_for_group(pages: list[dict], base_title: str, *, level: int) -> list[str]:
    candidates: list[str] = []
    for seq, page in enumerate(pages, start=1):
        parts = _disambiguation_parts(page, level=level, seq=seq)
        candidates.append(_title_with_suffix(base_title, *parts) if parts else base_title)
    return candidates


def _detect_near_duplicate_titles(pages: list[dict]) -> list[dict]:
    """Rename titles with high CJK bigram overlap (>= 0.8) against earlier pages."""
    result = [dict(page) for page in pages]
    used_titles = {page.get("title", "") for page in result if page.get("title")}

    for i, page in enumerate(result):
        title = str(page.get("title", "") or "")
        if not title:
            continue
        for j in range(i):
            other_title = str(result[j].get("title", "") or "")
            if not other_title or title == other_title:
                continue
            if cjk_bigram_similarity(title, other_title) < _NEAR_DUP_SIMILARITY_THRESHOLD:
                continue

            module_label = _path_module_label(page.get("path", ""))
            suffix_options = (
                [module_label] if module_label else [],
                [str(i + 1)],
            )
            new_title = title
            for parts in suffix_options:
                if not parts:
                    continue
                candidate = _title_with_suffix(title, *parts)
                if candidate not in used_titles:
                    new_title = candidate
                    break
            else:
                seq = 1
                while True:
                    candidate = _title_with_suffix(title, str(seq))
                    if candidate not in used_titles:
                        new_title = candidate
                        break
                    seq += 1

            result[i] = {**page, "title": new_title}
            used_titles.add(new_title)
            break

    return result


def _deduplicate_exact_titles(pages: list[dict]) -> list[dict]:
    """Resolve exact duplicate titles with progressive domain/type/numeric suffixes."""
    result = [dict(page) for page in pages]
    title_groups: dict[str, list[int]] = {}
    for index, page in enumerate(result):
        title = str(page.get("title", "") or "")
        title_groups.setdefault(title, []).append(index)

    for base_title, indices in title_groups.items():
        if len(indices) <= 1 or not base_title:
            continue

        group_pages = [result[index] for index in indices]
        for level in range(3):
            candidates = _candidate_titles_for_group(group_pages, base_title, level=level)
            if len(candidates) == len(set(candidates)):
                for index, new_title in zip(indices, candidates, strict=True):
                    result[index] = {**result[index], "title": new_title}
                break

    return result


def _ensure_title_uniqueness(pages: list[dict]) -> list[dict]:
    """Safety pass: force numeric suffixes until all titles are unique."""
    result = [dict(page) for page in pages]
    for _ in range(len(result) + 1):
        duplicates: dict[str, list[int]] = {}
        for index, page in enumerate(result):
            title = str(page.get("title", "") or "")
            if title:
                duplicates.setdefault(title, []).append(index)
        unresolved = {title: idxs for title, idxs in duplicates.items() if len(idxs) > 1}
        if not unresolved:
            return result

        for title, indices in unresolved.items():
            existing = {result[idx].get("title", "") for idx in range(len(result))}
            for seq, index in enumerate(indices, start=1):
                candidate = _title_with_suffix(title, str(seq))
                while candidate in existing:
                    seq += 1
                    candidate = _title_with_suffix(title, str(seq))
                result[index] = {**result[index], "title": candidate}
                existing.add(candidate)

    return result


_DISAMBIG_SUFFIX_RE = re.compile(r"^(.+?)（([a-z0-9][a-z0-9-]*)）$")


def _strip_disambiguation_suffixes(pages: list[dict]) -> list[dict]:
    """Remove domain-slug disambiguation suffixes when safe.

    Pattern: "标题（domain-slug）" → "标题" if unique after strip.
    """
    result = [dict(p) for p in pages]
    bases: dict[str, list[int]] = {}
    for i, page in enumerate(result):
        title = str(page.get("title", ""))
        m = _DISAMBIG_SUFFIX_RE.match(title)
        if m:
            bases.setdefault(m.group(1), []).append(i)

    for base, indices in bases.items():
        if len(indices) != 1:
            continue
        other_titles = [str(result[i].get("title", "")) for i in range(len(result)) if i not in set(indices)]
        if base in other_titles:
            continue
        idx = indices[0]
        result[idx] = {**result[idx], "title": base}

    return result


def _flag_titles_with_exposed_slugs(pages: list[dict]) -> list[dict]:
    """Mark pages whose final titles still expose kebab-case slug fragments."""
    result: list[dict] = []
    for page in pages:
        updated = dict(page)
        title = str(updated.get("title", "") or "")
        if _title_has_exposed_slug(title):
            flags = list(updated.get("quality_flags") or [])
            if "TITLE_HAS_SLUG" not in flags:
                flags.append("TITLE_HAS_SLUG")
            updated["quality_flags"] = flags
        result.append(updated)
    return result


def _deduplicate_titles(pages: list[dict]) -> list[dict]:
    """Ensure all page titles within a business are unique.

    Near-duplicates are renamed first, then exact duplicates receive
    H2-theme / module-name / numeric suffixes, with a final safety pass.
    """
    result = _detect_near_duplicate_titles(list(pages))
    result = _deduplicate_exact_titles(result)
    return _ensure_title_uniqueness(result)


async def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
    pages = list(state.get("pages", []))

    valid_targets: set[str] = set()
    for page in pages:
        title = page.get("title")
        path = page.get("path")
        bd = page.get("business_domain", "")
        if title:
            valid_targets.add(str(title).lower())
            if bd:
                valid_targets.add(f"{bd}/{title}".lower())
        if path:
            valid_targets.add(str(path).lower())
            parts = str(path).strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "__domains__":
                slug = parts[1]
                if title:
                    valid_targets.add(f"{slug}/{title}".lower())

    updated_pages: list[dict[str, Any]] = []
    for page in pages:
        content = page.get("content")
        raw_content_len = len(content) if content else 0
        page_path = page.get("path", "")
        if content:
            content_stripped = content.strip()
            gen_mode_early = page.get("metadata", {}).get("generation_mode", "")
            is_agent_error_overview = (
                page.get("page_type") == "domain_overview"
                and page.get("metadata", {}).get("overview_kind") != "topic_index"
                and gen_mode_early in ("agent_error", "error_fallback")
            )
            if len(content_stripped) < _MIN_PAGE_CHARS and not is_agent_error_overview:
                log.warning(
                    "page_too_short_rejected",
                    path=page_path,
                    chars=len(content_stripped),
                )
                updated_pages.append({**page, "content": "", "__rejected__": True})
                continue
        if content:
            page_type = ""
            if "/_topic" in page_path:
                page_type = "topic"
            elif page_path.startswith("/__domains__/"):
                page_type = "domain_overview"
            content = _sanitize_published_content(content, page_type=page_type)
            content = _sanitize_render_issues(content)
            content = _dedup_h2_sections(content)
            content = _sanitize_english_overview(content)
            content = _remove_invalid_wikilinks(content, valid_targets)

            content_language = _resolve_page_content_language(page, state)
            if _is_chinese_lang(content_language):
                content = _normalize_headings_to_chinese(content)

            is_topic_index = page.get("metadata", {}).get("overview_kind") == "topic_index"
            is_overview = page.get("page_type") == "domain_overview"
            is_topic = page.get("page_type") == "topic"

            if is_topic and not is_topic_index:
                from core.config import get_settings

                wiki_cfg = get_settings().wiki
                is_stub, stub_reason = _detect_stub_topic(
                    content,
                    raw_len=raw_content_len,
                    wiki=wiki_cfg,
                )
                if is_stub:
                    log.warning(
                        "stub_topic_rejected",
                        page_path=page.get("path"),
                        content_len=raw_content_len,
                        threshold=wiki_cfg.topic_min_publish_chars,
                        reason=stub_reason,
                        heading_ratio=round(_heading_line_ratio(content), 3)
                        if stub_reason == "heading_ratio"
                        else None,
                    )
                    updated_pages.append({**page, "content": "", "__rejected__": True})
                    continue

            page_quality_flags = page.get("quality_flags") or []
            if "FORCED_LOW_QUALITY" in page_quality_flags:
                lang = page.get("content_language", "")
                if lang and lang.lower() in ("en", "english", "en-us"):
                    banner = "> ⚠️ This domain documentation is incomplete and may contain gaps.\n\n"
                else:
                    banner = "> ⚠️ 本域文档待完善，内容可能不完整。\n\n"
                if not content.startswith(banner):
                    content = banner + content
                log.warning(
                    "forced_low_quality_banner",
                    page_path=page.get("path"),
                    quality_flags=page_quality_flags,
                )

            reject_threshold = _get_overview_reject_threshold()
            reject_hard_min = reject_threshold // 4
            gen_mode = page.get("metadata", {}).get("generation_mode", "")
            if is_overview and not is_topic_index and gen_mode in ("agent_error", "error_fallback"):
                # Agent-failed pages are not hard-rejected; they become degraded skeletons
                lang = page.get("content_language", "")
                if lang and lang.lower() in ("en", "english", "en-us"):
                    degraded_banner = "> ⚠️ This domain failed to generate and is awaiting retry.\n\n"
                else:
                    degraded_banner = "> ⚠️ 本域文档生成失败，等待重试。\n\n"
                if not content.startswith(degraded_banner):
                    content = degraded_banner + content
                page = {**page, "content": content, "__degraded__": True}
                log.warning(
                    "agent_error_page_kept_as_degraded",
                    page_path=page.get("path"),
                    gen_mode=gen_mode,
                    content_len=len(content),
                )
                updated_pages.append(page)
                continue
            if is_overview and not is_topic_index and len(content) < reject_hard_min:
                log.warning(
                    "shell_domain_rejected",
                    page_path=page.get("path"),
                    content_len=len(content),
                    threshold=reject_hard_min,
                )
                updated_pages.append({**page, "content": "", "__rejected__": True})
                continue

            threshold = _get_skeleton_threshold(page.get("page_type", ""))
            if (is_overview or is_topic) and len(content) < threshold and not is_topic_index:
                lang = page.get("content_language", "")
                if lang and lang.lower() in ("en", "english", "en-us"):
                    banner = "> ⚠️ This domain documentation is incomplete and may contain gaps.\n\n"
                else:
                    banner = "> ⚠️ 本域文档待完善，内容可能不完整。\n\n"
                log.warning(
                    "skeleton_page_detected",
                    page_path=page.get("path"),
                    content_len=len(content),
                )
                content = banner + content

            if is_topic and not is_topic_index:
                from core.config import get_settings

                content_language = _resolve_page_content_language(page, state)
                if _is_chinese_lang(content_language):
                    min_ratio = get_settings().wiki.cn_ratio_hard_min
                    cn_ratio = compute_cn_ratio(content)
                    if cn_ratio < min_ratio:
                        log.warning(
                            "low_cn_ratio_topic_rejected",
                            page_path=page.get("path"),
                            cn_ratio=round(cn_ratio, 3),
                            min_ratio=min_ratio,
                        )
                        updated_pages.append({**page, "content": "", "__rejected__": True})
                        continue

            if is_overview and not is_topic_index and _is_chinese_lang(content_language):
                cn_ratio = compute_cn_ratio(content)
                if cn_ratio < 0.15:
                    log.warning(
                        "overview_cn_ratio_rejected",
                        path=page.get("path"),
                        cn_ratio=cn_ratio,
                    )
                    updated_pages.append({**page, "content": "", "__rejected__": True})
                    continue

            if is_overview or is_topic:
                hallucination_flags = detect_hallucination_flags(content)
                if hallucination_flags:
                    lang = page.get("content_language", "")
                    if lang and lang.lower() in ("en", "english", "en-us"):
                        banner = "> ⚠️ This domain documentation is incomplete and may contain gaps.\n\n"
                    else:
                        banner = "> ⚠️ 本域文档待完善，内容可能不完整。\n\n"
                    if not content.startswith(banner):
                        content = banner + content
                    log.warning(
                        "hallucination_detected",
                        page_path=page.get("path"),
                        flags=hallucination_flags,
                    )
                    if is_topic and not is_topic_index:
                        updated_pages.append({**page, "content": "", "__rejected__": True})
                        continue
                    if is_overview and len(hallucination_flags) >= 3:
                        log.warning(
                            "hallucination_overview_rejected",
                            page_path=page.get("path"),
                            flags=hallucination_flags,
                        )
                        updated_pages.append({**page, "content": "", "__rejected__": True})
                        continue

            class_refs = _extract_class_references(content)
            if class_refs:
                log.warning(
                    "unverified_class_references",
                    page_title=page.get("title"),
                    page_path=page.get("path"),
                    references=sorted(class_refs),
                )
            content = repair_unclosed_code_blocks(content)
            title = page.get("title", "")
            if title:
                new_title = _rewrite_part_n_title(str(title), content)
                new_title = _rewrite_compound_title(new_title, page, content, state)
                if new_title != title:
                    page = {**page, "title": new_title, "content": content}
                else:
                    page = {**page, "content": content}
            else:
                page = {**page, "content": content}
        updated_pages.append(page)

    updated_pages = _deduplicate_titles(updated_pages)
    updated_pages = _strip_disambiguation_suffixes(updated_pages)
    updated_pages = _flag_titles_with_exposed_slugs(updated_pages)

    published = sum(1 for p in updated_pages if not p.get("__rejected__"))
    rejected = sum(1 for p in updated_pages if p.get("__rejected__"))
    log.info(
        "pipeline_complete",
        run_id=state.get("run_id"),
        total_pages=len(pages),
        pages_published=published,
        pages_rejected=rejected,
        error_count=len(state.get("errors", [])),
    )
    return {"pages": updated_pages} if updated_pages else {}
