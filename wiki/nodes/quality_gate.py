"""Quality gate node for wiki page evaluation."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.citation_verifier import verify_citations
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.models import ImportanceTier, WikiPage
from wiki.pipeline_concurrency import PipelineConcurrency
from wiki.pipeline_state import WikiPipelineState
from wiki.quality_evaluator import WikiQualityEvaluator

log = get_logger(__name__)

_SCORE_KEYS = frozenset({"l1_structural", "l2_bench", "l3_llm_judge"})


async def _evaluate_l3(
    page_path: str,
    page: WikiPage,
    page_dict: dict[str, Any],
    llm: Any,
    check_cache: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    harness_eval = WikiPageEvaluator()
    page_modules = page_dict.get("entity_uids") or [page.title or page.path]
    l3_result = await harness_eval.evaluate_l3(page.content, page_modules, llm)
    l3_scores: dict[str, Any] = {}
    if l3_result.dimensions:
        avg_1_5 = sum(l3_result.dimensions.values()) / len(l3_result.dimensions)
        l3_scores["l3_llm_judge"] = round((avg_1_5 - 1.0) / 4.0, 4)
        l3_scores["l3_dimensions"] = l3_result.dimensions
    if page_path in check_cache:
        check_cache[page_path]["l3_evaluated"] = True
    return (page_path, l3_scores)


def _compute_overall(score_dict: dict[str, Any]) -> float:
    numeric_scores = [
        v
        for k, v in score_dict.items()
        if k in _SCORE_KEYS and isinstance(v, (int, float)) and v is not None
    ]
    return round(sum(numeric_scores) / len(numeric_scores), 4) if numeric_scores else 0.0


async def quality_gate_node(
    state: WikiPipelineState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Evaluate page quality with configurable L1/L2/L3 layers.

    Configuration (priority high→low):
    1. state["config"]["quality_levels"]
    2. config["configurable"]["quality_levels"]
    3. Default: ["L1", "L2"]

    Uses _structural_check_cache to skip re-evaluation when page content is
    unchanged between heal cycles.
    """
    cfg = state.get("config") or {}
    levels = (
        cfg.get("quality_levels")
        or (config or {}).get("configurable", {}).get("quality_levels")
        or ["L1", "L2"]
    )
    llm = (config or {}).get("configurable", {}).get("llm")

    evaluator = WikiQualityEvaluator()
    importance_tiers: dict[str, str] = cfg.get("importance_tiers", {})
    heal_attempts = state.get("heal_attempts", {})

    # Load or initialise structural check cache
    check_cache: dict[str, dict[str, Any]] = dict(state.get("_structural_check_cache", {}))

    quality_scores: dict[str, dict[str, Any]] = {}
    pages_to_heal: list[str] = []
    l3_candidates: list[tuple[str, WikiPage, dict[str, Any]]] = []

    all_module_names: set[str] = set()
    for repo_mods in state.get("modules", {}).values():
        for mod in repo_mods:
            mod_name = mod.get("properties", {}).get("name", "")
            if mod_name:
                all_module_names.add(mod_name)

    for page_dict in state.get("pages", []):
        try:
            page = WikiPage.from_dict(page_dict)
        except Exception:
            log.warning("quality_gate_page_parse_failed", page_data=str(page_dict)[:100])
            continue

        raw_tier = importance_tiers.get(page.path, "standard")
        try:
            tier = ImportanceTier(str(raw_tier).lower())
        except ValueError:
            tier = ImportanceTier.STANDARD

        if tier == ImportanceTier.SKELETON:
            quality_scores[page.path] = {"l1_structural": 1.0, "overall": 1.0}
            continue

        # Compute content hash for cache lookup
        content_bytes = (page.content or "").encode("utf-8", errors="replace")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        cached = check_cache.get(page.path)

        score_dict: dict[str, Any] = {}

        if cached and cached.get("content_hash") == content_hash:
            # Reuse cached L1 score
            cached_score = cached.get("score", {})
            l1_overall = cached_score.get("l1_structural", 0.0)
            score_dict["l1_structural"] = l1_overall
        else:
            # Evaluate structural check fresh
            l1 = evaluator.structural_check(page)
            score_dict["l1_structural"] = l1.overall

            # Citation verification — detect hallucinated entity references
            citation_result = verify_citations(page.content, all_module_names)
            if citation_result.invalid_count > 0:
                score_dict["citation_invalid_count"] = citation_result.invalid_count
                score_dict["citation_invalid_refs"] = citation_result.invalid_refs[:5]
                penalty = min(0.2, citation_result.invalid_count * 0.05)
                l1_adjusted = max(0.0, l1.overall - penalty)
                score_dict["l1_structural"] = round(l1_adjusted, 4)

            gap_issues = [i for i in l1.issues if i.startswith("context_gaps:")]
            if gap_issues:
                gap_count = int(gap_issues[0].split(":")[1])
                score_dict["context_gap_count"] = gap_count

            # Update cache
            check_cache[page.path] = {"score": dict(score_dict), "content_hash": content_hash}

        if "L2" in levels:
            l2 = evaluator.bench_score(page)
            score_dict["l2_bench"] = l2.overall

        score_dict["l3_llm_judge"] = None
        l1_val = score_dict.get("l1_structural", 0.0)
        was_healed = page.path in heal_attempts and heal_attempts.get(page.path, 0) > 0
        if "L3" in levels and l1_val >= 0.7:
            should_l3 = (tier == ImportanceTier.CORE) or was_healed
            l3_cache_key = check_cache.get(page.path, {}).get("l3_evaluated", False)
            if should_l3 and not l3_cache_key and llm:
                l3_candidates.append((page.path, page, page_dict))

        score_dict["overall"] = _compute_overall(score_dict)

        quality_scores[page.path] = score_dict

        threshold = 0.7 if tier == ImportanceTier.CORE else 0.5
        max_retries = 2 if tier == ImportanceTier.CORE else 1
        attempts = heal_attempts.get(page.path, 0)

        structural_score = score_dict["l1_structural"]
        if structural_score < threshold and attempts < max_retries:
            pages_to_heal.append(page.path)

    if l3_candidates and llm:
        sem = PipelineConcurrency.semaphore("quality_l3")

        async def _bounded_l3(path: str, pg: WikiPage, pd: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            async with sem:
                return await _evaluate_l3(path, pg, pd, llm, check_cache)

        l3_results = await asyncio.gather(
            *[_bounded_l3(p, pg, pd) for p, pg, pd in l3_candidates],
            return_exceptions=True,
        )
        for r in l3_results:
            if isinstance(r, tuple):
                path, l3_scores = r
                quality_scores[path].update(l3_scores)
                quality_scores[path]["overall"] = _compute_overall(quality_scores[path])
            elif isinstance(r, BaseException):
                log.warning("l3_evaluation_failed", error=str(r))

    if len(pages_to_heal) > 1:
        if "L2" in levels:
            pages_to_heal.sort(key=lambda p: quality_scores.get(p, {}).get("l2_bench", 0.0))
        else:
            pages_to_heal.sort(key=lambda p: quality_scores.get(p, {}).get("l1_structural", 0.0))

    total_gaps = sum(
        v.get("context_gap_count", 0) for v in quality_scores.values()
    )
    pages_with_gaps = sum(
        1 for v in quality_scores.values() if v.get("context_gap_count", 0) > 0
    )

    log.info(
        "quality_gate_done",
        total_pages=len(state.get("pages", [])),
        evaluated=len(quality_scores),
        to_heal=len(pages_to_heal),
        levels=levels,
        context_gaps_total=total_gaps,
        pages_with_context_gaps=pages_with_gaps,
    )
    return {
        "quality_scores": quality_scores,
        "pages_to_heal": pages_to_heal,
        "_structural_check_cache": check_cache,
    }
