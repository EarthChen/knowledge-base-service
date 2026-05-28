"""LLM-based semantic coherence correction for domain assignments."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

from core.log import get_logger
from wiki.json_robust import parse_json_robust_sync
from wiki.llm_schemas import CorrectorReviewOutput
from wiki.prompts import SYSTEM_JSON_ONLY

log = get_logger(__name__)

_DOMAIN_MERGE_PROMPT = (
    "You are reviewing domain names for a wiki documentation tree.\n"
    "Below are all current domain names:\n\n"
    "{domain_listing}\n\n"
    "Identify domains that should be MERGED because they represent the same\n"
    "or highly overlapping business capability.\n\n"
    "Rules:\n"
    "- Only merge domains with CLEARLY overlapping business meaning\n"
    "- Keep the domain with more modules as the merge target\n"
    "- If unsure, do NOT merge\n\n"
    "Return ONLY valid JSON:\n"
    '{{"merges": [{{"sources": ["slug1", "slug2"], "target": "slug1", "reason": "..."}}]}}\n'
    'If no merges needed: {{"merges": []}}'
)

_GLOBAL_REVIEW_PROMPT = (
    "You are reviewing domain assignments for a code documentation wiki.\n"
    "Business: {business_id}\n\n"
    "All domains with their top representative modules:\n"
    "{domain_listing}\n\n"
    "Tasks:\n"
    "1. MERGE domains with overlapping business scope into one\n"
    "2. RENAME domains that use technical terms instead of business terms\n"
    "3. Flag obvious module misplacements (max 3 moves)\n\n"
    "Rules:\n"
    "- Only merge when business meaning clearly overlaps\n"
    "- Keep the domain with more modules as the merge target\n"
    "- Max 30% of modules can be moved\n"
    "{display_name_rule}\n\n"
    "Return ONLY valid JSON:\n"
    '{{"merges": [{{"sources": ["slug1", "slug2"], "target": "slug1",'
    ' "new_display_name": "...", "reason": "..."}}],'
    ' "renames": [{{"slug": "...", "new_display_name": "...", "reason": "..."}}],'
    ' "moves": [{{"module": "...", "from": "...", "to": "...", "reason": "..."}}]}}\n'
    'If no changes: {{"merges": [], "renames": [], "moves": []}}'
)

_DISPLAY_NAME_RULE_ZH = (
    "- IMPORTANT: new_display_name MUST be concise Chinese business terminology "
    "(2-6 Chinese characters), NOT English or slug-like names"
)
_DISPLAY_NAME_RULE_EN = (
    "- IMPORTANT: new_display_name MUST be a concise English business name "
    "(2-4 words), NOT slug-like identifiers or raw code terms"
)

_MAX_MOVE_RATIO = 0.3


def _shorten_path(path: str, levels: int = 3) -> str:
    """Keep the last N directory levels of a module path."""
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-levels:]) if len(parts) > levels else path


def _is_chinese_language(language: str) -> bool:
    lang = (language or "").strip().lower()
    if lang in {"zh", "zh-cn", "zh-tw", "chinese", "cn"}:
        return True
    return "中文" in language


def _display_name_rule(language: str) -> str:
    return _DISPLAY_NAME_RULE_ZH if _is_chinese_language(language) else _DISPLAY_NAME_RULE_EN


def build_global_review_prompt(
    *,
    business_id: str,
    domain_listing: str,
    language: str = "简体中文",
    package_tree_str: str = "",
    cross_domain_edges_str: str = "",
) -> str:
    prompt = _GLOBAL_REVIEW_PROMPT.format(
        business_id=business_id or "unknown",
        domain_listing=domain_listing,
        display_name_rule=_display_name_rule(language),
    )
    if not package_tree_str and not cross_domain_edges_str:
        return prompt
    enhanced_context = f"""

## 包层次结构 (帮助判断模块的组织归属):
{package_tree_str or "  (无路径信息)"}

## 高频跨域调用 (被多域调用的模块可能是基础设施):
{cross_domain_edges_str or "  (无显著跨域调用)"}

