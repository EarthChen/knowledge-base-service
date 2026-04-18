"""Shared helpers for merging file changes from webhook commit payloads."""

from __future__ import annotations

from typing import Any

from wiki.webhook.event_model import ChangedFile


def merge_changed_files_from_commits(commits: list[dict[str, Any]]) -> list[ChangedFile]:
    """Last mention of a path wins (simulates stacked commits). Deduplicate by path."""
    by_path: dict[str, ChangedFile] = {}
    for commit in commits:
        for path in commit.get("added") or []:
            if isinstance(path, str):
                by_path[path] = ChangedFile(path=path, status="added")
        for path in commit.get("modified") or []:
            if isinstance(path, str):
                by_path[path] = ChangedFile(path=path, status="modified")
        for path in commit.get("removed") or []:
            if isinstance(path, str):
                by_path[path] = ChangedFile(path=path, status="removed")
        renamed = commit.get("renamed_file")
        if isinstance(renamed, dict):
            new_p = renamed.get("new_path")
            old_p = renamed.get("old_path")
            if isinstance(new_p, str) and isinstance(old_p, str):
                by_path[new_p] = ChangedFile(path=new_p, status="renamed", old_path=old_p)
    return list(by_path.values())
