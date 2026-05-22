"""Quality healing node for wiki pages."""

import asyncio
import hashlib
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.context_gap import cleanup_context_gaps
from wiki.domain_complexity import DomainComplexityScorer
from wiki.models import ImportanceTier, WikiPage
from wiki.nodes.utils import _find_domain_in_tree
from wiki.page_agent import WikiPageAgent
from wiki.prompts import SYSTEM_WIKI_HEAL
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.reasoning import GuidedPromptEnhancer, ReasoningLevel, TaskType, select_reasoning_level

log = get_logger(__name__)

_MAX_HEAL_ROUNDS = 3  # Legacy constant; actual rounds now from config (heal_max_rounds_core/standard)


def _update_heal_hint(
    page_path: str,
    page_dict: dict[str, Any],
    evaluator: WikiQualityEvaluator,
    heal_hints: dict[str, str],
) -> bool:
    """Refresh ``heal_hints`` from WikiQualityBench / structural analysis (runs even without LLM)."""
    try:
        page = WikiPage.from_dict(page_dict)
        try:
            bench = evaluator.bench_score(page)
            hint = evaluator.build_heal_prompt_hint_v2(bench)
        except Exception:
            log.warning("heal_bench_score_failed", page=page_path, exc_info=True)
            score = evaluator.structural_check(page)
            hint = evaluator.build_heal_prompt_hint(score)
        heal_hints[page_path] = hint
    except Exception:
        log.warning("heal_page_analysis_failed", page=page_path, exc_info=True)
        return False
    return True


def _page_passes_post_heal(
    page: WikiPage,
    state: dict[str, Any],
    evaluator: WikiQualityEvaluator,
) -> bool:
    """Align with quality_gate_node: L1 structural score vs tier threshold."""
    cfg = state.get("config") or {}
    importance_tiers: dict[str, str] = cfg.get("importance_tiers", {})
    raw_tier = importance_tiers.get(page.path, "standard")
    try:
        tier = ImportanceTier(str(raw_tier).lower())
    except ValueError:
        tier = ImportanceTier.STANDARD
    if tier == ImportanceTier.SKELETON:
        return True
    l1 = evaluator.structural_check(page)
    threshold = 0.7 if tier == ImportanceTier.CORE else 0.5
    return l1.overall >= threshold


