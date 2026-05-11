"""Per-domain Agent: skeleton-first, then progressive enrichment.

Wraps WikiPageAgent with iterative quality-driven refinement,
Explore/Write two-phase separation, and document splitting.
"""
from __future__ import annotations

import re
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

MAX_PAGE_TOKENS = 5000


def _build_baseline(domain: dict[str, Any], module_summaries: dict[str, str]) -> str:
    """Concatenate domain description + per-module summaries from CLM."""
    parts = [f"## {domain['name']}"]
    if domain.get("description"):
        parts.append(domain["description"])
    for mod in domain.get("modules", []):
        summary = module_summaries.get(mod, "")
        if summary:
            parts.append(f"### {mod}\n{summary[:500]}")
    return "\n\n".join(parts)


def _maybe_split(content: str, domain_name: str) -> list[dict[str, Any]]:
    """Split oversized documents by ## sections."""
    estimated_tokens = len(content) // 4
    if estimated_tokens <= MAX_PAGE_TOKENS:
        return [_make_page(content, domain_name)]

    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    if len(sections) <= 1:
        return [_make_page(content, domain_name)]

    overview = sections[0]
    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in sections[1:]:
        title_match = re.match(r"^## (.+)", section)
        section_title = title_match.group(1).strip() if title_match else "Untitled"
        page_key = f"{domain_name}/{section_title}"
        child_pages.append(_make_page(section, page_key))
        child_links.append(f"- [[{page_key}|{section_title}]]")

    parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_name)

    return [parent_page, *child_pages]


def _make_page(content: str, key: str) -> dict[str, Any]:
    return {"type": "domain_overview", "title": key, "content": content}
