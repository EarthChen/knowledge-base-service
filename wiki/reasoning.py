"""Adaptive reasoning level selection and multi-step reasoning execution."""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from core.log import get_logger
from wiki.domain_complexity import DomainComplexity

log = get_logger(__name__)


class ReasoningLevel(str, Enum):
    NONE = "none"
    GUIDED = "guided"
    MULTI_STEP = "multi_step"


class TaskType(str, Enum):
    CLASSIFY = "classify"
    COMPOSE = "compose"
    HEAL = "heal"
    OVERVIEW = "overview"


_DEFAULT_STRATEGY: dict[TaskType, dict[DomainComplexity, ReasoningLevel]] = {
    TaskType.CLASSIFY: {
        DomainComplexity.LOW: ReasoningLevel.NONE,
        DomainComplexity.MEDIUM: ReasoningLevel.GUIDED,
        DomainComplexity.HIGH: ReasoningLevel.GUIDED,
    },
    TaskType.COMPOSE: {
        DomainComplexity.LOW: ReasoningLevel.NONE,
        DomainComplexity.MEDIUM: ReasoningLevel.GUIDED,
        DomainComplexity.HIGH: ReasoningLevel.MULTI_STEP,
    },
    TaskType.HEAL: {
        DomainComplexity.LOW: ReasoningLevel.GUIDED,
        DomainComplexity.MEDIUM: ReasoningLevel.MULTI_STEP,
        DomainComplexity.HIGH: ReasoningLevel.MULTI_STEP,
    },
    TaskType.OVERVIEW: {
        DomainComplexity.LOW: ReasoningLevel.GUIDED,
        DomainComplexity.MEDIUM: ReasoningLevel.GUIDED,
        DomainComplexity.HIGH: ReasoningLevel.MULTI_STEP,
    },
}


def select_reasoning_level(
    task_type: TaskType,
    complexity: DomainComplexity,
) -> ReasoningLevel:
    """Select reasoning level based on task type and domain complexity."""
    return _DEFAULT_STRATEGY[task_type][complexity]


class GuidedPromptEnhancer:
    """Inject structured reasoning guidance into prompts for GUIDED level.

    Scope: classify, overview, and heal prompts.
    compose GUIDED is handled by TopicPageComposer's built-in prompts.
    """

    def enhance_classify_prompt(self, prompt: str) -> str:
        guidance = (
            "Before classifying, analyze:\n"
            "1. Which modules share data models or call each other?\n"
            "2. Which modules serve the same business process?\n"
            "3. Are there modules that seem unrelated but share a common entry point?\n\n"
        )
        return guidance + prompt

    def enhance_overview_prompt(self, prompt: str) -> str:
        guidance = (
            "Before writing the overview, analyze:\n"
            "1. What are the primary business flows across domains?\n"
            "2. Which domains are tightly coupled vs loosely coupled?\n"
            "3. What is the overall system's value proposition?\n\n"
        )
        return guidance + prompt

    def enhance_heal_prompt(self, prompt: str) -> str:
        guidance = (
            "Before rewriting, analyze:\n"
            "1. What specific quality issues does this page have?\n"
            "2. Which sections are adequate and should be preserved in spirit?\n"
            "3. What missing information would most improve this page?\n\n"
        )
        return guidance + prompt


