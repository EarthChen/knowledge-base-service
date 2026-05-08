"""Wiki cross-link resolution node."""

import re
from typing import Any

from core.log import get_logger

log = get_logger(__name__)


async def create_links_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 4c-4d: resolve cross-links and prepare link metadata for persistence."""
    pages = state.get("pages", [])
    page_titles = {p.get("title", "").lower(): p.get("path", "") for p in pages}
    page_paths = {
        p.get("path", "").rsplit("/", 1)[-1].lower(): p.get("path", "")
        for p in pages
        if p.get("path")
    }

    link_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    resolved_links: dict[str, list[dict[str, str]]] = {}

    for page in pages:
        page_path = page.get("path", "")
        content = page.get("content", "")
        links: list[dict[str, str]] = []

        for match in link_pattern.finditer(content):
            link_text = match.group(1)
            key = link_text.lower()
            target = page_titles.get(key) or page_paths.get(key)
            if target and target != page_path:
                links.append({"from_text": link_text, "target_path": target})
                log.debug("wiki_link_resolved", source=page_path, target=target)

        if links:
            resolved_links[page_path] = links

    log.info(
        "create_links_done",
        pages_with_links=len(resolved_links),
        total_links=sum(len(v) for v in resolved_links.values()),
    )
    return {"resolved_links": resolved_links}
