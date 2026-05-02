"""Standalone helpers for MCP server (entity filters, paths, document formatting)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.auth import Role
from core.config import get_settings
from store.schema import NodeLabel

_MAX_FILE_READ_BYTES = 512 * 1024

_ENTITY_FILTER_LABELS: dict[str, frozenset[str]] = {
    "function": frozenset({str(NodeLabel.FUNCTION)}),
    "class": frozenset({str(NodeLabel.CLASS)}),
    "module": frozenset({str(NodeLabel.MODULE)}),
    "document": frozenset({str(NodeLabel.DOCUMENT)}),
}


def _normalize_entity_type_arg(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s.lower() if s else None


def _filter_semantic_matches_by_entity_type(
    matches: list[dict[str, Any]],
    entity_type: str | None,
) -> list[dict[str, Any]]:
    if not entity_type:
        return matches
    if entity_type in ("flow", "concept"):
        return matches
    allowed = _ENTITY_FILTER_LABELS.get(entity_type)
    if not allowed:
        return matches
    return [m for m in matches if m.get("type") in allowed]


def _filter_graph_context_by_entity_type(
    graph_context: list[dict[str, Any]],
    entity_type: str | None,
) -> list[dict[str, Any]]:
    if not entity_type:
        return graph_context
    if entity_type in ("flow", "concept"):
        return graph_context
    allowed = _ENTITY_FILTER_LABELS.get(entity_type)
    if not allowed:
        return graph_context
    fn_label = str(NodeLabel.FUNCTION)
    out: list[dict[str, Any]] = []
    for item in graph_context:
        t = item.get("type", "")
        if t in allowed:
            out.append(item)
        elif t == "business_flow" and fn_label in allowed:
            out.append(item)
    return out


def _mcp_error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _resolve_repo_base_path(repository: str, repo_registry: Any | None = None) -> Path | None:
    """Resolve repository name to its local clone directory.

    Security: rejects any repository value that resolves outside clone_base_path.
    When the graph uses a canonical name that differs from the clone folder (see
    ``RepoRegistry`` + ``GitManager``), ``repo_registry`` is used to find the git URL
    and the same on-disk path as indexing.
    """
    from services.git_manager import resolve_repo_clone_root

    return resolve_repo_clone_root(repository, get_settings().git, repo_registry)


_WIKI_MCP_DISPATCH_FALLBACK: tuple[tuple[str, str, Role], ...] = (
    ("get_wiki_page", "handle_get_wiki_page", Role.VIEWER),
    ("list_wiki_pages", "handle_list_wiki_pages", Role.VIEWER),
    ("wiki_search", "handle_wiki_search", Role.VIEWER),
    ("wiki_export", "handle_wiki_export", Role.EDITOR),
    ("wiki_get_tree", "handle_wiki_get_tree", Role.VIEWER),
    ("wiki_get_related", "handle_wiki_get_related", Role.VIEWER),
    ("wiki_get_domain_overview", "handle_wiki_get_domain_overview", Role.VIEWER),
    ("wiki_get_snapshot", "handle_wiki_get_snapshot", Role.VIEWER),
    ("wiki_find_implementing_modules", "handle_wiki_find_implementing_modules", Role.VIEWER),
    ("unified_knowledge_query", "handle_unified_knowledge_query", Role.VIEWER),
)

_DOC_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.\s]")


def _mcp_relative_document_path(file_path: str, repository: str | None) -> str:
    """Strip clone/base prefix from absolute paths (same logic as main list/get documents)."""
    if not file_path:
        return file_path
    normalized = file_path.replace("\\", "/")
    if repository:
        marker = f"/{repository}/"
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx + len(marker) :]
    return normalized


def _mcp_infer_section_levels(sections: list[dict[str, Any]], file_path: str | None = None) -> None:
    heading_levels: dict[str, int] = {}

    if file_path:
        try:
            fpath = Path(file_path).resolve()
            if fpath.is_file() and ".." not in Path(file_path).parts:
                raw = fpath.read_text(encoding="utf-8")
                for line in raw.split("\n"):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        hashes = len(stripped) - len(stripped.lstrip("#"))
                        title = stripped[hashes:].strip()
                        heading_levels[title] = hashes
        except OSError:
            pass

    if heading_levels:
        for s in sections:
            title = s.get("title", "")
            clean_title = title.rsplit(" > ", 1)[-1] if " > " in title else title
            if clean_title in heading_levels:
                s["level"] = heading_levels[clean_title]
        return

    prev_level = 2
    for i, s in enumerate(sections):
        title = s.get("title", "")
        m = _DOC_NUMBERED_HEADING_RE.match(title)
        if m:
            dots = m.group(1).count(".")
            s["level"] = 2 + dots
        elif i == 0:
            s["level"] = 1
        else:
            s["level"] = prev_level
        prev_level = s["level"]


def _format_list_documents_mcp(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_uid: dict[str, dict[str, Any]] = {}
    for r in result_rows:
        uid = r.get("uid")
        if not uid:
            continue
        if uid not in by_uid:
            repo = r.get("repository")
            raw_file = r.get("file") or ""
            by_uid[uid] = {
                "file": _mcp_relative_document_path(raw_file, repo),
                "title": r.get("title") or r.get("name") or "",
                "repository": repo,
                "uid": uid,
                "content_hash": r.get("content_hash"),
                "sections": [],
            }
        sec_uid = r.get("sec_uid")
        if sec_uid:
            by_uid[uid]["sections"].append({
                "title": r.get("sec_name") or r.get("sec_title") or "",
                "uid": sec_uid,
                "start_line": r.get("sec_start_line"),
            })

    documents = sorted(
        by_uid.values(),
        key=lambda d: (d.get("repository") or "", d.get("file") or ""),
    )
    for d in documents:
        d["sections"].sort(key=lambda s: (s.get("start_line") is None, s.get("start_line") or 0))

    return {"documents": documents, "total": len(documents)}


def _format_get_document_mcp(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = result_rows[0]
    repo = first.get("repository")
    raw_file = first.get("file") or ""

    sections: list[dict[str, Any]] = []
    for r in result_rows:
        suid = r.get("section_uid")
        if not suid:
            continue
        sections.append({
            "title": r.get("section_name") or r.get("section_title") or "",
            "content": r.get("content") or "",
            "start_line": r.get("start_line"),
            "uid": suid,
            "level": r.get("level"),
        })

    has_stored_levels = any(s.get("level") is not None for s in sections)
    if not has_stored_levels:
        _mcp_infer_section_levels(sections, file_path=first.get("file"))

    for s in sections:
        if s.get("level") is None:
            s["level"] = 2

    return {
        "title": first.get("title") or "",
        "file": _mcp_relative_document_path(raw_file, repo),
        "repository": repo,
        "sections": sections,
    }
