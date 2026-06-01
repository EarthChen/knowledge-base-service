"""Project documentation discovery for wiki pipeline enrichment.

Reads AGENTS.md / CLAUDE.md / README.md from repository clone roots,
following Markdown links to sub-documents. Mimics the approach used by
Codex CLI, OpenCode, and Cline for project understanding.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

META_DOC_PRIORITY = ["AGENTS.md", "CLAUDE.md", "README.md", "readme.md"]
MAX_MAIN_DOC_LINES = 300
MAX_SUB_DOC_LINES = 200
MAX_LINKED_DOCS = 5
MAX_TOTAL_LINES = 1000

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")


def _safe_read_lines(path: Path, max_lines: int) -> list[str]:
    """Read file as lines, consistent with read_file tool behavior."""
    try:
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return all_lines[:max_lines]
    except (OSError, PermissionError):
        return []


def _resolve_safe_path(root: Path, rel: str) -> Path | None:
    """Resolve a relative path and verify it stays within root (prevent traversal)."""
    root_resolved = root.resolve()
    target = (root_resolved / rel).resolve()
    if not target.is_relative_to(root_resolved) or not target.is_file():
        return None
    return target


def _extract_md_links(lines: list[str]) -> list[str]:
    """Extract relative .md link targets from Markdown content."""
    links: list[str] = []
    for line in lines:
        for _label, href in _MD_LINK_RE.findall(line):
            if not href.startswith("http") and not href.startswith("#") and not href.startswith("file://"):
                links.append(href)
    return links


def discover_project_docs(repo_paths: dict[str, str]) -> list[dict[str, Any]]:
    """Discover and read project meta-documents from repository clone dirs.

    Returns list of dicts: [{repo, path, lines, total_lines, priority}]
    """
    results: list[dict[str, Any]] = []
    total_lines_read = 0

    for repo_id, root_str in repo_paths.items():
        root = Path(root_str)
        if not root.is_dir():
            continue

        main_doc: Path | None = None
        priority = 0
        for i, name in enumerate(META_DOC_PRIORITY):
            candidate = root / name
            if candidate.is_file():
                main_doc = candidate
                priority = i
                break

        if main_doc is None:
            continue

        lines = _safe_read_lines(main_doc, MAX_MAIN_DOC_LINES)
        if not lines:
            continue

        total_lines_read += len(lines)
        results.append({
            "repo": repo_id,
            "path": main_doc.name,
            "lines": lines,
            "total_lines": len(lines),
            "priority": priority,
        })

        if total_lines_read >= MAX_TOTAL_LINES:
            break

        linked_paths = _extract_md_links(lines)
        for link_path in linked_paths[:MAX_LINKED_DOCS]:
            if total_lines_read >= MAX_TOTAL_LINES:
                break
            sub_path = _resolve_safe_path(root, link_path)
            if sub_path is None:
                continue
            sub_lines = _safe_read_lines(sub_path, MAX_SUB_DOC_LINES)
            if sub_lines:
                total_lines_read += len(sub_lines)
                results.append({
                    "repo": repo_id,
                    "path": link_path,
                    "lines": sub_lines,
                    "total_lines": len(sub_lines),
                    "priority": priority + 10,
                })

    return results


def format_for_namer(docs: list[dict[str, Any]]) -> str:
    """Format project docs as context block for domain namer prompt."""
    if not docs:
        return ""

    parts: list[str] = ["Project documentation context:"]
    for doc in docs:
        lines = doc.get("lines", [])
        if not lines:
            continue
        header = f"\n--- {doc['path']} ---"
        parts.append(header)
        parts.extend(lines[:50])
        if len(lines) > 50:
            parts.append(f"... ({len(lines) - 50} more lines)")

    return "\n".join(parts)


def format_for_page_agent(docs: list[dict[str, Any]]) -> str:
    """Format project docs as background context for page agent."""
    if not docs:
        return ""

    parts: list[str] = ["## Project Background"]
    for doc in docs:
        lines = doc.get("lines", [])
        if not lines:
            continue
        parts.append(f"\n### From {doc['path']}:")
        parts.extend(lines[:80])

    return "\n".join(parts)
