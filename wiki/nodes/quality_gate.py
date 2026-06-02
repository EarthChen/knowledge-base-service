"""Quality gate node for wiki page evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.config import get_settings
from core.log import get_logger
from wiki.citation_verifier import verify_citations
from wiki.content_guards import (
    count_boilerplate_hits,
    detect_hallucination_flags,
    detect_truncated_code_blocks,
    detect_unclosed_code_blocks,
    has_meta_sections,
    has_topic_overview_section,
    is_compound_module_title,
)
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.models import ImportanceTier, WikiPage
from wiki.nodes.tier_utils import resolve_tier
from wiki.pipeline_concurrency import PipelineConcurrency
from wiki.pipeline_state import WikiPipelineState
from wiki.quality_evaluator import WikiQualityEvaluator

log = get_logger(__name__)

HARD_REJECT_HALLUCINATION_FLAGS = frozenset(
    {
        "fabricated_latency_sla",
        "fabricated_sla",
        "fabricated_availability",
    }
)

_PART_N_RE = re.compile(r"- Part \d+$")
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
        v for k, v in score_dict.items() if k in _SCORE_KEYS and isinstance(v, (int, float)) and v is not None
    ]
    return round(sum(numeric_scores) / len(numeric_scores), 4) if numeric_scores else 0.0


def _is_chinese_lang(lang: str) -> bool:
    normalized = lang.lower().strip()
    return normalized in ("zh", "zh-cn", "zh-tw", "zh-hans", "chinese", "简体中文", "繁體中文") or "中文" in lang


def _detect_lang_from_content(content: str) -> str:
    """Auto-detect language from content based on Chinese character ratio."""
    text = re.sub(r"```[\s\S]*?```", "", content or "")
    if not text:
        return ""
    cn_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ratio = cn_count / len(text)
    return "zh" if ratio > 0.15 else "en"


def _check_cn_ratio(page: dict[str, Any]) -> float:
    """Estimate Chinese character ratio from page content (strips code fences)."""
    content = page.get("content", "")
    text = re.sub(r"```[\s\S]*?```", "", content)
    if len(text) < 100:
        return 1.0
    cn_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cn_count / len(text) if text else 0.0


def _extract_h2_headings(content: str) -> list[str]:
    return [line.strip() for line in (content or "").split("\n") if line.startswith("## ")]


@dataclass
class H2Issue:
    code: str
    message: str
    severity: str = "warning"


def _check_h2_structure(content: str, page_type: str) -> H2Issue | None:
    """Check that content has sufficient H2 sections for its page type.

    - topic pages need >= 3 H2 sections
    - overview pages need >= 2 H2 sections
    """
    lines = content.split("\n")
    in_fence = False
    h2_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("## "):
            h2_count += 1

    min_required = 3 if page_type == "topic" else 2

    if h2_count < min_required:
        return H2Issue(
            code="h2_insufficient",
            message=f"Page type '{page_type}' has {h2_count} H2 sections, needs >= {min_required}",
            severity="warning",
        )
    return None


_DIAGRAM_ONLY_LANGS = frozenset({"mermaid", "plantuml"})


def _has_non_mermaid_code_block(content: str) -> bool:
    """Return True if content has a fenced code block that is not mermaid/plantuml."""
    lines = (content or "").split("\n")
    in_fence = False
    fence_lang = ""
    for line in lines:
        stripped = line.strip()
        if not in_fence:
            if stripped.startswith("```") and len(stripped) >= 3:
                in_fence = True
                lang = stripped[3:].strip().lower()
                fence_lang = lang.split()[0] if lang else ""
            continue
        if stripped == "```":
            if fence_lang not in _DIAGRAM_ONLY_LANGS:
                return True
            in_fence = False
            fence_lang = ""
            continue
    return False


def _check_min_content_length(
    page: dict[str, Any],
    overview_min: int | None = None,
    topic_min: int | None = None,
) -> dict[str, Any]:
    """Check if page content meets minimum length threshold."""
    if overview_min is None:
        overview_min = get_settings().wiki.overview_min_content_chars
    if topic_min is None:
        topic_min = get_settings().wiki.topic_min_content_chars
    content = str(page.get("content") or "")
    page_type = str(page.get("page_type") or "")
    content_len = len(content)

    if page_type == "domain_overview":
        threshold = overview_min
    elif page_type == "topic":
        threshold = topic_min
    else:
        threshold = 500

    return {
        "below_threshold": content_len < threshold,
        "content_len": content_len,
        "threshold": threshold,
        "page_type": page_type,
    }


async def quality_gate_node(state: WikiPipelineState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Evaluate page quality with configurable L1/L2/L3 layers.

    Configuration (priority high→low):
    1. state["config"]["quality_levels"]
    2. config["configurable"]["quality_levels"]
    3. Default: ["L1", "L2"]

    Uses _structural_check_cache to skip re-evaluation when page content is
    unchanged between heal cycles.

    Heal counters (paired with ``heal_pages_node`` and ``should_heal``):
    - ``heal_attempts[page]``: total inner-round attempts across all cycles.
    - ``heal_cycles[page]``: outer quality-gate → heal loop iterations; used here
      to decide whether a page may enter another heal cycle.
    """
    cfg = state.get("config") or {}
    levels = cfg.get("quality_levels") or (config or {}).get("configurable", {}).get("quality_levels") or ["L1", "L2"]
    llm = (config or {}).get("configurable", {}).get("llm")

    wiki_cfg = get_settings().wiki
    evaluator = WikiQualityEvaluator()
    importance_tiers: dict[str, str] = cfg.get("importance_tiers", {})
    heal_attempts = state.get("heal_attempts", {})
    heal_cycles: dict[str, int] = dict(state.get("heal_cycles", {}))

    # Load or initialise structural check cache
    check_cache: dict[str, dict[str, Any]] = dict(state.get("_structural_check_cache", {}))
    heal_hints: dict[str, str] = dict(state.get("heal_hints", {}))

    quality_scores: dict[str, dict[str, Any]] = {}
    pages_to_heal: list[str] = []
    l3_candidates: list[tuple[str, WikiPage, dict[str, Any]]] = []

    all_module_names: set[str] = set()
    for repo_mods in state.get("modules", {}).values():
        for mod in repo_mods:
            props = mod.get("properties", {}) or {}
            mod_name = props.get("name", "")
            repo = props.get("repository", "")
            if mod_name:
                all_module_names.add(mod_name)
                if repo:
                    all_module_names.add(f"{repo}|{mod_name}")

    for page_dict in state.get("pages", []):
        gen_mode = page_dict.get("metadata", {}).get("generation_mode", "")
        if gen_mode in ("agent_error", "error_fallback"):
            page_path = page_dict.get("path", "")
            quality_scores[page_path] = {
                "l1_structural": 0.0,
                "overall": 0.0,
                "skipped_reason": gen_mode,
            }
            cycles = heal_cycles.get(page_path, 0)
            max_heal = wiki_cfg.agent_error_heal_max_cycles
            if cycles < max_heal:
                pages_to_heal.append(page_path)
            continue

        try:
            page = WikiPage.from_dict(page_dict)
        except Exception:
            log.warning("quality_gate_page_parse_failed", page_data=str(page_dict)[:100])
            continue

        tier = resolve_tier(page.path, importance_tiers)

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

        is_topic_index = page_dict.get("metadata", {}).get("overview_kind") == "topic_index"
        length_result = _check_min_content_length(page_dict)
        below_min = length_result["below_threshold"] and not is_topic_index
        score_dict["below_min_length"] = below_min
        if below_min:
            heal_hints[page.path] = (
                f"Content too short ({length_result['content_len']} < {length_result['threshold']} chars)"
            )

        low_cn_ratio = False
        page_type = str(page_dict.get("page_type") or "")
        content_language = str(page_dict.get("content_language") or "")
        if page_type == "topic":
            effective_lang = content_language or _detect_lang_from_content(page_dict.get("content", ""))
            if _is_chinese_lang(effective_lang):
                cn_ratio = _check_cn_ratio(page_dict)
                cn_threshold = getattr(wiki_cfg, "language_guardrail_cn_ratio", 0.15)
                score_dict["cn_ratio"] = round(cn_ratio, 3)
                if cn_ratio < cn_threshold:
                    low_cn_ratio = True
                    score_dict["low_cn_ratio"] = True
                    log.warning(
                        "quality_gate_low_cn_ratio",
                        title=page_dict.get("title"),
                        cn_ratio=round(cn_ratio, 3),
                        threshold=cn_threshold,
                    )
                    page_dict.setdefault("metadata", {})["heal_reason"] = f"low_cn_ratio_{cn_ratio:.3f}"
                    heal_hints[page.path] = (
                        f"Chinese content ratio too low ({cn_ratio:.1%} < {cn_threshold:.0%}); "
                        "regenerate with stronger Chinese prompts"
                    )

        content_issues: list[str] = []
        page_content = page_dict.get("content", "")

        page_title = page_dict.get("title", "")
        if _PART_N_RE.search(page_title):
            content_issues.append("part_n_title: Title uses mechanical 'Part N' naming, should use semantic title")

        if is_compound_module_title(page_title):
            log.warning("quality_gate_compound_module_title", title=page_title)
            content_issues.append(
                "compound_module_title: title uses repo/path|ClassName compound key, should use semantic title"
            )
            page_dict.setdefault("metadata", {})["heal_reason"] = "compound_module_title"
            score_dict["compound_module_title"] = True
            l1_val = score_dict.get("l1_structural", 1.0)
            score_dict["l1_structural"] = round(min(l1_val, 0.4), 4)
            heal_hints[page.path] = (
                f"Compound module title detected; regenerate page with semantic title (current: {page_title})"
            )

        min_chars = 500 if page_type == "topic" else 1000
        if len(page_content.strip()) < min_chars:
            content_issues.append(
                f"content_too_short: Page only has {len(page_content.strip())} chars (min: {min_chars})"
            )

        hallucination_flags = detect_hallucination_flags(page_content)
        hard_hallucination_flags = [f for f in hallucination_flags if f in HARD_REJECT_HALLUCINATION_FLAGS]
        soft_hallucination_flags = [f for f in hallucination_flags if f not in HARD_REJECT_HALLUCINATION_FLAGS]
        if soft_hallucination_flags:
            log.warning(
                "quality_gate_hallucination",
                title=page_dict.get("title"),
                flags=soft_hallucination_flags,
            )
        if hard_hallucination_flags:
            log.warning(
                "quality_gate_hallucination_hard",
                title=page_dict.get("title"),
                flags=hard_hallucination_flags,
            )
            content_issues.append(f"hallucination_hard: {hard_hallucination_flags}")
            heal_hints[page.path] = "; ".join(
                filter(
                    None,
                    [
                        heal_hints.get(page.path, ""),
                        "Remove fabricated SLA/performance metrics",
                    ],
                )
            )

        bp_count = count_boilerplate_hits(page_content)
        if bp_count >= 2:
            log.warning("quality_gate_boilerplate", title=page_dict.get("title"), count=bp_count)
            content_issues.append(f"boilerplate: {bp_count} hits")

        if has_meta_sections(page_content):
            log.warning("quality_gate_meta_section", title=page_dict.get("title"))
            content_issues.append("meta_section_leak")

        if page_type == "module_overview":
            if "_No nested graph children_" in page_content and len(page_content) > 2000:
                content_issues.append("sparse_module_over_inflated")

            effective_lang = content_language or _detect_lang_from_content(page_content)
            if _is_chinese_lang(effective_lang):
                module_cn_ratio = _check_cn_ratio(page_dict)
                score_dict["cn_ratio"] = round(module_cn_ratio, 3)
                if module_cn_ratio < 0.35:
                    log.warning(
                        "quality_gate_module_overview_low_cn_ratio",
                        title=page_dict.get("title"),
                        cn_ratio=round(module_cn_ratio, 3),
                        threshold=0.35,
                    )
                    content_issues.append(f"module_overview_low_cn: cn={module_cn_ratio:.3f} < 0.35")

        if page_type == "domain_overview":
            effective_lang = content_language or _detect_lang_from_content(page_content)
            cn_ratio_val: float | None = None
            if _is_chinese_lang(effective_lang):
                cn_ratio_val = _check_cn_ratio(page_dict)
                if cn_ratio_val < 0.20:
                    log.warning(
                        "quality_gate_overview_low_cn_ratio",
                        title=page_dict.get("title"),
                        cn_ratio=round(cn_ratio_val, 3),
                        threshold=0.20,
                    )
                    content_issues.append(f"overview_low_cn_ratio: cn={cn_ratio_val:.3f} < 0.20")

            code_fences = re.findall(r"^```", page_content, re.MULTILINE)
            code_block_count = len(code_fences) // 2
            if code_block_count > 5:
                if cn_ratio_val is None:
                    cn_ratio_val = _check_cn_ratio(page_dict) if _is_chinese_lang(effective_lang) else 1.0
                if cn_ratio_val < 0.20:
                    content_issues.append(
                        f"overview_code_overload: {code_block_count} code blocks with cn_ratio={cn_ratio_val:.3f}"
                    )

            h2_headings = _extract_h2_headings(page_content)
            if len(page_content) < 500 and len(h2_headings) == 1:
                log.warning(
                    "quality_gate_shell_domain",
                    title=page_dict.get("title"),
                    content_len=len(page_content),
                    h2=h2_headings[0],
                )
                content_issues.append("shell_domain_overview: content too thin, only 1 section")

        if page_type == "topic" and not is_topic_index and not _has_non_mermaid_code_block(page_content):
            log.warning("quality_gate_topic_no_code", title=page_dict.get("title"))
            content_issues.append("topic_no_code: topic has no code examples")

        if page_type == "topic" and not is_topic_index and not has_topic_overview_section(page_content):
            log.warning("quality_gate_missing_overview", title=page_dict.get("title"))
            content_issues.append("missing_overview: topic lacks ## 概述 section; add overview before other sections")

        h2_issue = _check_h2_structure(page_content, page_type or "topic")
        if h2_issue:
            content_issues.append(f"h2_structure: {h2_issue.message}")

        truncated = detect_truncated_code_blocks(page_content)
        unclosed_blocks = detect_unclosed_code_blocks(page_content)
        if truncated or unclosed_blocks:
            block_count = len(truncated) if truncated else 1
            log.warning(
                "quality_gate_truncated_code",
                title=page_dict.get("title"),
                count=block_count,
            )
            content_issues.append(
                f"CODE_TRUNCATED: {block_count} unclosed code block(s) detected. "
                "Ensure all code blocks have matching closing ``` fences and are complete."
            )

        page_quality_flags = page_dict.get("quality_flags") or []
        if "FORCED_ACCEPT" in page_quality_flags:
            content_issues.append("agent_forced_accept: documentation accepted at minimum agent quality threshold")

        if content_issues:
            existing = heal_hints.get(page.path, "")
            combined = "; ".join(filter(None, [existing, *content_issues]))
            heal_hints[page.path] = combined

        score_dict["overall"] = _compute_overall(score_dict)

        quality_scores[page.path] = score_dict

        threshold = 0.7 if tier == ImportanceTier.CORE else 0.5
        max_retries = 2 if tier == ImportanceTier.CORE else 1
        cycles = heal_cycles.get(page.path, 0)

        structural_score = score_dict["l1_structural"]
        l2_val = score_dict.get("l2_bench", 1.0)
        l2_below = (l2_val < wiki_cfg.heal_l2_threshold) if wiki_cfg.heal_l2_threshold > 0 and "L2" in levels else False
        below_min_len = score_dict.get("below_min_length", False)
        has_content_issues = any(i for i in content_issues if not i.startswith("agent_forced_accept:"))
        forced_low_quality = "FORCED_LOW_QUALITY" in page_quality_flags
        if forced_low_quality and cycles < max_retries and page.path not in pages_to_heal:
            pages_to_heal.append(page.path)
        elif (
            (structural_score < threshold or l2_below or below_min_len or low_cn_ratio or has_content_issues)
            and cycles < max_retries
            and page.path not in pages_to_heal
        ):
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

        if wiki_cfg.heal_on_l3_failure and "L3" in levels:
            for page_path, score_dict in quality_scores.items():
                l3_val = score_dict.get("l3_llm_judge")
                if l3_val is None:
                    continue
                tier_str = resolve_tier(page_path, importance_tiers)
                if tier_str == ImportanceTier.SKELETON:
                    continue
                l3_threshold = wiki_cfg.heal_l3_threshold
                max_retries = 2 if tier_str == ImportanceTier.CORE else 1
                cycles = heal_cycles.get(page_path, 0)
                if l3_val < l3_threshold and cycles < max_retries and page_path not in pages_to_heal:
                    pages_to_heal.append(page_path)

    domains_with_overview: set[str] = set()
    domains_with_topics: set[str] = set()
    for page_dict in state.get("pages", []):
        bd = str(page_dict.get("business_domain") or "").strip()
        if not bd:
            continue
        page_type = str(page_dict.get("page_type") or "")
        if page_type == "domain_overview":
            domains_with_overview.add(bd)
        elif page_type == "topic":
            domains_with_topics.add(bd)
    for domain_slug in domains_with_overview - domains_with_topics:
        log.warning(
            "quality_gate_domain_no_topics",
            domain=domain_slug,
            reason="domain has overview but no topic pages",
        )

    if len(pages_to_heal) > 1:
        if "L2" in levels:
            pages_to_heal.sort(key=lambda p: quality_scores.get(p, {}).get("l2_bench", 0.0))
        else:
            pages_to_heal.sort(key=lambda p: quality_scores.get(p, {}).get("l1_structural", 0.0))

    page_by_path = {str(p.get("path")): p for p in state.get("pages", []) if p.get("path")}
    for page_path in pages_to_heal:
        if heal_hints.get(page_path):
            continue
        page_dict = page_by_path.get(page_path)
        if not page_dict:
            continue
        if page_dict.get("metadata", {}).get("generation_mode") in ("agent_error", "error_fallback"):
            heal_hints[page_path] = (
                "Regenerate failed documentation with Overview, key components, "
                "relationships, and at least one mermaid diagram."
            )
            continue
        try:
            page = WikiPage.from_dict(page_dict)
            bench = evaluator.bench_score(page)
            hint = evaluator.build_heal_prompt_hint_v2(bench)
            l3_dims = quality_scores.get(page_path, {}).get("l3_dimensions")
            if isinstance(l3_dims, dict) and l3_dims:
                low_dims = [dim for dim, val in l3_dims.items() if isinstance(val, (int, float)) and val < 3.0]
                if low_dims:
                    hint += "\n\n## L3 judge improvement hints\n" + "\n".join(f"- Improve {dim}." for dim in low_dims)
            heal_hints[page_path] = hint
        except Exception:
            log.warning("quality_gate_heal_hint_failed", page=page_path, exc_info=True)

    total_gaps = sum(v.get("context_gap_count", 0) for v in quality_scores.values())
    pages_with_gaps = sum(1 for v in quality_scores.values() if v.get("context_gap_count", 0) > 0)

    log.info(
        "quality_gate_done",
        run_id=state.get("run_id"),
        total_pages=len(state.get("pages", [])),
        evaluated=len(quality_scores),
        to_heal=len(pages_to_heal),
        levels=levels,
        context_gaps_total=total_gaps,
        pages_with_context_gaps=pages_with_gaps,
        page_scores=[
            {"path": p.get("path", ""), "overall": scores.get("overall", 0)}
            for p in state.get("pages", [])
            for scores in [quality_scores.get(p.get("path", ""), {})]
            if scores
        ],
    )
    return {
        "quality_scores": quality_scores,
        "pages_to_heal": pages_to_heal,
        "heal_hints": heal_hints,
        "_structural_check_cache": check_cache,
    }
