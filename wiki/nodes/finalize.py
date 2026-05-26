"""Finalize node for wiki pipeline."""
from __future__ import annotations

import re
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_FAKE_SOURCE_RE = re.compile(r"com/xxx/")
_SOURCE_PROTOCOL_RE = re.compile(r"source://[^\s)>\]]+", re.IGNORECASE)
_CODE_REF_COMMENT_RE = re.compile(r"<!--\s*(?:CODE_REF|UNVERIFIED_CODE)\s*:?.*?-->", re.DOTALL)


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

    return content.strip()


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

    def replace_link(m: re.Match[str]) -> str:
        target = m.group(1)
        return m.group(0) if target in valid_targets else target

    return re.sub(r"\[\[([^\]]+)\]\]", replace_link, content)


async def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
    pages = list(state.get("pages", []))

    valid_targets: set[str] = set()
    for page in pages:
        title = page.get("title")
        path = page.get("path")
        bd = page.get("business_domain", "")
        if title:
            valid_targets.add(str(title))
            if bd:
                valid_targets.add(f"{bd}/{title}")
        if path:
            valid_targets.add(str(path))
            parts = str(path).strip("/").split("/")
            if len(parts) >= 3 and parts[-1] == "_overview":
                slug = parts[-2]
                if title:
                    valid_targets.add(f"{slug}/{title}")

    updated_pages: list[dict[str, Any]] = []
    for page in pages:
        content = page.get("content")
        if content:
            content = _sanitize_published_content(content)
            content = _remove_invalid_wikilinks(content, valid_targets)
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

    log.info(
        "pipeline_complete",
        total_pages=len(pages),
        error_count=len(state.get("errors", [])),
    )
    return {"pages": updated_pages} if updated_pages else {}
