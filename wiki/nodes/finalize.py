"""Finalize node for wiki pipeline."""

from __future__ import annotations

import re
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

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
            if not in_code_block:
                in_code_block = True
                code_block_has_fake = False
                code_buf = [line]
                continue
            code_buf.append(line)
            in_code_block = False
            if not code_block_has_fake:
                result.extend(code_buf)
            code_buf = []
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


def _sanitize_published_content(content: str) -> str:
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

    # 7. Close unclosed code blocks
    if content.count("```") % 2 == 1:
        content += "\n```"

    # 8. Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    for pattern, replacement in _REDACT_PATTERNS:
        content = pattern.sub(replacement, content)

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


def _remove_invalid_wikilinks(content: str, valid_targets: set[str]) -> str:
    """Remove wikilinks pointing to non-existent pages."""
    valid_lower = {t.lower() for t in valid_targets if t}

    def replace_link(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        return m.group(0) if target.lower() in valid_lower else target

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


def _get_skeleton_threshold(page_type: str = "domain_overview") -> int:
    from core.config import get_settings

    if page_type == "topic":
        return get_settings().wiki.topic_min_content_chars
    return get_settings().wiki.overview_min_content_chars


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
        if content:
            content = _sanitize_published_content(content)
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

                min_publish = get_settings().wiki.topic_min_publish_chars
                if raw_content_len < min_publish:
                    log.warning(
                        "stub_topic_rejected",
                        page_path=page.get("path"),
                        content_len=raw_content_len,
                        threshold=min_publish,
                    )
                    updated_pages.append({**page, "content": "", "__rejected__": True})
                    continue

            if is_topic and not is_topic_index:
                from core.config import get_settings

                content_language = _resolve_page_content_language(page, state)
                if _is_chinese_lang(content_language):
                    min_ratio = get_settings().wiki.cn_ratio_hard_min
                    cn_ratio = _compute_cn_ratio(content)
                    if cn_ratio < min_ratio:
                        log.warning(
                            "low_cn_ratio_topic_rejected",
                            page_path=page.get("path"),
                            cn_ratio=round(cn_ratio, 3),
                            min_ratio=min_ratio,
                        )
                        updated_pages.append({**page, "content": "", "__rejected__": True})
                        continue

            if is_overview or is_topic:
                hallucination_flags = _detect_hallucination_patterns(content)
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
            page = {**page, "content": content}
        updated_pages.append(page)

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
