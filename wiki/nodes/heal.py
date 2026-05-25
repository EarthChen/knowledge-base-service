"""Quality healing node for wiki pages."""

import asyncio
import hashlib
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.llm_rate_limiter import acquire_llm_quota
from wiki.models import ImportanceTier, WikiPage
from wiki.nodes.tier_utils import resolve_tier
from wiki.nodes.utils import _find_domain_in_tree
from wiki.quality_evaluator import WikiQualityEvaluator

log = get_logger(__name__)

_MAX_HEAL_ROUNDS = 3  # Legacy constant; actual rounds now from config (heal_max_rounds_core/standard)


def _update_heal_hint(
    page_path: str,
    page_dict: dict[str, Any],
    evaluator: WikiQualityEvaluator,
    heal_hints: dict[str, str],
    check_cache: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Refresh ``heal_hints`` from WikiQualityBench / structural analysis (runs even without LLM)."""
    try:
        page = WikiPage.from_dict(page_dict)
        try:
            bench = evaluator.bench_score(page)
            hint = evaluator.build_heal_prompt_hint_v2(bench)
            if check_cache is not None:
                content_hash = hashlib.sha256(
                    (page.content or "").encode("utf-8", errors="replace")
                ).hexdigest()
                structure = getattr(bench, "structure", None)
                l1_val = structure.overall if structure is not None and hasattr(structure, "overall") else 0
                check_cache[page_path] = {
                    "score": {"l1_structural": l1_val},
                    "content_hash": content_hash,
                }
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
    check_cache: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Align with quality_gate_node: L1 structural score vs tier threshold."""
    cfg = state.get("config") or {}
    importance_tiers: dict[str, str] = cfg.get("importance_tiers", {})
    tier = resolve_tier(page.path, importance_tiers)
    if tier == ImportanceTier.SKELETON:
        return True

    content_hash = hashlib.sha256(
        (page.content or "").encode("utf-8", errors="replace")
    ).hexdigest()

    if check_cache is not None:
        cached = check_cache.get(page.path)
        if cached and cached.get("content_hash") == content_hash:
            score = cached.get("score", {})
            if isinstance(score, dict):
                l1_val = score.get("l1_structural", 0)
            else:
                l1_val = getattr(score, "overall", 0)
            threshold = 0.7 if tier == ImportanceTier.CORE else 0.5
            return l1_val >= threshold

    l1 = evaluator.structural_check(page)
    threshold = 0.7 if tier == ImportanceTier.CORE else 0.5

    if check_cache is not None:
        check_cache[page.path] = {
            "score": {"l1_structural": l1.overall},
            "content_hash": content_hash,
        }

    return l1.overall >= threshold


def _make_strategy_chain():
    from wiki.heal_strategy import HealStrategyChain

    return HealStrategyChain()


def _build_domain_context(state: dict[str, Any], page_dict: dict[str, Any]) -> str:
    domain_name = page_dict.get("domain", "unknown")
    dmatch = _find_domain_in_tree(state.get("domain_tree", []) or [], domain_name)
    if dmatch is not None:
        modules = dmatch.get("modules", [])
        return f"Domain: {domain_name}, Modules: {', '.join(str(m) for m in modules[:10])}"
    return ""


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
    check_cache: dict[str, dict[str, Any]] | None = None,
    budget_resolver: Any | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    from wiki.heal_strategy import HealContext
    from wiki.token_budget import TokenBudgetResolver

    if not _update_heal_hint(page_path, page_dict, evaluator, heal_hints, check_cache=check_cache):
        return False

    page = WikiPage.from_dict(page_dict)
    resolver = budget_resolver or TokenBudgetResolver()
    heal_budget = resolver.budget("topic_page_generate")

    ctx = HealContext(
        page=page,
        page_dict=page_dict,
        hint=heal_hints[page_path],
        domain_name=page_dict.get("domain", "unknown"),
        domain_context=_build_domain_context(state, page_dict),
        llm=llm,
        graph_store=graph_store,
        state=state,
        content_char_limit=heal_budget * 3,
        heal_budget=heal_budget,
    )

    chain = _make_strategy_chain()
    await acquire_llm_quota(config, estimated_tokens=heal_budget)
    result = await chain.execute(ctx)

    if result:
        page_dict["content"] = result.content
        log.info(
            "page_healed",
            page=page_path,
            strategy=result.strategy_name,
            attempt=heal_attempts.get(page_path, 0),
        )
        return True
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
    budget_resolver = configurable.get("budget_resolver")
    wiki_cfg = get_settings().wiki
    evaluator = WikiQualityEvaluator()
    heal_attempts: dict[str, int] = dict(state.get("heal_attempts", {}))
    heal_cycles: dict[str, int] = dict(state.get("heal_cycles", {}))
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
        return {
            "pages_to_heal": [],
            "heal_attempts": heal_attempts,
            "heal_cycles": heal_cycles,
            "heal_hints": heal_hints,
            "pages": [],
            "_structural_check_cache": check_cache,
        }

    # Build page lookup
    page_by_path: dict[str, dict[str, Any]] = {}
    for p in state.get("pages", []):
        path = p.get("path")
        if path in seen:
            page_by_path[str(path)] = dict(p)

    # Phase 1: Triage by tier (shared resolve_tier defaults to CORE when tiers empty)
    importance_tiers: dict[str, str] = (state.get("config") or {}).get("importance_tiers", {})
    core_pages: list[str] = []
    standard_pages: list[str] = []

    for path in all_paths:
        tier = resolve_tier(path, importance_tiers)
        if tier == ImportanceTier.SKELETON:
            continue
        if tier == ImportanceTier.STANDARD:
            standard_pages.append(path)
        else:
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
                    check_cache=check_cache,
                    budget_resolver=budget_resolver,
                    config=config,
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
                _update_heal_hint(page_path, page_dict, evaluator, heal_hints, check_cache=check_cache)
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
                if not _page_passes_post_heal(page, state, evaluator, check_cache=check_cache):
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
    for p in initial_paths:
        heal_cycles[p] = heal_cycles.get(p, 0) + 1

    return {
        "pages_to_heal": [],
        "heal_attempts": heal_attempts,
        "heal_cycles": heal_cycles,
        "heal_hints": heal_hints,
        "pages": healed_pages,
        "_structural_check_cache": check_cache,
    }
