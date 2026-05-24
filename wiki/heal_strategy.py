"""Heal strategy pattern: protocol, context, result, and three implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from core.log import get_logger
from wiki.context_gap import cleanup_context_gaps
from wiki.models import WikiPage

log = get_logger(__name__)


@dataclass
class HealContext:
    """Immutable input for a single heal attempt."""

    page: WikiPage
    page_dict: dict[str, Any]
    hint: str
    domain_name: str
    domain_context: str
    llm: Any
    graph_store: Any | None
    state: dict[str, Any]
    content_char_limit: int
    heal_budget: int


@dataclass
class HealResult:
    """Output of a successful heal attempt."""

    content: str
    strategy_name: str


@runtime_checkable
class HealStrategy(Protocol):
    """A single healing strategy that can be attempted on a wiki page."""

    @property
    def name(self) -> str: ...

    def can_apply(self, context: HealContext) -> bool: ...

    async def apply(self, context: HealContext) -> HealResult | None: ...


def _create_targeted_healer():
    from wiki.targeted_healer import TargetedHealer

    return TargetedHealer()


def _create_page_agent(llm, graph_store):
    from wiki.page_agent import WikiPageAgent

    return WikiPageAgent(llm, graph_store)


class TargetedHealStrategy:
    """Primary: LLM diagnosis + JSON section patches."""

    name = "targeted"

    def can_apply(self, ctx: HealContext) -> bool:
        return ctx.llm is not None

    async def apply(self, ctx: HealContext) -> HealResult | None:
        healer = _create_targeted_healer()
        result = await healer.heal(
            ctx.page,
            ctx.hint,
            ctx.llm,
            ctx.domain_context,
            content_char_limit=ctx.content_char_limit,
            max_tokens=ctx.heal_budget,
        )
        if not result:
            return None
        content = cleanup_context_gaps(result.content or "")
        if ctx.graph_store and "<!-- CONTEXT_GAP" in (result.content or "") and len(content.strip()) < 100:
            agent = _create_page_agent(ctx.llm, ctx.graph_store)
            enriched = await agent.enrich(
                content, domain_name=ctx.domain_name, existing_pages=ctx.state.get("pages")
            )
            content = cleanup_context_gaps(enriched)
        return HealResult(content=content, strategy_name=self.name)


class AgentEnrichStrategy:
    """Fallback: WikiPageAgent tool-loop exploration and enrichment."""

    name = "agent_enrich"

    def can_apply(self, ctx: HealContext) -> bool:
        return ctx.llm is not None and ctx.graph_store is not None

    async def apply(self, ctx: HealContext) -> HealResult | None:
        agent = _create_page_agent(ctx.llm, ctx.graph_store)
        content = await agent.enrich(
            ctx.page_dict.get("content", ""),
            domain_name=ctx.domain_name,
            existing_pages=ctx.state.get("pages"),
        )
        return HealResult(content=cleanup_context_gaps(content), strategy_name=self.name)


class RawLLMHealStrategy:
    """Last resort: single LLM generate call with heal prompt."""

    name = "raw_llm"

    def can_apply(self, ctx: HealContext) -> bool:
        return ctx.llm is not None

    async def apply(self, ctx: HealContext) -> HealResult | None:
        from wiki.domain_complexity import DomainComplexityScorer
        from wiki.nodes.utils import _find_domain_in_tree
        from wiki.prompts import SYSTEM_WIKI_HEAL
        from wiki.reasoning import GuidedPromptEnhancer, ReasoningLevel, TaskType, select_reasoning_level

        heal_prompt = (
            f"Improve this wiki page for domain '{ctx.domain_name}'.\n\n"
            f"Domain context: {ctx.domain_context}\n\n"
            f"Quality issues found:{ctx.hint}\n\n"
            f"Current content:\n{ctx.page_dict.get('content', '')[:ctx.content_char_limit]}\n\n"
            "Generate an improved version.\n"
        )
        scorer = DomainComplexityScorer()
        dmatch = _find_domain_in_tree(ctx.state.get("domain_tree", []) or [], ctx.domain_name)
        dmods = list(dmatch.get("modules", [])) if isinstance(dmatch, dict) else []
        heal_domain = {
            "name": ctx.domain_name,
            "biz_entities": [{"name": str(m), "methods": [], "calls": []} for m in dmods[:80]],
            "data_models": [],
        }
        metrics = scorer.score(heal_domain)
        level = select_reasoning_level(TaskType.HEAL, metrics.complexity)
        if level == ReasoningLevel.GUIDED:
            heal_prompt = GuidedPromptEnhancer().enhance_heal_prompt(heal_prompt)
        content = await ctx.llm.generate(heal_prompt, system=SYSTEM_WIKI_HEAL, max_tokens=ctx.heal_budget)
        return HealResult(content=cleanup_context_gaps(content), strategy_name=self.name)


class HealStrategyChain:
    """Execute strategies in priority order, return first successful result."""

    def __init__(self, strategies: list[HealStrategy] | None = None) -> None:
        self._strategies: list[HealStrategy] = strategies or [
            TargetedHealStrategy(),
            AgentEnrichStrategy(),
            RawLLMHealStrategy(),
        ]

    async def execute(self, context: HealContext) -> HealResult | None:
        for strategy in self._strategies:
            if not strategy.can_apply(context):
                log.debug("heal_strategy_skip", strategy=strategy.name, reason="not_applicable")
                continue
            try:
                result = await strategy.apply(context)
                if result and result.content and result.content.strip():
                    log.info("heal_strategy_success", strategy=strategy.name, page=context.page.path)
                    return result
                log.debug("heal_strategy_pass", strategy=strategy.name, page=context.page.path)
            except Exception:
                log.warning("heal_strategy_failed", strategy=strategy.name, page=context.page.path, exc_info=True)
        return None
