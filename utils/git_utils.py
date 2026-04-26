"""Git remote URL heuristics."""

from __future__ import annotations


def looks_like_git_url(value: str) -> bool:
    """Return True if ``value`` looks like a git remote URL rather than a local path."""
    if value.startswith(("http://", "https://", "git@", "ssh://")):
        return True
    return value.endswith(".git")