async def _heal_one_page(
    *,
    page_path: str,
    page_dict: dict[str, Any],
    state: dict[str, Any],
    evaluator: WikiQualityEvaluator,
    llm: Any,
    heal_hints: dict[str, str],
    heal_attempts: dict[str, int],
    graph_store: Any | None = None,
) -> bool:
    import wiki.pipeline_nodes as pn

    if not _update_heal_hint(page_path, page_dict, evaluator, heal_hints):
        return False

    page = WikiPage.from_dict(page_dict)
    hint = heal_hints[page_path]

    heal_budget = pn.TokenBudgetResolver().budget("topic_page_generate")
    content_char_limit = heal_budget * 3
    domain_name = page_dict.get("domain", "unknown")
    domain_context = ""
    dmatch = _find_domain_in_tree(state.get("domain_tree", []) or [], domain_name)
    if dmatch is not None:
        modules = dmatch.get("modules", [])
        domain_context = (
            f"Domain: {domain_name}, Modules: {', '.join(str(m) for m in modules[:10])}"
        )

    heal_prompt = (
        f"Improve this wiki page for domain '{domain_name}'.\n\n"
        f"Domain context: {domain_context}\n\n"
        f"Quality issues found:{hint}\n\n"
        f"Current content:\n{page_dict.get('content', '')[:content_char_limit]}\n\n"
        "Generate an improved version with these required sections:\n"
        "1. ## 业务概述 (business overview)\n"
        "2. ## 核心业务流程 (include Mermaid sequenceDiagram or flowchart)\n"
        "3. ## 核心服务详情 (detailed service descriptions)\n"
        "4. ## 数据模型 (data models table if applicable)\n"
        "5. ## 关联主题 ([[wiki-link]] to related domains)\n\n"
        "Requirements:\n"
        "- Include at least one Mermaid diagram\n"
        "- Use Chinese for business descriptions\n"
        "- Focus on business logic, not framework details\n"
    )
    try:
        from wiki.targeted_healer import TargetedHealer

        healer = TargetedHealer()
        targeted_result = await healer.heal(
            page,
            hint,
            llm,
            domain_context,
            content_char_limit=content_char_limit,
            max_tokens=heal_budget,
        )
        if targeted_result:
            raw_content = targeted_result.content or ""
            cleaned = cleanup_context_gaps(raw_content)
            page_dict["content"] = cleaned
            raw_has_context_gap = "<!-- CONTEXT_GAP" in raw_content
            too_short_after_clean = len(cleaned.strip()) < 100
            if graph_store is not None and (
                raw_has_context_gap and too_short_after_clean
            ):
                agent = WikiPageAgent(llm, graph_store)
                new_content = await agent.enrich(
                    page_dict["content"],
                    domain_name=domain_name,
                    existing_pages=state.get("pages"),
                )
                page_dict["content"] = cleanup_context_gaps(new_content)
            log.info("targeted_heal_success", page=page_path)
            return True
        heal_scorer = DomainComplexityScorer()
        dmods = list(dmatch.get("modules", [])) if isinstance(dmatch, dict) else []
        heal_domain = {
            "name": domain_name,
            "biz_entities": [{"name": str(m), "methods": [], "calls": []} for m in dmods[:80]],
            "data_models": [],
        }
        heal_metrics = heal_scorer.score(heal_domain)
        heal_level = select_reasoning_level(TaskType.HEAL, heal_metrics.complexity)
        fallback_prompt = heal_prompt
        if heal_level == ReasoningLevel.GUIDED:
            fallback_prompt = GuidedPromptEnhancer().enhance_heal_prompt(heal_prompt)
        if graph_store is not None:
            agent = WikiPageAgent(llm, graph_store)
            raw_for_enrich = page_dict.get("content", "")
            new_content = await agent.enrich(
                raw_for_enrich,
                domain_name=domain_name,
                existing_pages=state.get("pages"),
            )
        else:
            new_content = await llm.generate(
                fallback_prompt,
                system=SYSTEM_WIKI_HEAL,
                max_tokens=heal_budget,
            )
        page_dict["content"] = cleanup_context_gaps(new_content)
        log.info("page_healed", page=page_path, attempt=heal_attempts[page_path])
        return True
    except Exception:
        log.warning("heal_page_regen_failed", page=page_path, exc_info=True)
        return False


