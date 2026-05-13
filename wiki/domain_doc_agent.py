"""Per-domain Agent: skeleton-first, then progressive enrichment.

Wraps WikiPageAgent with iterative quality-driven refinement,
Explore/Write two-phase separation, and document splitting.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from core.log import get_logger
from wiki.page_agent import WikiPageAgent, WorkingMemory
from wiki.quality_report import evaluate_quality

log = get_logger(__name__)

MAX_PAGE_TOKENS = 5000

EXPLORE_TIMEOUT_SEC = int(os.environ.get("EXPLORE_TIMEOUT_SEC", "240"))
WRITE_TIMEOUT_SEC = int(os.environ.get("WRITE_TIMEOUT_SEC", "120"))


def _extract_tree_edges(
    nodes: list[dict[str, Any]],
    domain_modules: set[str],
    edges: list[tuple[str, str]],
) -> None:
    """Extract parent→child edges from module_tree (list of root dicts)."""
    for node in nodes:
        parent_key = node.get("canonical_key", "")
        for child in node.get("children", []):
            child_key = child.get("canonical_key", "")
            if parent_key and child_key and (
                parent_key in domain_modules or child_key in domain_modules
            ):
                edges.append((parent_key, child_key))
            _extract_tree_edges([child], domain_modules, edges)


def _build_baseline(
    domain: dict[str, Any],
    module_summaries: dict[str, Any],
    *,
    module_tree: list[dict[str, Any]] | None = None,
) -> str:
    """Build baseline context: domain description + topology + one-line module roles.

    Provides enough structure for Agent to know the domain shape while forcing
    deep code exploration via tools (avoids Issue #008 lazy behavior).
    """
    display = domain.get("display_name", domain["name"])
    parts = [f"## {display}"]
    if domain.get("description"):
        parts.append(domain["description"])

    modules = domain.get("modules", [])
    if modules:
        parts.append("### 模块列表")
        for mod in modules:
            raw = module_summaries.get(mod, "")
            if isinstance(raw, dict):
                text = str(raw.get("summary_text", "") or "")
            else:
                text = str(raw) if raw else ""
            one_liner = text.split("\n")[0][:80] if text else ""
            parts.append(f"- **{mod}**: {one_liner}" if one_liner else f"- **{mod}**")

    if module_tree:
        domain_modules = set(modules)
        relevant_edges: list[tuple[str, str]] = []
        _extract_tree_edges(module_tree, domain_modules, relevant_edges)
        if relevant_edges:
            parts.append("### 模块依赖拓扑")
            for src, tgt in relevant_edges[:20]:
                parts.append(f"- {src} → {tgt}")

    return "\n\n".join(parts)


def _maybe_split(
    content: str,
    domain_slug: str,
    domain_display_name: str = "",
) -> list[dict[str, Any]]:
    """Split oversized documents by ## sections into topic sub-pages."""
    display = domain_display_name or domain_slug
    estimated_tokens = len(content) // 4
    if estimated_tokens <= MAX_PAGE_TOKENS:
        return [_make_page(content, domain_slug, display)]

    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    sections = [s for s in sections if s]
    if len(sections) <= 1:
        return [_make_page(content, domain_slug, display)]

    from wiki.path_conventions import domain_topic_path

    overview = sections[0]
    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in sections[1:]:
        title_match = re.match(r"^## (.+)", section)
        section_title = title_match.group(1).strip() if title_match else "Untitled"
        topic_path = domain_topic_path(domain_slug, section_title)
        child_pages.append({
            "page_type": "topic",
            "title": section_title,
            "path": topic_path,
            "content": section,
            "diagrams": [],
            "source_locations": [],
            "metadata": {
                "node_count": 0,
                "edge_count": 0,
                "generation_mode": "agent",
            },
        })
        child_links.append(f"- [[{section_title}]]")

    parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_slug, display)

    return [parent_page, *child_pages]


