"""Builds and manages the wiki tree structure."""

from __future__ import annotations

import hashlib
from collections import defaultdict


class WikiTreeBuilder:
    """Utility for generating wiki tree paths, UIDs, and detecting naming conflicts."""

    def generate_page_path(
        self,
        domain: str | None = None,
        repository: str | None = None,
        entity_name: str | None = None,
        is_overview: bool = False,
        is_flow: bool = False,
    ) -> str:
        parts: list[str] = []
        if domain:
            parts.append(domain)
        if is_overview:
            parts.append("_overview")
            return "/" + "/".join(parts)
        if is_flow and entity_name:
            parts.append(entity_name)
            parts.append("_flow")
            return "/" + "/".join(parts)
        if repository:
            parts.append(repository)
        if entity_name:
            parts.append(entity_name)
        return "/" + "/".join(parts)

    def generate_section_uid(self, business_id: str, section_title: str) -> str:
        return f"WikiSection:{business_id}:{section_title}"

    def generate_space_uid(self, business_id: str) -> str:
        return f"WikiSpace:{business_id}"

    def detect_naming_conflicts(
        self, pages: list[dict[str, str]]
    ) -> dict[str, list[str]]:
        name_to_repos: dict[str, list[str]] = defaultdict(list)
        for page in pages:
            entity_name = page.get("entity_name", "")
            repo = page.get("repository", "")
            if entity_name and repo:
                name_to_repos[entity_name].append(repo)

        return {
            name: repos
            for name, repos in name_to_repos.items()
            if len(repos) > 1
        }

    def compute_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
