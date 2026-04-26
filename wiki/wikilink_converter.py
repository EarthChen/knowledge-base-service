"""Convert [[path]] wikilinks to relative markdown links or Obsidian format."""

from __future__ import annotations

import os
import re

_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


class WikiLinkConverter:
    """Bi-directional wikilink format converter.

    Handles conversion between internal ``[[/path]]`` markers
    (injected by ``WikiReferenceGenerator.inject_wikilinks``)
    and output formats (standard markdown links, Obsidian wikilinks).
    """

    def to_markdown(self, content: str, current_path: str) -> str:
        """Convert ``[[/path]]`` → ``[title](relative.md)`` standard markdown links."""

        def _replace(m: re.Match[str]) -> str:
            target = m.group(1).strip()
            title = target.rsplit("/", 1)[-1]
            if title == "_overview":
                parent = target.rsplit("/", 1)[0].rsplit("/", 1)[-1]
                title = parent if parent else "_overview"
            rel = self._relative_link(current_path, target)
            return f"[{title}]({rel})"

        return _WIKILINK_PATTERN.sub(_replace, content)

    def to_obsidian(self, content: str) -> str:
        """Normalize ``[[/path]]`` → ``[[path]]`` for Obsidian vault."""

        def _replace(m: re.Match[str]) -> str:
            target = m.group(1).strip().lstrip("/")
            return f"[[{target}]]"

        return _WIKILINK_PATTERN.sub(_replace, content)

    def extract_wikilinks(self, content: str) -> list[str]:
        """Return all ``[[path]]`` targets found in content."""
        return [m.group(1).strip() for m in _WIKILINK_PATTERN.finditer(content)]

    @staticmethod
    def _relative_link(from_path: str, to_path: str) -> str:
        """Compute relative markdown file path from one wiki path to another."""
        from_dir = os.path.dirname(from_path.strip("/"))
        to_clean = to_path.strip("/")
        if to_clean.endswith("/_overview"):
            to_file = to_clean.replace("/_overview", "/README.md")
        else:
            to_file = to_clean + ".md"
        rel = os.path.relpath(to_file, start=from_dir or ".")
        return rel.replace(os.sep, "/")