def _make_page(content: str, slug: str, display_name: str = "") -> dict[str, Any]:
    from wiki.path_conventions import domain_overview_path

    return {
        "page_type": "domain_overview",
        "title": display_name or slug,
        "path": domain_overview_path(slug),
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
        domain_display_name: str = "",
        max_iterations: int = 20,
        repo_path: str | None = None,
        search_service: Any | None = None,
    ) -> None:
        self.domain_name = domain_name
        self.domain_display_name = domain_display_name or domain_name
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

    async def _pre_fill_snippets(self, memory: WorkingMemory, module_names: list[str]) -> None:
        graph = self._page_agent._graph
        if not graph or not module_names:
            return
        try:
            from wiki.cypher_queries import CHUNK_SNIPPETS_CY, SNIPPETS_CY

            result = await graph.execute_query(SNIPPETS_CY, {"names": module_names})
            for row in (getattr(result, "data", None) or []):
                func_name = str(row.get("func_name", ""))
                snippet = str(row.get("snippet", "")).strip()
                file_path = str(row.get("file_path", ""))
                if snippet:
                    memory.code_snippets.append(f"[{func_name} @ {file_path}]\n{snippet}")
            if not memory.code_snippets:
                result = await graph.execute_query(CHUNK_SNIPPETS_CY, {"names": module_names})
                for row in (getattr(result, "data", None) or []):
                    entity_name = str(row.get("entity_name", ""))
                    snippet = str(row.get("snippet", "")).strip()
                    if snippet:
                        memory.code_snippets.append(f"[{entity_name}]\n{snippet}")
                        if len(memory.code_snippets) >= 6:
                            break
        except Exception:
            log.warning("pre_fill_snippets_failed", domain=self.domain_name, exc_info=True)

    async def generate_with_iterations(
        self,
        module_names: list[str],
        baseline_context: str,
    ) -> list[dict[str, Any]]:
        """Generate domain documentation with Explore → Write → Quality loop.

        Each phase (explore, write) has its own timeout. Write retries once
        on first timeout. A total elapsed-time budget prevents runaway loops.
        """
        total_budget = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "600"))
        loop = asyncio.get_running_loop()
        t0 = loop.time()

        def _remaining() -> float:
            return max(0, total_budget - (loop.time() - t0))

        memory = WorkingMemory()
        await self._pre_fill_snippets(memory, module_names)
        try:
            timeout = min(EXPLORE_TIMEOUT_SEC, _remaining())
            await asyncio.wait_for(
                self._page_agent.explore(
                    module_names=module_names,
                    domain_name=self.domain_name,
                    baseline_context=baseline_context,
                    memory=memory,
                ),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            log.warning(
                "explore_timeout_partial",
                domain=self.domain_name,
                memory_chars=memory._total_chars(),
            )

        if not module_names:
            content = await self._page_agent.write(
                self.domain_name,
                baseline_context,
                memory,
            )
            pages = _maybe_split(content, self.domain_name, self.domain_display_name)
            if memory.discovered_entity_uids:
                entity_uids = list(memory.discovered_entity_uids)
                for page in pages:
                    page["covered_entity_uids"] = entity_uids
            return pages

        content = ""
        write_timeout_count = 0

        for iteration in range(self._max_iterations):
            if _remaining() <= 0:
                log.warning("total_budget_exhausted", domain=self.domain_name)
                break

            try:
                timeout = min(WRITE_TIMEOUT_SEC, _remaining())
                content = await asyncio.wait_for(
                    self._page_agent.write(
                        self.domain_name,
                        baseline_context,
                        memory,
                    ),
                    timeout=timeout,
                )
                write_timeout_count = 0
            except (asyncio.TimeoutError, TimeoutError):
                write_timeout_count += 1
                log.warning(
                    "write_timeout",
                    domain=self.domain_name,
                    attempt=write_timeout_count,
                )
                if write_timeout_count >= 2:
                    break
                continue

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
                log.info("quality_perfect_exit", domain=self.domain_name, iteration=iteration)
                break

            if iteration >= 2 and quality.coverage >= 0.9 and quality.citation_density >= 0.3:
                log.info(
                    "quality_acceptable_exit",
                    domain=self.domain_name,
                    iteration=iteration,
                    coverage=quality.coverage,
                    citation_density=quality.citation_density,
                )
                break

            if iteration >= 3:
                log.info("quality_max_iteration_exit", domain=self.domain_name, iteration=iteration)
                break

            if _remaining() <= 0:
                break

            supplemental_memory = WorkingMemory()
            try:
                timeout = min(EXPLORE_TIMEOUT_SEC, _remaining())
                await asyncio.wait_for(
                    self._page_agent.explore(
                        module_names,
                        self.domain_name,
                        baseline_context,
                        focus_modules=quality.uncovered_modules or None,
                        memory=supplemental_memory,
                    ),
                    timeout=timeout,
                )
            except (asyncio.TimeoutError, TimeoutError):
                log.warning("reexplore_timeout", domain=self.domain_name)
            finally:
                if supplemental_memory._total_chars() > 0:
                    memory.merge(supplemental_memory)
            if _remaining() <= 0:
                break

        if len(self.iteration_history) >= self._max_iterations:
            log.warning("max_safety_iterations", domain=self.domain_name)

        if not content:
            content = self._page_agent._generate_skeleton(module_names, self.domain_name)

        pages = _maybe_split(content, self.domain_name, self.domain_display_name)
        if memory.discovered_entity_uids:
            entity_uids = list(memory.discovered_entity_uids)
            log.info(
                "entity_uids_from_explore",
                domain=self.domain_name,
                uid_count=len(entity_uids),
            )
            for page in pages:
                page["covered_entity_uids"] = entity_uids
        return pages
