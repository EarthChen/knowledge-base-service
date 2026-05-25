"""Wiki Generation Harness — Plan-Gather-Distill-Generate-Evaluate-Repair orchestrator."""
from __future__ import annotations

from core.log import get_logger
from wiki.cypher_queries import (
    CALLERS_CY,
    CHUNK_SNIPPETS_CY,
    IMPLEMENTS_CY,
    METHOD_CALL_CHAIN_CY,
    METHODS_CY,
    call_chain_cypher,
)
from wiki.domain_summary_cache import extract_summary_card
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.harness_facts import GatheredFacts
from wiki.harness_guardrails import HarnessGuardRails
from wiki.harness_planner import GenerationPlan, WikiPagePlanner
from wiki.harness_router import AdaptiveRouter, ComplexityAssessment

log = get_logger(__name__)


class WikiGenerationHarness:
    def __init__(self, agent, graph_store, llm, config=None, domain_cache=None):
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
        self.domain_cache: dict[str, str] = domain_cache if domain_cache is not None else {}

    async def run(
        self,
        domain: str,
        modules: list[str],
        ccb_context,
        **kwargs,
    ) -> str:
        # 1. Complexity assessment
        assessment = self.router.assess(modules, ccb_context)
        if self.config:
            assessment.use_l3_llm_judge = self.config.llm_judge_enabled
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
        facts = await self._gather(plan, ccb_context)

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
        if assessment.level == "complex" and len(plan.outline) > 1:
            content = await self._generate_sectional(
                plan, modules, domain, baseline, assessment
            )
        else:
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

    async def _generate_sectional(
        self,
        plan: GenerationPlan,
        modules: list[str],
        domain: str,
        baseline: str | None,
        assessment: ComplexityAssessment,
    ) -> str:
        """Generate content section-by-section for complex modules, then coherence pass."""
        sections: list[str] = []
        for section in plan.outline:
            mod_subset = (
                section.modules
                if getattr(section, "modules", None)
                else modules[:5]
            )
            section_modules = [m for m in modules if m in mod_subset]
            if not section_modules and modules:
                section_modules = modules[:5]
            section_content = await self.agent.generate(
                module_names=section_modules,
                domain_name=f"{domain} — {section.name}",
                baseline_context=baseline,
                max_rounds=3 if assessment.level == "simple" else 5,
            )
            sections.append(f"## {section.name}\n\n{section_content}")

        combined = f"# {domain}\n\n" + "\n\n---\n\n".join(sections)

        coherence_cap = assessment.budget.get("coherence_pass") or 6000
        if coherence_cap is None:
            coherence_cap = 6000
        snippet = combined[: int(coherence_cap)]

        coherence_prompt = (
            "以下 Wiki 页面由多个部分拼接而成，请检查并修复:\n"
            "1. 重复内容\n2. 矛盾信息\n3. 不连贯的过渡\n\n"
            f"{snippet}\n\n"
            "输出修正后的完整页面。"
        )
        try:
            coherent = await self.llm.generate(
                coherence_prompt, system="你是文档编辑专家。"
            )
            if coherent and len(coherent.strip()) > len(combined) * 0.5:
                return coherent
        except Exception:
            log.warning("coherence_pass_failed", domain=domain, exc_info=True)

        return combined

    async def _gather(self, plan, ccb_context=None) -> GatheredFacts:
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
                    names = self._planned_query_names(query)
                    if not names:
                        continue
                    from_ccb = self._gather_from_ccb(query.tool_name, names, ccb_context)
                    if from_ccb:
                        facts.add(section.name, query.tool_name, str(from_ccb))
                        continue
                    result = await self._execute_planned_query(query)
                    if result:
                        facts.add(section.name, query.tool_name, str(result))
                except Exception as e:
                    log.warning("harness_gather_error", tool=query.tool_name, error=str(e))

        return facts

    @staticmethod
    def _planned_query_names(query) -> list[str]:
        params = query.params
        names = list(params.get("module_names", []) or [])
        if not names:
            name = params.get("module_name") or params.get("domain_name", "")
            if name:
                names = [name]
        return names

    def _gather_from_ccb(self, tool_name: str, names: list[str], ccb) -> str | None:
        """Reuse EnrichedDomainContext (CCB) fields when they satisfy a planned graph query."""
        if ccb is None or not names:
            return None

        if tool_name == "query_module_detail":
            biz_entities = getattr(ccb, "biz_entities", None) or []
            by_name = {getattr(e, "name", None): e for e in biz_entities if getattr(e, "name", None)}
            lines: list[str] = []
            for n in names:
                ent = by_name.get(n)
                if ent is None:
                    return None
                methods = getattr(ent, "methods", None) or []
                for m in methods[:30]:
                    mod = getattr(m, "module_name", "") or n
                    fn = getattr(m, "name", "")
                    sig = getattr(m, "signature", "")
                    doc = getattr(m, "docstring", "") or ""
                    lines.append(
                        f"- {mod}.{fn}({sig})" + (f" — {doc[:100]}" if doc else ""),
                    )
            return "\n".join(lines) if lines else None

        if tool_name == "query_call_chain":
            intra = getattr(ccb, "intra_domain_calls", None) or []
            cross = getattr(ccb, "cross_domain_calls", None) or []
            mchains = getattr(ccb, "method_call_chains", None) or []
            if not intra and not cross and not mchains:
                return None
            ns = set(names)
            lines: list[str] = []

            def _step_in_scope(step) -> bool:
                ca = getattr(step, "caller", "") or ""
                ce = getattr(step, "callee", "") or ""
                if ca in ns or ce in ns:
                    return True
                for mod in ns:
                    if ca.startswith(f"{mod}.") or ce.startswith(f"{mod}."):
                        return True
                return False

            for step in list(intra) + list(cross):
                if not _step_in_scope(step):
                    continue
                ca = getattr(step, "caller", "") or ""
                ce = getattr(step, "callee", "") or ""
                cm = getattr(step, "caller_method", "") or ""
                em = getattr(step, "callee_method", "") or ""
                fn_info = ""
                if cm or em:
                    fn_info = f" [{cm},{em}]"
                lines.append(f"- {ca} → {ce}{fn_info}")
                if len(lines) >= 20:
                    break

            for mc in mchains[:30]:
                if not isinstance(mc, dict):
                    continue
                emod = str(mc.get("entry_module", "") or "")
                if emod and emod not in ns:
                    continue
                ch = mc.get("chain") or []
                if len(ch) >= 2 and isinstance(ch[0], dict) and isinstance(ch[1], dict):
                    a0, b0 = ch[0], ch[1]
                    mod = str(b0.get("module", "") or emod)
                    caller_m = str(a0.get("func", "") or "")
                    callee_m = str(b0.get("func", "") or "")
                    lines.append(f"- {mod}: {caller_m}() → {callee_m}()")
                elif emod:
                    emeth = str(mc.get("entry_method", "") or "")
                    if emeth:
                        lines.append(f"- {emod}: {emeth}() → …")

            return "\n".join(lines[:50]) if lines else None

        if tool_name in ("query_callers", "query_domain_dependencies"):
            rows = getattr(ccb, "external_callers", None) or []
            if not rows:
                return None
            ns = set(names)
            lines = []
            for r in rows[:20]:
                if not isinstance(r, dict):
                    continue
                caller = str(r.get("caller_name", "") or "")
                target = str(r.get("target_name", "") or "")
                if target not in ns:
                    continue
                prefix = "- " if tool_name == "query_callers" else "- 被调用: "
                lines.append(f"{prefix}{caller} → {target}")
            return "\n".join(lines) if lines else None

        if tool_name == "query_implementations":
            rows = getattr(ccb, "interface_impls", None) or []
            if not rows:
                return None
            ns = set(names)
            lines = []
            for r in rows[:15]:
                if not isinstance(r, dict):
                    continue
                impl = str(r.get("impl_name", "") or "")
                intf = str(r.get("interface_name", "") or "")
                mod = str(r.get("module_name", "") or "")
                if mod not in ns and impl not in ns:
                    continue
                lines.append(f"- {impl} implements {intf}")
            return "\n".join(lines) if lines else None

        if tool_name == "read_code":
            snippets = getattr(ccb, "key_snippets", None) or []
            if not snippets:
                return None
            blocks = []
            for i, block in enumerate(snippets[:10]):
                blocks.append(f"### ccb_snippet_{i}\n```java\n{block}\n```")
            return "\n".join(blocks)

        return None

    async def _execute_planned_query(self, query) -> str | None:
        """Execute a single planned query via graph_store using real Cypher queries."""
        if not self.graph_store:
            return None

        tool = query.tool_name
        params = query.params
        names = params.get("module_names", [])
        if not names:
            name = params.get("module_name") or params.get("domain_name", "")
            if name:
                names = [name]

        if not names:
            return None

        try:
            if tool == "query_module_detail":
                result = await self.graph_store.execute_query(
                    METHODS_CY, {"names": names}
                )
                rows = getattr(result, "data", None) or []
                if not rows:
                    return None
                lines = []
                for r in rows[:30]:
                    mod = r.get("module_name", "")
                    fn = r.get("func_name", "")
                    sig = r.get("signature", "")
                    doc = r.get("docstring", "")
                    lines.append(f"- {mod}.{fn}({sig})" + (f" — {doc[:100]}" if doc else ""))
                return "\n".join(lines) if lines else None

            elif tool == "query_call_chain":
                result = await self.graph_store.execute_query(
                    call_chain_cypher(3), {"names": names}
                )
                rows = getattr(result, "data", None) or []
                method_result = await self.graph_store.execute_query(
                    METHOD_CALL_CHAIN_CY, {"names": names}
                )
                method_rows = getattr(method_result, "data", None) or []
                lines = []
                for r in rows[:20]:
                    caller = r.get("caller", "")
                    callee = r.get("callee", "")
                    c_fns = r.get("caller_functions", [])
                    e_fns = r.get("callee_functions", [])
                    fn_info = ""
                    if c_fns or e_fns:
                        fn_info = f" [{','.join(c_fns[:3])} → {','.join(e_fns[:3])}]"
                    lines.append(f"- {caller} → {callee}{fn_info}")
                for r in method_rows[:30]:
                    caller_m = r.get("caller_method", "")
                    callee_m = r.get("callee_method", "")
                    mod = r.get("module_name", "")
                    lines.append(f"- {mod}: {caller_m}() → {callee_m}()")
                return "\n".join(lines) if lines else None

            elif tool == "query_callers":
                result = await self.graph_store.execute_query(
                    CALLERS_CY, {"names": names}
                )
                rows = getattr(result, "data", None) or []
                lines = []
                for r in rows[:20]:
                    caller = r.get("caller_name", "")
                    target = r.get("target_name", "")
                    lines.append(f"- {caller} → {target}")
                return "\n".join(lines) if lines else None

            elif tool == "query_implementations":
                result = await self.graph_store.execute_query(
                    IMPLEMENTS_CY, {"names": names}
                )
                rows = getattr(result, "data", None) or []
                lines = []
                for r in rows[:15]:
                    impl = r.get("impl_name", "")
                    intf = r.get("interface_name", "")
                    lines.append(f"- {impl} implements {intf}")
                return "\n".join(lines) if lines else None

            elif tool == "query_domain_dependencies":
                result = await self.graph_store.execute_query(
                    CALLERS_CY, {"names": names}
                )
                rows = getattr(result, "data", None) or []
                lines = []
                for r in rows[:15]:
                    caller = r.get("caller_name", "")
                    target = r.get("target_name", "")
                    lines.append(f"- 被调用: {caller} → {target}")
                return "\n".join(lines) if lines else None

            elif tool == "read_code":
                result = await self.graph_store.execute_query(
                    CHUNK_SNIPPETS_CY, {"names": names, "valid_pairs": []}
                )
                rows = getattr(result, "data", None) or []
                lines = []
                for r in rows[:10]:
                    entity = r.get("entity_name", "")
                    snippet = r.get("snippet", "")
                    fp = r.get("file_path", "")
                    lines.append(f"### {entity} ({fp})\n```java\n{snippet}\n```")
                return "\n".join(lines) if lines else None

            else:
                log.debug("harness_unknown_tool", tool=tool)
                return None

        except Exception as e:
            log.warning("harness_query_error", tool=tool, error=str(e))
            return None

    def _update_domain_cache(self, domain: str, modules: list[str], content: str) -> None:
        card = extract_summary_card(domain, modules, content)
        self.domain_cache[domain] = (
            f"Domain: {card.domain_name}\n"
            f"Modules: {', '.join(card.module_names[:10])}\n"
            f"Summary: {card.responsibilities}"
        )
