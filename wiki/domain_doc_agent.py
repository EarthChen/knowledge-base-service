"""Per-domain Agent: skeleton-first, then progressive enrichment.

Wraps WikiPageAgent with iterative quality-driven refinement,
Explore/Write two-phase separation, and document splitting.
"""
from __future__ import annotations

import re
from typing import Any

from core.log import get_logger
from wiki.page_agent import WikiPageAgent
from wiki.quality_report import evaluate_quality

log = get_logger(__name__)

MAX_PAGE_TOKENS = 5000


def _build_baseline(domain: dict[str, Any], module_summaries: dict[str, Any]) -> str:
    """Concatenate domain description + per-module summaries from CLM."""
    parts = [f"## {domain['name']}"]
    if domain.get("description"):
        parts.append(domain["description"])
    for mod in domain.get("modules", []):
        raw = module_summaries.get(mod, "")
        if isinstance(raw, dict):
            text = str(raw.get("summary_text", "") or "")
        else:
            text = str(raw) if raw else ""
        if text:
            parts.append(f"### {mod}\n{text[:500]}")
    return "\n\n".join(parts)


def _maybe_split(content: str, domain_name: str) -> list[dict[str, Any]]:
    """Split oversized documents by ## sections."""
    estimated_tokens = len(content) // 4
    if estimated_tokens <= MAX_PAGE_TOKENS:
        return [_make_page(content, domain_name)]

    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    if len(sections) <= 1:
        return [_make_page(content, domain_name)]

    overview = sections[0]
    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in sections[1:]:
        title_match = re.match(r"^## (.+)", section)
        section_title = title_match.group(1).strip() if title_match else "Untitled"
        page_key = f"{domain_name}/{section_title}"
        child_pages.append(_make_page(section, page_key))
        child_links.append(f"- [[{page_key}|{section_title}]]")

    parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_name)

    return [parent_page, *child_pages]


def _make_page(content: str, key: str) -> dict[str, Any]:
    from wiki.path_conventions import domain_overview_path

    return {
        "page_type": "domain_overview",
        "title": key,
        "path": domain_overview_path(key),
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {
            "node_count": 0,
            "edge_count": 0,
            "generation_mode": "agent",
        },
    }


class DomainDocAgent:
    """Per-domain agent: skeleton-first, then progressive enrichment."""

    def __init__(
        self,
        domain_name: str,
        llm: Any,
        graph_store: Any,
        *,
        max_iterations: int = 20,
        repo_path: str | None = None,
        search_service: Any | None = None,
    ) -> None:
        self.domain_name = domain_name
        self._page_agent = WikiPageAgent(
            llm,
            graph_store,
            max_rounds=20,
            max_tool_calls=100,
            repo_path=repo_path,
            search_service=search_service,
        )
        self._max_iterations = max_iterations
        self.iteration_history: list[dict[str, Any]] = []

    async def generate_with_iterations(
        self,
        module_names: list[str],
        baseline_context: str,
    ) -> list[dict[str, Any]]:
        """Generate domain documentation with quality-driven iteration."""
        content = await self._page_agent.generate(
            module_names=module_names,
            domain_name=self.domain_name,
            baseline_context=baseline_context,
        )

        if not module_names:
            return _maybe_split(content, self.domain_name)

        for iteration in range(self._max_iterations):
            quality = evaluate_quality(content, module_names)
            self.iteration_history.append({
                "iteration": iteration,
                "coverage": quality.coverage,
                "citation_density": quality.citation_density,
                "context_gaps": quality.context_gap_count,
                "uncovered_count": len(quality.uncovered_modules),
            })

            log.info(
                "domain_agent_iteration",
                domain=self.domain_name,
                iteration=iteration,
                coverage=quality.coverage,
                citation_density=quality.citation_density,
                gaps=quality.context_gap_count,
            )

            if (
                quality.coverage >= 0.95
                and quality.citation_density >= 0.5
                and quality.context_gap_count == 0
            ):
                break

            content = await self._page_agent.enrich(
                content,
                domain_name=self.domain_name,
                focus_modules=quality.uncovered_modules or None,
                quality_report=quality,
            )

        if len(self.iteration_history) >= self._max_iterations:
            log.warning("max_safety_iterations", domain=self.domain_name)

        return _maybe_split(content, self.domain_name)