async def heal_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Concurrent, tier-aware page healing.

    Phase 1: Triage pages by ImportanceTier (skip SKELETON)
    Phase 2: Concurrent heal with per-tier round limits
    Phase 3: Merge results
    """
    from core.config import get_settings
    from wiki.pipeline_concurrency import PipelineConcurrency

    configurable = (config or {}).get("configurable", {})
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    wiki_cfg = get_settings().wiki
    evaluator = WikiQualityEvaluator()
    heal_attempts: dict[str, int] = dict(state.get("heal_attempts", {}))
    heal_hints: dict[str, str] = dict(state.get("heal_hints", {}))
    check_cache: dict[str, dict[str, Any]] = dict(state.get("_structural_check_cache", {}))

    # De-duplicate
    seen: set[str] = set()
    all_paths: list[str] = []
    for p in state.get("pages_to_heal", []):
        if p not in seen:
            seen.add(p)
            all_paths.append(p)

    if not all_paths:
        log.info("heal_pages_done", healed_count=0)
        return {"pages_to_heal": [], "heal_attempts": heal_attempts, "heal_hints": heal_hints, "pages": [], "_structural_check_cache": check_cache}

    # Build page lookup
    page_by_path: dict[str, dict[str, Any]] = {}
    for p in state.get("pages", []):
        path = p.get("path")
        if path in seen:
            page_by_path[str(path)] = dict(p)

    # Phase 1: Triage by tier
    # When importance_tiers is empty (production default), treat all pages as "core"
    # to preserve the original 3-round healing behavior.
    importance_tiers: dict[str, str] = (state.get("config") or {}).get("importance_tiers", {})
    core_pages: list[str] = []
    standard_pages: list[str] = []
    has_tier_info = bool(importance_tiers)

    for path in all_paths:
        raw_tier = str(importance_tiers.get(path, "")).lower() if has_tier_info else ""
        if raw_tier == "skeleton":
            continue
        elif raw_tier == "standard":
            standard_pages.append(path)
        else:
            # "core", unknown, or empty (no tier info) → treated as core for full healing
            core_pages.append(path)

    log.info(
        "heal_triage",
        total=len(all_paths),
        core=len(core_pages),
        standard=len(standard_pages),
        skipped_skeleton=len(all_paths) - len(core_pages) - len(standard_pages),
    )

    # Phase 2: Concurrent heal
    sem = PipelineConcurrency.semaphore("heal")
    healed_by_path: dict[str, dict[str, Any]] = {}

    async def _bounded_heal(page_path: str) -> bool:
        async with sem:
            page_dict = page_by_path.get(page_path)
            if not page_dict:
                return False
            heal_attempts[page_path] = heal_attempts.get(page_path, 0) + 1
            if llm:
                ok = await _heal_one_page(
                    page_path=page_path,
                    page_dict=page_dict,
                    state=state,
                    evaluator=evaluator,
                    llm=llm,
                    heal_hints=heal_hints,
                    heal_attempts=heal_attempts,
                    graph_store=graph_store,
                )
                if ok:
                    healed_by_path[page_path] = dict(page_dict)
                    # Update structural check cache for healed page
                    new_content = page_dict.get("content", "")
                    new_hash = hashlib.sha256(
                        new_content.encode("utf-8", errors="replace")
                    ).hexdigest()
                    try:
                        healed_page = WikiPage.from_dict(page_dict)
                        l1 = evaluator.structural_check(healed_page)
                        check_cache[page_path] = {
                            "score": {"l1_structural": l1.overall},
                            "content_hash": new_hash,
                        }
                    except Exception:
                        log.debug("heal_cache_update_failed", page=page_path, exc_info=True)
                return ok
            else:
                _update_heal_hint(page_path, page_dict, evaluator, heal_hints)
                return False

    async def _run_heal_tier(active: list[str], max_rounds: int, tier: str) -> list[str]:
        """Run heal rounds for a tier (core/standard), return still-failing paths."""
        for round_num in range(max_rounds):
            if not active:
                break
            results = await asyncio.gather(*[_bounded_heal(p) for p in active], return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    log.warning("heal_unhandled_exception", exc_info=r)
            failing: list[str] = []
            for p in active:
                page_dict = page_by_path.get(p)
                if not page_dict:
                    continue
                try:
                    page = WikiPage.from_dict(page_dict)
                except Exception:
                    failing.append(p)
                    continue
                if not _page_passes_post_heal(page, state, evaluator):
                    failing.append(p)
            active = failing
            if active:
                log.info("heal_tier_round", tier=tier, round=round_num + 1, still_failing=len(active))
        return active

    max_rounds_core = wiki_cfg.heal_max_rounds_core if llm else 1
    max_rounds_std = wiki_cfg.heal_max_rounds_standard if llm else 1
    active_core = await _run_heal_tier(list(core_pages), max_rounds_core, "core")
    active_std = await _run_heal_tier(list(standard_pages), max_rounds_std, "standard")

    # Phase 3: Results
    initial_paths = core_pages + standard_pages
    healed_pages = [healed_by_path[p] for p in initial_paths if p in healed_by_path]
    log.info(
        "heal_pages_done",
        healed_count=len(healed_pages),
        core_healed=len([p for p in core_pages if p in healed_by_path]),
        standard_healed=len([p for p in standard_pages if p in healed_by_path]),
        still_failing_core=len(active_core),
        still_failing_standard=len(active_std),
    )
    return {
        "pages_to_heal": [],
        "heal_attempts": heal_attempts,
        "heal_hints": heal_hints,
        "pages": healed_pages,
        "_structural_check_cache": check_cache,
    }
