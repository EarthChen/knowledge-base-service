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

    _populate_navigation_from_domain_tree(pages, state.get("domain_tree") or [])

    log.info(
        "create_links_done",
        pages_with_links=len(resolved_links),
        total_links=sum(len(v) for v in resolved_links.values()),
    )
    return {"resolved_links": resolved_links}


def _populate_navigation_from_domain_tree(
    pages: list[dict[str, Any]],
    domain_tree: list[dict[str, Any]],
) -> None:
    """Walk domain_tree and populate navigation field on matching pages."""
    from wiki.path_conventions import domain_overview_path

    pages_by_path: dict[str, dict[str, Any]] = {
        p.get("path", ""): p for p in pages if p.get("path")
    }

    def _walk(
        nodes: list[dict[str, Any]],
        parent_path: str,
        parent_title: str,
        breadcrumbs: list[list[str]],
    ) -> None:
        sibling_paths = [
            domain_overview_path(n.get("name", ""))
            for n in nodes
            if domain_overview_path(n.get("name", "")) in pages_by_path
        ]

        for node in nodes:
            name = node.get("name", "")
            if not name:
                continue
            display_name = node.get("display_name", name)
            overview_path = domain_overview_path(name)
            page = pages_by_path.get(overview_path)
            children = node.get("children", [])

            child_overview_paths = [
                domain_overview_path(c.get("name", ""))
                for c in children
                if domain_overview_path(c.get("name", "")) in pages_by_path
            ]

            topic_paths = sorted(
                p_path for p_path, p_data in pages_by_path.items()
                if (
                    p_data.get("page_type") == "topic"
                    and p_path.startswith(f"/__domains__/{name}/")
                )
            )

            current_crumbs = breadcrumbs + [[display_name, overview_path]]

            if page is not None:
                current_siblings = [s for s in sibling_paths if s != overview_path]
                page["navigation"] = {
                    "parent_path": parent_path,
                    "parent_title": parent_title,
                    "sibling_paths": current_siblings,
                    "child_paths": child_overview_paths + topic_paths,
                    "related_flow_paths": [],
                    "breadcrumbs": current_crumbs,
                }

            for tp in topic_paths:
                topic_page = pages_by_path.get(tp)
                if topic_page:
                    topic_title = topic_page.get("title", "")
                    other_topics = [t for t in topic_paths if t != tp]
                    topic_page["navigation"] = {
                        "parent_path": overview_path,
                        "parent_title": display_name,
                        "sibling_paths": other_topics,
                        "child_paths": [],
                        "related_flow_paths": [],
                        "breadcrumbs": current_crumbs + [[topic_title, tp]],
                    }

            if children:
                _walk(
                    children,
                    parent_path=overview_path,
                    parent_title=display_name,
                    breadcrumbs=current_crumbs,
                )

    _walk(domain_tree, parent_path="", parent_title="", breadcrumbs=[])