class MultiStepReasoner:
    """Execute multi-step reasoning for MULTI_STEP level."""

    _PLAN_SYSTEM = (
        "You are a technical documentation architect. "
        "Plan the structure of a wiki page. "
        "Output ONLY valid JSON. No markdown fences."
    )

    _ANALYSIS_SYSTEM = (
        "You are a senior architect analyzing cross-domain relationships. "
        "Provide a concise analysis of how domains interact."
    )

    async def plan_and_compose(
        self,
        domain: dict[str, Any],
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        """Step 1: Plan page structure → Step 2: Generate content from plan."""
        plan = await self._plan_structure(domain, llm, reasoning_effort=reasoning_effort)
        content = await self._generate_from_plan(
            domain,
            plan,
            llm,
            system=system,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return content

    async def plan_and_overview(
        self,
        domains_summary: str,
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        """Step 1: Cross-domain analysis → Step 2: Generate overview."""
        analysis = await self._analyze_domains(
            domains_summary,
            llm,
            reasoning_effort=reasoning_effort,
        )
        content = await self._generate_overview(
            domains_summary,
            analysis,
            llm,
            system=system,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return content

    async def _plan_structure(
        self,
        domain: dict[str, Any],
        llm: Any,
        **kw: Any,
    ) -> dict[str, Any]:
        name = domain.get("name", "unknown")
        entities = domain.get("biz_entities", [])
        entity_desc = "\n".join(
            f"- {e.get('name', '')}: {e.get('summary', '')} "
            f"(methods: {', '.join(e.get('methods', [])[:8])}; "
            f"calls: {', '.join(e.get('calls', [])[:5])})"
            for e in entities
        )
        prompt = (
            f"Plan the wiki page structure for domain: **{name}**\n\n"
            f"Services:\n{entity_desc}\n\n"
            "Return JSON:\n"
            '{"sections": [{"heading": "## Section Title", "key_points": ["point1", "point2"]}], '
            '"diagrams": ["description of each Mermaid diagram needed"]}\n\n'
            "Rules:\n"
            "- 3-6 sections covering: business overview (WHY), core flow, key services, interactions\n"
            "- At least 1 diagram (sequenceDiagram or flowchart)\n"
            "- Section headings in Chinese"
        )
        gen_kw: dict[str, Any] = {}
        if kw.get("reasoning_effort"):
            gen_kw["reasoning_effort"] = kw["reasoning_effort"]
        messages = [
            {"role": "system", "content": self._PLAN_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        if hasattr(llm, "complete_json"):
            try:
                plan = await llm.complete_json(messages, {}, **gen_kw)
            except (ValueError, Exception):
                log.warning("multi_step_plan_complete_json_failed", domain=name, exc_info=True)
                return {"sections": [], "diagrams": []}
            if isinstance(plan, dict) and "sections" in plan:
                return plan
            return {"sections": [], "diagrams": []}
        raw = await llm.generate(prompt, system=self._PLAN_SYSTEM, **gen_kw)
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            plan = json.loads(cleaned)
            if isinstance(plan, dict) and "sections" in plan:
                return plan
        except (json.JSONDecodeError, ValueError):
            log.warning("multi_step_plan_parse_failed", domain=name)
        return {"sections": [], "diagrams": []}

    async def _generate_from_plan(
        self,
        domain: dict[str, Any],
        plan: dict[str, Any],
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        name = domain.get("name", "unknown")
        entities = domain.get("biz_entities", [])
        entity_desc = "\n".join(f"- {e.get('name', '')}: {e.get('summary', '')}" for e in entities)

        sections = plan.get("sections", [])
        diagrams = plan.get("diagrams", [])
        if sections:
            plan_text = f"Planned structure:\n{json.dumps(sections, ensure_ascii=False, indent=2)}"
            diagram_text = ("\nPlanned diagrams:\n" + "\n".join(f"- {d}" for d in diagrams)) if diagrams else ""
        else:
            plan_text = ""
            diagram_text = ""

        prompt = (
            f"Write a wiki page for domain: **{name}**\n\n"
            f"Services:\n{entity_desc}\n\n"
            f"{plan_text}{diagram_text}\n\n"
            "Follow the planned structure above. Write each section with depth and business insight.\n"
            "Use Chinese for section headings and business descriptions.\n"
            "Include Mermaid diagrams as planned.\n"
            f"Keep response under {max_tokens} tokens."
        )
        gen_kw: dict[str, Any] = {}
        if reasoning_effort:
            gen_kw["reasoning_effort"] = reasoning_effort
        return await llm.generate(prompt, system=system, max_tokens=max_tokens, **gen_kw)

    async def _analyze_domains(self, summary: str, llm: Any, **kw: Any) -> str:
        prompt = (
            "Analyze the following domain summaries and describe:\n"
            "1. How these domains interact with each other\n"
            "2. Which domains are tightly coupled\n"
            "3. What is the overall system's architecture pattern\n\n"
            f"Domain summaries:\n{summary}"
        )
        gen_kw: dict[str, Any] = {}
        if kw.get("reasoning_effort"):
            gen_kw["reasoning_effort"] = kw["reasoning_effort"]
        return await llm.generate(prompt, system=self._ANALYSIS_SYSTEM, **gen_kw)

    async def _generate_overview(
        self,
        summary: str,
        analysis: str,
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        prompt = (
            "Generate a system architecture overview based on this analysis:\n\n"
            f"Analysis:\n{analysis}\n\n"
            f"Domain details:\n{summary}\n\n"
            "Include a Mermaid architecture diagram showing domain relationships.\n"
            f"Keep response under {max_tokens} tokens."
        )
        gen_kw: dict[str, Any] = {}
        if reasoning_effort:
            gen_kw["reasoning_effort"] = reasoning_effort
        return await llm.generate(prompt, system=system, max_tokens=max_tokens, **gen_kw)
