"""Path and document section helpers for repository / document API routes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.\s]")


def relative_file_path(file_path: str, repository: str | None) -> str:
    """Strip clone/base prefix from absolute paths so responses use repo-relative paths."""
    if not file_path:
        return file_path
    normalized = file_path.replace("\\", "/")
    if repository:
        marker = f"/{repository}/"
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx + len(marker) :]
    return normalized


def build_file_tree(rows: list[dict[str, Any]], repository: str) -> dict[str, Any]:
    """Convert flat Module ``file`` paths into a nested directory/file tree."""
    root: dict[str, Any] = {"name": "/", "type": "directory", "children": [], "path": ""}
    for row in rows:
        raw_file = row.get("file") or ""
        file_path = raw_file.replace("\\", "/")
        if not file_path:
            continue
        parts = [p for p in file_path.split("/") if p]
        current = root
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            existing = next((c for c in current["children"] if c["name"] == part), None)
            if existing is None:
                if is_file:
                    node: dict[str, Any] = {
                        "name": part,
                        "type": "file",
                        "path": file_path,
                    }
                    repo_val = row.get("repository") or repository
                    if repo_val:
                        node["repository"] = repo_val
                else:
                    node = {
                        "name": part,
                        "type": "directory",
                        "path": "/".join(parts[: i + 1]),
                        "children": [],
                    }
                current["children"].append(node)
                current = node if not is_file else current
            else:
                current = existing if not is_file else current

    def sort_tree(node: dict[str, Any]) -> None:
        ch = node.get("children")
        if isinstance(ch, list) and ch:
            ch.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
            for child in ch:
                sort_tree(child)

    sort_tree(root)
    return root


def infer_section_levels(sections: list[dict[str, Any]], file_path: str | None = None) -> None:
    """Infer heading levels from original file or numbered title patterns."""
    heading_levels: dict[str, int] = {}

    if file_path:
        try:
            fpath = Path(file_path)
            if fpath.is_file():
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
        m = _NUMBERED_HEADING_RE.match(title)
        if m:
            dots = m.group(1).count(".")
            s["level"] = 2 + dots
        elif i == 0:
            s["level"] = 1
        else:
            s["level"] = prev_level
        prev_level = s["level"]


# Backward compatibility for tests and external imports
def _relative_file_path(file_path: str, repository: str | None) -> str:
    return relative_file_path(file_path, repository)


def _build_file_tree(rows: list[dict[str, Any]], repository: str) -> dict[str, Any]:
    return build_file_tree(rows, repository)


def _infer_section_levels(sections: list[dict[str, Any]], file_path: str | None = None) -> None:
    return infer_section_levels(sections, file_path)
