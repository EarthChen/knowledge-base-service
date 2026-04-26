"""Utility for building wiki tree UIDs and detecting naming conflicts."""

from __future__ import annotations

import hashlib
from collections import defaultdict


class WikiTreeBuilder:
    """Helpers for constructing WikiSpace / WikiSection uid conventions."""

    def generate_space_uid(self, business_id: str) -> str:
        return f"WikiSpace:{business_id}"

    def generate_section_uid(self, business_id: str, section_name: str) -> str:
        return f"WikiSection:{business_id}:{section_name}"

    def generate_domain_section_uid(self, business_id: str, domain_name: str) -> str:
        return f"WikiSection:{business_id}:domain:{domain_name}"

    def generate_repo_section_uid(self, business_id: str, repo_name: str) -> str:
        return f"WikiSection:{business_id}:repo:{repo_name}"

    def compute_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def detect_naming_conflicts(
        self, pages: list[dict[str, str]]
    ) -> dict[str, list[str]]:
        name_repos: dict[str, set[str]] = defaultdict(set)
        for p in pages:
            name = p.get("entity_name", "")
            repo = p.get("repository", "")
            if name and repo:
                name_repos[name].add(repo)
        return {
            name: sorted(repos)
            for name, repos in name_repos.items()
            if len(repos) > 1
        }

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
