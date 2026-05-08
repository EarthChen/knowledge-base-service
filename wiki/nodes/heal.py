"""Quality healing node for wiki pages."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.domain_complexity import DomainComplexityScorer
from wiki.models import ImportanceTier, WikiPage
from wiki.nodes.utils import _find_domain_in_tree
from wiki.prompts import SYSTEM_WIKI_HEAL
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.reasoning import GuidedPromptEnhancer, ReasoningLevel, TaskType, select_reasoning_level

log = get_logger(__name__)

_MAX_HEAL_ROUNDS = 3


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
            page_dict["content"] = targeted_result.content
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
        new_content = await llm.generate(
            fallback_prompt,
            system=SYSTEM_WIKI_HEAL,
            max_tokens=heal_budget,
        )
        page_dict["content"] = new_content
        log.info("page_healed", page=page_path, attempt=heal_attempts[page_path])
        return True
    except Exception:
        log.warning("heal_page_regen_failed", page=page_path, exc_info=True)
        return False


async def heal_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Regenerate pages that failed the quality gate (replaces them via merge_wiki_pages)."""
    llm = (config or {}).get("configurable", {}).get("llm")
    evaluator = WikiQualityEvaluator()
    heal_attempts = dict(state.get("heal_attempts", {}))
    heal_hints = dict(state.get("heal_hints", {}))

    initial_paths: list[str] = []
    seen_setup: set[str] = set()
    for page_path in state.get("pages_to_heal", []):
        if page_path in seen_setup:
            continue
        seen_setup.add(page_path)
        initial_paths.append(page_path)

    if not initial_paths:
        log.info("heal_pages_done", healed_count=0)
        return {
            "pages_to_heal": [],
            "heal_attempts": heal_attempts,
            "heal_hints": heal_hints,
            "pages": [],
        }

    page_by_path: dict[str, dict[str, Any]] = {}
    for p in state.get("pages", []):
        path = p.get("path")
        if path in seen_setup:
            page_by_path[str(path)] = dict(p)

    max_rounds = _MAX_HEAL_ROUNDS if llm else 1
    active = list(initial_paths)
    healed_by_path: dict[str, dict[str, Any]] = {}

    for _ in range(max_rounds):
        if not active:
            break
        next_active: list[str] = []
        for page_path in active:
            heal_attempts[page_path] = heal_attempts.get(page_path, 0) + 1
            page_dict = page_by_path.get(page_path)
            if not page_dict:
                continue

            if llm:
                ok = await _heal_one_page(
                    page_path=page_path,
                    page_dict=page_dict,
                    state=state,
                    evaluator=evaluator,
                    llm=llm,
                    heal_hints=heal_hints,
                    heal_attempts=heal_attempts,
                )
                if ok:
                    healed_by_path[page_path] = dict(page_dict)
            else:
                _update_heal_hint(page_path, page_dict, evaluator, heal_hints)
                log.info("page_heal_skip_no_llm", page=page_path)

        for page_path in active:
            page_dict = page_by_path.get(page_path)
            if not page_dict:
                continue
            try:
                page = WikiPage.from_dict(page_dict)
            except Exception:
                next_active.append(page_path)
                continue
            if not _page_passes_post_heal(page, state, evaluator):
                next_active.append(page_path)

        active = next_active

    healed_pages = [healed_by_path[p] for p in initial_paths if p in healed_by_path]
    log.info("heal_pages_done", healed_count=len(healed_pages))
    return {
        "pages_to_heal": [],
        "heal_attempts": heal_attempts,
        "heal_hints": heal_hints,
        "pages": healed_pages,
    }
