"""Shared wiki composition helpers used by WikiService and WikiPageComposerService."""

from __future__ import annotations

from store.schema import GraphNode
from wiki.models import (
    NavigationContext,
    PageType,
    WikiPage,
    WikiPageSummary,
    WikiStructureNode,
)


def _populate_navigation_context(
    root: WikiStructureNode,
    pages: dict[str, WikiPage],
) -> None:
    """Walk structure tree and populate NavigationContext for each page."""

    def _walk(
        node: WikiStructureNode,
        parent: WikiStructureNode | None,
        breadcrumbs: list[tuple[str, str]],
    ) -> None:
        current_crumbs = breadcrumbs + [(node.title, node.path)]
        if node.path in pages:
            page = pages[node.path]
            nav = NavigationContext(
                parent_path=parent.path if parent else None,
                parent_title=parent.title if parent else None,
                sibling_paths=[
                    ch.path for ch in (parent.children if parent else []) if ch.path != node.path
                ],
                child_paths=[ch.path for ch in node.children],
                breadcrumbs=current_crumbs,
            )
            page.navigation = nav
        for child in node.children:
            _walk(child, node, current_crumbs)

    _walk(root, None, [])


def _expected_wiki_page_paths_dfs(node: WikiStructureNode) -> list[str]:
    """Depth-first structure paths matching ``_compose_all_pages`` walk order."""
    if node.page_type == PageType.REPO_OVERVIEW:
        order = [node.path]
        for ch in node.children:
            order.extend(_expected_wiki_page_paths_dfs(ch))
        return order
    order = [node.path]
    for ch in node.children:
        order.extend(_expected_wiki_page_paths_dfs(ch))
    return order


def _extract_summary(page: WikiPage, entity_uid: str = "") -> WikiPageSummary:
    """Extract a short summary from a composed WikiPage for parent aggregation."""
    content = page.content or ""
    overview_start = content.find("## Overview")
    if overview_start >= 0:
        after_heading = content[overview_start + len("## Overview") :].strip()
        next_heading = after_heading.find("\n## ")
        if next_heading > 0:
            summary_text = after_heading[:next_heading].strip()[:200]
        else:
            summary_text = after_heading[:200]
    else:
        lines = content.split("\n")
        non_heading = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
        summary_text = " ".join(non_heading)[:200]
    summary_text = summary_text.replace("\n", " ").strip()
    return WikiPageSummary(
        entity_uid=entity_uid,
        title=page.title,
        path=page.path,
        summary=summary_text,
        importance_tier=getattr(page, "_importance_tier", None),
        page_type=page.page_type,
    )


def _collect_nodes_by_depth(
    root: WikiStructureNode,
) -> tuple[list[WikiStructureNode], list[tuple[int, WikiStructureNode]]]:
    """Partition tree into (leaves, [(depth, parent_node)]) with parents sorted deepest-first."""
    leaves: list[WikiStructureNode] = []
    parents: list[tuple[int, WikiStructureNode]] = []

    def _visit(node: WikiStructureNode, depth: int) -> None:
        if node.page_type == PageType.REPO_OVERVIEW:
            parents.append((depth, node))
            for child in node.children:
                _visit(child, depth + 1)
            return
        if not node.children:
            leaves.append(node)
        else:
            parents.append((depth, node))
            for child in node.children:
                _visit(child, depth + 1)

    _visit(root, 0)
    parents.sort(key=lambda x: -x[0])
    return leaves, parents


def _build_lightweight_glossary(entities: list[GraphNode]) -> dict[str, str]:
    """Build a glossary dict from entity names and business_summary without LLM calls."""
    terms: dict[str, str] = {}
    for node in entities:
        name = node.properties.get("name", "")
        bs = (node.properties.get("business_summary", "") or "")[:80]
        if name and bs:
            terms[name] = bs
    return terms


def _build_lightweight_parent_context(parent_node: GraphNode | None) -> str:
    """Extract parent context from graph node properties."""
    if parent_node is None:
        return ""
    props = parent_node.properties
    parts: list[str] = []
    name = props.get("name", "")
    if name:
        parts.append(f"Parent module: {name}")
    bs = props.get("business_summary", "")
    if bs:
        parts.append(f"Context: {bs}")
    desc = props.get("description", "")
    if desc and desc != bs:
        parts.append(f"Description: {desc[:200]}")
    return ". ".join(parts)