## 审查指引:
1. 检查每个域内的模块是否业务上相关。如果某模块的包路径与同域其他模块明显不同，考虑移出。
2. 如果某模块被 3 个以上域频繁调用，它可能是基础设施/工具类，应独立为 infra 域。
3. 明确业务归属的模块(如包路径含 family/intimacy/relation 等)不应与其他业务线混淆。
4. converter/mapper/handler 类型模块，如果仅服务于特定业务则保留，如果跨域共用则归 infra。
"""
    return prompt + enhanced_context


class GraphSemanticCorrector:
    """LLM-based semantic coherence correction for domain assignments."""

    def __init__(self, llm: LLMPort | None):
        self._llm = llm

    async def merge_similar_domains(
        self,
        domain_infos: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._llm is None or len(domain_infos) <= 1:
            return []

        lines = []
        for info in domain_infos:
            lines.append(
                f"- {info['slug']} ({info['display_name']}) — {info['module_count']} modules"
            )
        listing = "\n".join(lines)
        prompt = _DOMAIN_MERGE_PROMPT.format(domain_listing=listing)

        try:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
        except Exception:
            log.warning("domain_merge_review_llm_failed", exc_info=True)
            return []

        if not isinstance(parsed, dict):
            return []

        merges = parsed.get("merges")
        if not isinstance(merges, list):
            return []

        valid_slugs = {info["slug"] for info in domain_infos}
        valid_merges = []
        for merge in merges:
            sources = merge.get("sources", [])
            target = merge.get("target", "")
            if (
                isinstance(sources, list)
                and len(sources) >= 2
                and isinstance(target, str)
                and target in valid_slugs
                and all(s in valid_slugs for s in sources)
                and target in sources
            ):
                valid_merges.append(merge)

        if valid_merges:
            log.info("domain_merge_review_found", merge_count=len(valid_merges))

        return valid_merges

    @staticmethod
    def _has_chinese(text: str) -> bool:
        return any("一" <= ch <= "鿿" for ch in text)

    @staticmethod
    def _accept_display_name(new_name: str, language: str) -> bool:
        if not new_name or not isinstance(new_name, str):
            return False
        if _is_chinese_language(language):
            return GraphSemanticCorrector._has_chinese(new_name)
        slug_like = new_name == new_name.lower() and "-" in new_name and " " not in new_name
        return not slug_like

    async def review_global_consistency(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_paths: dict[str, str],
        module_summaries: dict[str, str],
        *,
        business_id: str = "",
        module_details: dict[str, dict[str, Any]] | None = None,
        language: str = "简体中文",
        anchored_slugs: frozenset[str] = frozenset(),
        package_tree_str: str = "",
        cross_domain_edges_str: str = "",
    ) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
        """One-shot global review: merge overlapping domains, rename, move modules."""
        if self._llm is None or len(domain_mapping) <= 1:
            return domain_mapping, domain_display_names

        # Build compact listing (top 10 modules per domain, with path and summary)
        lines: list[str] = []
        for slug, pairs in sorted(domain_mapping.items(), key=lambda x: -len(x[1])):
            display = domain_display_names.get(slug, slug)
            top = sorted(pairs, key=lambda p: -len(module_summaries.get(p[1], "")))[:10]
            lines.append(f"- {slug} ({display}) — {len(pairs)} modules")
            for _repo, mod_name in top:
                path = module_paths.get(mod_name, "")
                summary = module_summaries.get(mod_name, "")
                path_part = f" [path: {_shorten_path(path)}]" if path else ""
                summary_part = f" -- {summary}" if summary else ""
                methods_part = ""
                if module_details:
                    detail = module_details.get(mod_name)
                    if isinstance(detail, dict):
                        km = detail.get("key_methods") or detail.get("methods") or []
                        if km and isinstance(km, list):
                            methods_part = f" [methods: {', '.join(str(m) for m in km[:5])}]"
                lines.append(f"  - {mod_name}{path_part}{summary_part}{methods_part}")
        listing = "\n".join(lines)

        prompt = build_global_review_prompt(
            business_id=business_id,
            domain_listing=listing,
            language=language,
            package_tree_str=package_tree_str,
            cross_domain_edges_str=cross_domain_edges_str,
        )
        if anchored_slugs:
            constraint = (
                "\nCRITICAL: The following domains are protected and MUST NOT be merged or removed: "
                f"{', '.join(sorted(anchored_slugs))}"
            )
            prompt += constraint

        try:
            messages = [
                {"role": "system", "content": SYSTEM_JSON_ONLY},
                {"role": "user", "content": prompt},
            ]
            parsed = await self._llm.complete_json(
                messages,
                CorrectorReviewOutput.model_json_schema(),
            )
        except Exception:
            log.warning("global_review_llm_failed", exc_info=True)
            return domain_mapping, domain_display_names

        if not isinstance(parsed, dict):
            return domain_mapping, domain_display_names

        new_mapping = {slug: list(pairs) for slug, pairs in domain_mapping.items()}
        new_display = dict(domain_display_names)

        # Apply merges
        merges = parsed.get("merges", [])
        if isinstance(merges, list):
            for merge in merges:
                sources = merge.get("sources", [])
                target = merge.get("target", "")
                if not isinstance(sources, list) or target not in sources:
                    continue
                if target not in new_mapping:
                    continue
                new_name = merge.get("new_display_name")
                if isinstance(new_name, str) and self._accept_display_name(new_name, language):
                    new_display[target] = new_name
                for src in sources:
                    if src == target or src not in new_mapping:
                        continue
                    if src in anchored_slugs:
                        log.info("global_review_merge_protected", source=src, target=target)
                        continue
                    new_mapping[target].extend(new_mapping.pop(src))
                    new_display.pop(src, None)
                    log.info("global_review_merge", source=src, target=target)

        # Apply renames
        renames = parsed.get("renames", [])
        if isinstance(renames, list):
            for rename in renames:
                slug = rename.get("slug", "")
                new_name = rename.get("new_display_name", "")
                if slug in new_display and isinstance(new_name, str) and new_name:
                    if not self._accept_display_name(new_name, language):
                        log.warning(
                            "global_review_rename_skipped_invalid_display_name",
                            slug=slug,
                            new_name=new_name,
                            language=language,
                        )
                        continue
                    new_display[slug] = new_name
                    log.info("global_review_rename", slug=slug, new_name=new_name)

        # Apply moves (limited)
        total_modules = sum(len(v) for v in new_mapping.values())
        max_moves = max(int(total_modules * _MAX_MOVE_RATIO), 1)
        moves = parsed.get("moves", [])
        applied_moves = 0
        if isinstance(moves, list):
            for move in moves:
                if applied_moves >= max_moves:
                    break
                mod_name = move.get("module", "")
                from_d = move.get("from", "")
                to_d = move.get("to", "")
                if not all([mod_name, from_d, to_d]):
                    continue
                if from_d not in new_mapping or to_d not in new_mapping:
                    continue
                pair = None
                for repo, name in new_mapping[from_d]:
                    if name == mod_name:
                        pair = (repo, name)
                        break
                if pair is None:
                    continue
                new_mapping[from_d].remove(pair)
                new_mapping[to_d].append(pair)
                applied_moves += 1
                log.info("global_review_move", module=mod_name, from_d=from_d, to_d=to_d)

        new_mapping = {k: v for k, v in new_mapping.items() if v}
        return new_mapping, new_display
