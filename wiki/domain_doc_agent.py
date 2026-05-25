"""Per-domain Agent: skeleton-first, then progressive enrichment.

Wraps WikiPageAgent with iterative quality-driven refinement,
Explore/Write two-phase separation, and document splitting.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.log import get_logger
from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult
from wiki.page_agent import WikiPageAgent, WorkingMemory
from wiki.output_guardrail import (
    CoverageCheck,
    FormatCheck,
    LengthCheck,
    OutputGuardrailChain,
)
from wiki.quality_report import evaluate_quality
from wiki.quality_trace import AgentTrace, TraceCollector

log = get_logger(__name__)


@dataclass
class TopicPlan:
    title: str
    modules: list[str]
    description: str = ""


@dataclass
class DomainTopicOutline:
    should_split: bool
    topics: list[TopicPlan]


def _parse_topic_outline(raw: str) -> DomainTopicOutline | None:
    """Parse LLM output into a DomainTopicOutline. Returns None on failure."""
    from wiki.json_robust import parse_json_robust_sync

    parsed = parse_json_robust_sync(raw)
    if not isinstance(parsed, dict):
        return None
    should_split = parsed.get("should_split")
    topics_raw = parsed.get("topics")
    if should_split is None or not isinstance(topics_raw, list):
        return None
    topics = []
    for t in topics_raw:
        if not isinstance(t, dict):
            continue
        title = t.get("title", "")
        modules = t.get("modules", [])
        if not title or not isinstance(modules, list):
            continue
        topics.append(TopicPlan(
            title=str(title),
            modules=[str(m) for m in modules],
            description=str(t.get("description", "")),
        ))
    if not topics:
        return None
    if len(topics) > 6:
        topics = topics[:6]
    return DomainTopicOutline(should_split=bool(should_split), topics=topics)


MAX_PAGE_TOKENS = 5000

EXPLORE_TIMEOUT_SEC = int(os.environ.get("EXPLORE_TIMEOUT_SEC", "240"))
WRITE_TIMEOUT_SEC = int(os.environ.get("WRITE_TIMEOUT_SEC", "180"))
_DOMAIN_AGENT_INNER_MARGIN_SEC = 30
_DEFAULT_DOMAIN_AGENT_TIMEOUT_SEC = 600


def _domain_agent_total_budget_sec() -> int:
    """Inner elapsed budget — stays below outer asyncio.wait_for timeout."""
    from core.config import get_settings

    outer_timeout = get_settings().wiki.domain_agent_timeout_sec
    if not isinstance(outer_timeout, int):
        outer_timeout = _DEFAULT_DOMAIN_AGENT_TIMEOUT_SEC
    return max(1, outer_timeout - _DOMAIN_AGENT_INNER_MARGIN_SEC)


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

    overview = sections[0] if not sections[0].startswith("## ") else ""
    body_sections = sections[1:] if overview else sections

    # Merge adjacent small sections (combined < 1000 tokens)
    merged: list[str] = []
    buf = ""
    for section in body_sections:
        if buf and (len(buf) + len(section)) // 4 < 1000:
            buf += "\n" + section
        else:
            if buf:
                merged.append(buf)
            buf = section
    if buf:
        merged.append(buf)

    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in merged:
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
        child_links.append(f"- [[{domain_slug}/{section_title}]]")

    if not overview.strip():
        overview = f"# {display}\n\n"
    parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_slug, display)

    return [parent_page, *child_pages]


def _extract_executive_summary(content: str, max_len: int = 300) -> str:
    """Extract the first non-heading paragraph as executive summary."""
    if not content:
        return ""
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("|"):
            continue
        if stripped.startswith("-") or stripped.startswith("*"):
            continue
        return stripped[:max_len]
    return ""


def _inject_executive_summaries(pages: list[dict[str, Any]]) -> None:
    for page in pages:
        if "metadata" not in page:
            page["metadata"] = {}
        if not page["metadata"].get("executive_summary"):
            page["metadata"]["executive_summary"] = _extract_executive_summary(
                page.get("content", "")
            )


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


class DomainDocAgent(DocOrchestrator):
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
        repo_paths: dict[str, str] | None = None,
        search_service: Any | None = None,
        budget_resolver: Any | None = None,
    ) -> None:
        from core.config import get_settings
        from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM, AGENT_WRITE_SYSTEM

        wiki_cfg = get_settings().wiki
        explore_rounds = wiki_cfg.domain_agent_explore_max_rounds
        explore_tool_calls = wiki_cfg.domain_agent_explore_max_tool_calls

        page_agent = WikiPageAgent(
            llm,
            graph_store,
            max_rounds=explore_rounds,
            max_tool_calls=explore_tool_calls,
            repo_path=repo_path,
            search_service=search_service,
        )
        super().__init__(
            agent=page_agent,
            name=domain_name,
            max_iterations=max_iterations,
            explore_system_prompt=AGENT_EXPLORE_SYSTEM.format(max_rounds=explore_rounds),
            write_system_prompt=AGENT_WRITE_SYSTEM,
        )
        self.domain_name = domain_name
        self.domain_display_name = domain_display_name or domain_name
        self._repo_paths = repo_paths or {}
        self._page_agent = page_agent
        self._budget_resolver = budget_resolver
        self._valid_pairs: list[str] | None = None
        self.iteration_history: list[dict[str, Any]] = []
        self._output_guardrail = OutputGuardrailChain([
            FormatCheck(),
            CoverageCheck(),
            LengthCheck(),
        ])

    # --- Hook 1: pre_fill ---
    async def pre_fill(
        self,
        memory: Any,
        module_names: list[str],
        *,
        valid_pairs: list[str] | None = None,
    ) -> None:
        """Seed code snippets from graph before exploration."""
        graph = self._page_agent._graph
        if not graph or not module_names:
            return
        try:
            from wiki.cypher_queries import CHUNK_SNIPPETS_CY, SNIPPETS_CY

            pairs = list(valid_pairs if valid_pairs is not None else self._valid_pairs or [])
            bare_names = [str(name) for name in module_names if "|" not in str(name)]
            for name in module_names:
                compound = str(name)
                if "|" in compound and compound not in pairs:
                    pairs.append(compound)
            query_params = {"names": bare_names or [str(n) for n in module_names], "valid_pairs": pairs}

            result = await graph.execute_query(SNIPPETS_CY, query_params)
            for row in (getattr(result, "data", None) or []):
                func_name = str(row.get("func_name", ""))
                snippet = str(row.get("snippet", "")).strip()
                file_path = str(row.get("file_path", ""))
                if snippet and hasattr(memory, "code_snippets"):
                    memory.code_snippets.append(f"[{func_name} @ {file_path}]\n{snippet}")
            if hasattr(memory, "code_snippets") and not memory.code_snippets:
                result = await graph.execute_query(CHUNK_SNIPPETS_CY, query_params)
                for row in (getattr(result, "data", None) or []):
                    entity_name = str(row.get("entity_name", ""))
                    snippet = str(row.get("snippet", "")).strip()
                    if snippet:
                        memory.code_snippets.append(f"[{entity_name}]\n{snippet}")
                        if len(memory.code_snippets) >= 6:
                            break
        except Exception:
            log.warning("pre_fill_snippets_failed", domain=self.domain_name, exc_info=True)

    # --- Hook 2: evaluate ---
    async def evaluate(self, content: str, module_names: list[str]) -> QualityResult:
        """Evaluate generated content quality via coverage + citation metrics."""
        qr = evaluate_quality(content, module_names)
        return QualityResult(
            coverage=qr.coverage,
            citation_density=qr.citation_density,
            context_gap_count=qr.context_gap_count,
            uncovered_modules=qr.uncovered_modules,
            implementation_depth=qr.implementation_depth,
        )

    # --- Hook 3: is_acceptable ---
    def is_acceptable(self, quality: QualityResult, iteration: int) -> bool:
        """Determine if quality is good enough to stop iterating."""
        if (
            quality.coverage >= 0.95
            and quality.citation_density >= 0.5
            and quality.context_gap_count == 0
        ):
            return True
        if iteration >= 2 and quality.coverage >= 0.9 and quality.citation_density >= 0.3:
            return True
        if iteration >= 3:
            return True
        return False

    # --- Hook 4: post_process ---
    def post_process(
        self, content: str, module_names: list[str], memory: Any
    ) -> list[dict[str, Any]]:
        """Structure output into page dicts with optional splitting."""
        if not content:
            content = self._page_agent._generate_skeleton(module_names, self.domain_name)

        pages = _maybe_split(content, self.domain_name, self.domain_display_name)

        if hasattr(memory, "discovered_entity_uids") and memory.discovered_entity_uids:
            entity_uids = list(memory.discovered_entity_uids)
            log.info(
                "entity_uids_from_explore",
                domain=self.domain_name,
                uid_count=len(entity_uids),
            )
            for page in pages:
                page["covered_entity_uids"] = entity_uids
        return pages

    # --- Backward-compatible internal helper (renamed from _pre_fill_snippets) ---
    async def _pre_fill_snippets(
        self,
        memory: WorkingMemory,
        module_names: list[str],
        *,
        valid_pairs: list[str] | None = None,
    ) -> None:
        """Backward compat: delegates to pre_fill hook."""
        await self.pre_fill(memory, module_names, valid_pairs=valid_pairs)

    async def _plan_topics(
        self,
        module_names: list[str],
        memory: WorkingMemory,
    ) -> DomainTopicOutline:
        """Plan topic structure via single LLM call after explore phase."""
        if len(module_names) <= 5:
            return DomainTopicOutline(
                should_split=False,
                topics=[TopicPlan(
                    title=self.domain_display_name,
                    modules=list(module_names),
                    description=f"{self.domain_display_name} overview",
                )],
            )

        from wiki.agent_prompts import SYSTEM_TOPIC_PLANNER

        module_list = "\n".join(f"- {m}" for m in module_names)
        call_info = "\n".join(memory.discovered_call_chains[:20]) if memory.discovered_call_chains else "No call chain data available."

        user_prompt = (
            f"## Domain: {self.domain_display_name}\n\n"
            f"## Module List ({len(module_names)} modules)\n{module_list}\n\n"
            f"## Key Call Relationships\n{call_info}\n"
        )
        messages = [
            {"role": "system", "content": SYSTEM_TOPIC_PLANNER},
            {"role": "user", "content": user_prompt},
        ]

        try:
            llm = self._page_agent._llm
            from wiki.token_budget import resolve_max_tokens

            plan_tokens = resolve_max_tokens(self._budget_resolver, "topic_plan")
            if hasattr(llm, "complete_json"):
                result = await llm.complete_json(messages, {}, max_tokens=plan_tokens)
                if isinstance(result, dict):
                    raw = json.dumps(result, ensure_ascii=False)
                else:
                    raw = str(result)
            else:
                raw = await llm.generate(
                    user_prompt, system=SYSTEM_TOPIC_PLANNER, max_tokens=plan_tokens,
                )
                raw = str(raw)
            outline = _parse_topic_outline(raw)
            if outline:
                log.info("plan_topics_success", domain=self.domain_name, topics=len(outline.topics))
                return outline
        except Exception:
            log.warning("plan_topics_failed", domain=self.domain_name, exc_info=True)

        return DomainTopicOutline(
            should_split=False,
            topics=[TopicPlan(
                title=self.domain_display_name,
                modules=list(module_names),
                description=f"{self.domain_display_name} overview",
            )],
        )

    async def _write_with_outline(
        self,
        outline: DomainTopicOutline,
        baseline_context: str,
        memory: WorkingMemory,
        module_names: list[str],
    ) -> list[dict[str, Any]]:
        """Write pages according to topic outline."""
        if not outline.should_split or len(outline.topics) <= 1:
            content = await self._page_agent.write(
                self.domain_name, baseline_context, memory,
            )
            content = await self._verify_code_blocks(content, memory)
            pages = _maybe_split(content, self.domain_name, self.domain_display_name)
            _inject_executive_summaries(pages)
            return pages

        from wiki.path_conventions import domain_topic_path

        topic_pages: list[dict[str, Any]] = []
        topic_links: list[str] = []

        for topic in outline.topics:
            topic_module_list = ", ".join(topic.modules)
            topic_context = (
                f"{baseline_context}\n\n"
                f"--- TOPIC SCOPE ---\n"
                f"You are writing the \"{topic.title}\" section.\n"
                f"Focus ONLY on these modules: {topic_module_list}\n"
                f"Description: {topic.description}\n"
            )
            topic_content = await self._page_agent.write(
                self.domain_name, topic_context, memory,
            )
            topic_content = await self._verify_code_blocks(topic_content, memory)
            topic_path = domain_topic_path(self.domain_name, topic.title)
            topic_pages.append({
                "page_type": "topic",
                "title": topic.title,
                "path": topic_path,
                "content": topic_content,
                "diagrams": [],
                "source_locations": [],
                "metadata": {
                    "node_count": len(topic.modules),
                    "edge_count": 0,
                    "generation_mode": "agent",
                },
                "business_domain": self.domain_name,
            })
            topic_links.append(f"- [[{self.domain_name}/{topic.title}]]")

        overview_content = (
            f"# {self.domain_display_name}\n\n"
            + "\n".join(
                f"## {t.title}\n{t.description}\n"
                for t in outline.topics
            )
            + "\n## 章节导航\n\n" + "\n".join(topic_links)
        )
        overview_page = _make_page(overview_content, self.domain_name, self.domain_display_name)

        pages = [overview_page, *topic_pages]
        _inject_executive_summaries(pages)
        return pages

    async def generate_with_iterations(
        self,
        module_names: list[str],
        baseline_context: str,
        *,
        valid_pairs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate domain documentation with Explore → Write → Quality loop.

        Each phase (explore, write) has its own timeout. Write retries once
        on first timeout. A total elapsed-time budget prevents runaway loops.
        """
        warnings.warn(
            "DomainDocAgent.generate_with_iterations() is deprecated; "
            "prefer DocOrchestrator.generate() via use_orchestrator_template.",
            DeprecationWarning,
            stacklevel=2,
        )
        from core.config import get_settings

        wiki_cfg = get_settings().wiki
        if wiki_cfg.use_orchestrator_template:
            self._valid_pairs = valid_pairs
            pages = await self.generate(module_names, baseline_context)
            _inject_executive_summaries(pages)
            return pages

        start_time = time.monotonic()
        total_budget = _domain_agent_total_budget_sec()
        loop = asyncio.get_running_loop()
        t0 = loop.time()

        def _remaining() -> float:
            return max(0, total_budget - (loop.time() - t0))

        memory = WorkingMemory()
        await self._pre_fill_snippets(memory, module_names, valid_pairs=valid_pairs)
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

        # Topic planning after explore
        outline = await self._plan_topics(module_names, memory)
        memory.topic_outline = outline

        # Early branch: if topic planning says split, skip monolithic write loop
        if outline.should_split and len(outline.topics) > 1:
            pages = await self._write_with_outline(
                outline, baseline_context, memory, module_names,
            )

            from core.config import get_settings

            wiki_cfg = get_settings().wiki
            if wiki_cfg.topic_split_quality_check and _remaining() > 30:
                for page in pages:
                    content = page.get("content", "")
                    page_modules = page.get("metadata", {}).get("covered_modules", module_names)
                    quality = evaluate_quality(content, page_modules)
                    if quality.coverage < wiki_cfg.domain_agent_early_exit_quality:
                        log.info(
                            "topic_split_low_quality",
                            domain=self.domain_name,
                            topic=page.get("title", ""),
                            coverage=quality.coverage,
                        )
                        if quality.uncovered_modules and _remaining() > 20:
                            try:
                                focus_modules = quality.uncovered_modules[:5]
                                timeout = min(30, _remaining())
                                await asyncio.wait_for(
                                    self._page_agent.explore(
                                        module_names=focus_modules,
                                        domain_name=self.domain_name,
                                        baseline_context=baseline_context,
                                        memory=memory,
                                    ),
                                    timeout=timeout,
                                )
                            except (asyncio.TimeoutError, TimeoutError):
                                pass

            if memory.discovered_entity_uids:
                entity_uids = list(memory.discovered_entity_uids)
                for page in pages:
                    page["covered_entity_uids"] = entity_uids
            _inject_executive_summaries(pages)
            return pages

        if not module_names:
            content = await self._page_agent.write(
                self.domain_name,
                baseline_context,
                memory,
            )
            content = await self._verify_code_blocks(content, memory)
            pages = _maybe_split(content, self.domain_name, self.domain_display_name)
            if memory.discovered_entity_uids:
                entity_uids = list(memory.discovered_entity_uids)
                for page in pages:
                    page["covered_entity_uids"] = entity_uids
            _inject_executive_summaries(pages)
            return pages

        content = ""
        write_timeout_count = 0
        quality = None

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
                content = await self._verify_code_blocks(content, memory)
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
            from core.config import get_settings

            early_exit = get_settings().wiki.domain_agent_early_exit_quality
            min_chars = get_settings().wiki.domain_agent_early_exit_min_chars
            if (
                quality.coverage >= early_exit
                and quality.citation_density >= 0.3
                and len(content or "") >= min_chars
            ):
                self.iteration_history.append({
                    "iteration": iteration,
                    "coverage": quality.coverage,
                    "citation_density": quality.citation_density,
                    "context_gaps": quality.context_gap_count,
                    "uncovered_count": len(quality.uncovered_modules),
                })
                log.info(
                    "agent_early_exit",
                    domain=self.domain_name,
                    coverage=quality.coverage,
                    citation=quality.citation_density,
                )
                break

            guardrail_result = await self._output_guardrail.evaluate(
                content, {"module_names": module_names}
            )
            log.info(
                "output_guardrail_result",
                domain=self.domain_name,
                iteration=iteration,
                passed=guardrail_result.passed,
                score=guardrail_result.total_score,
            )
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
                depth=getattr(quality, "implementation_depth", 0),
            )

            if (
                quality.coverage >= 0.95
                and quality.citation_density >= 0.5
                and getattr(quality, "implementation_depth", 1.0) >= 0.6
                and quality.context_gap_count == 0
            ):
                log.info("quality_perfect_exit", domain=self.domain_name, iteration=iteration)
                break

            if (
                iteration >= 2
                and quality.coverage >= 0.9
                and quality.citation_density >= 0.3
                and getattr(quality, "implementation_depth", 1.0) >= 0.4
            ):
                log.info(
                    "quality_acceptable_exit",
                    domain=self.domain_name,
                    iteration=iteration,
                    coverage=quality.coverage,
                    citation_density=quality.citation_density,
                )
                break

            if iteration >= 4:
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

        _inject_executive_summaries(pages)

        try:
            covered = [m for m in module_names if m.lower() in (content or "").lower()]
            trace = AgentTrace(
                domain=self.domain_name,
                page_title=self.domain_display_name or self.domain_name,
                timestamp=datetime.now(timezone.utc),
                explore_rounds=len(self.iteration_history),
                tools_called=[],
                quality_score=quality.coverage if quality else 0.0,
                modules_expected=module_names,
                modules_covered=covered,
                generation_time_ms=int((time.monotonic() - start_time) * 1000),
            )
            collector = TraceCollector()
            await collector.record(trace)
        except Exception:
            log.warning("trace_collection_failed", domain=self.domain_name, exc_info=True)

        return pages
