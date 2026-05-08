"""Wiki Generation Harness — Plan-Gather-Distill-Generate-Evaluate-Repair orchestrator."""
from __future__ import annotations

from core.log import get_logger
from wiki.domain_summary_cache import extract_summary_card
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.harness_facts import GatheredFacts
from wiki.harness_guardrails import HarnessGuardRails
from wiki.harness_planner import WikiPagePlanner
from wiki.harness_router import AdaptiveRouter

log = get_logger(__name__)


class WikiGenerationHarness:
    def __init__(self, agent, graph_store, llm, config=None):
        self.agent = agent
        self.graph_store = graph_store
        self.llm = llm
        self.config = config
        self.router = AdaptiveRouter(
            simple_threshold=config.simple_threshold if config else 5,
            complex_threshold=config.complex_threshold if config else 15,
        )
        self.planner = WikiPagePlanner()
        self.evaluator = WikiPageEvaluator()
        self.domain_cache: dict[str, str] = {}

    async def run(
        self,
        domain: str,
        modules: list[str],
        ccb_context,
        **kwargs,
    ) -> str:
        # 1. Complexity assessment
        assessment = self.router.assess(modules, ccb_context)
        log.info(
            "harness_assess",
            domain=domain,
            level=assessment.level,
            modules=len(modules),
        )

        # 2. Plan
        plan = self.planner.plan(
            domain, modules, ccb_context, assessment,
            domain_cache=self.domain_cache,
        )

        # 3. Gather
        facts = await self._gather(plan)

        # 4. Distill
        domain_summaries = [
            self.domain_cache[d]
            for d in plan.cross_domain_refs
            if d in self.domain_cache
        ]
        distilled = facts.distill(
            complexity_level=assessment.level,
            domain_summaries=domain_summaries if domain_summaries else None,
        )

        # 5. Generate
        baseline = distilled if distilled else None
        content = await self.agent.generate(
            module_names=modules,
            domain_name=domain,
            baseline_context=baseline,
            max_rounds=3 if assessment.level == "simple" else 5,
        )

        # 6. Evaluate + Repair loop
        max_repairs = assessment.max_repair_rounds
        if self.config and self.config.max_repair_rounds < max_repairs:
            max_repairs = self.config.max_repair_rounds
        if self.config and not self.config.llm_judge_enabled:
            assessment.use_llm_judge = False
        for round_i in range(max_repairs + 1):
            eval_result = self.evaluator.evaluate(content, modules, assessment, self.llm)
            if eval_result.passed:
                break
            if round_i < max_repairs:
                log.info(
                    "harness_repair",
                    domain=domain,
                    round=round_i + 1,
                    score=eval_result.score,
                )
                content = await self.agent.repair(content, eval_result)

        # 7. Update domain cache
        self._update_domain_cache(domain, modules, content)

        return content

    async def _gather(self, plan) -> GatheredFacts:
        """Execute planned queries against graph_store. No LLM involved."""
        facts = GatheredFacts()
        guardrails = HarnessGuardRails()

        for section in plan.outline:
            for query in section.queries:
                violation = guardrails.check_tool_call(query.tool_name, query.params)
                if violation:
                    log.warning("harness_guardrail", rule=violation.rule)
                    continue
                try:
                    result = await self._execute_planned_query(query)
                    if result:
                        facts.add(section.name, query.tool_name, str(result))
                except Exception as e:
                    log.warning("harness_gather_error", tool=query.tool_name, error=str(e))

        return facts

    async def _execute_planned_query(self, query) -> str | None:
        """Execute a single planned query via graph_store."""
        if not self.graph_store:
            return None
        try:
            result = await self.graph_store.execute_query(
                f"MATCH (n) WHERE n.name IN $names RETURN n.name LIMIT 5",
                params={"names": query.params.get("module_names", [query.params.get("module_name", "")])},
            )
            if hasattr(result, "data") and result.data:
                return str(result.data[:5])
        except Exception:
            pass
        return None

    def _update_domain_cache(self, domain: str, modules: list[str], content: str) -> None:
        card = extract_summary_card(domain, modules, content)
        self.domain_cache[domain] = (
            f"Domain: {card.domain_name}\n"
            f"Modules: {', '.join(card.module_names[:10])}\n"
            f"Summary: {card.responsibilities}"
        )
