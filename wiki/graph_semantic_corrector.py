"""LLM-based semantic coherence correction for domain assignments."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

from core.log import get_logger
from wiki.json_robust import parse_json_robust_sync
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
    "- IMPORTANT: new_display_name MUST be concise Chinese business terminology "
    "(2-6 Chinese characters), NOT English or slug-like names\n\n"
    "Return ONLY valid JSON:\n"
    '{{"merges": [{{"sources": ["slug1", "slug2"], "target": "slug1",'
    ' "new_display_name": "...", "reason": "..."}}],'
    ' "renames": [{{"slug": "...", "new_display_name": "...", "reason": "..."}}],'
    ' "moves": [{{"module": "...", "from": "...", "to": "...", "reason": "..."}}]}}\n'
    'If no changes: {{"merges": [], "renames": [], "moves": []}}'
)

_MAX_MOVE_RATIO = 0.3


def _shorten_path(path: str, levels: int = 3) -> str:
    """Keep the last N directory levels of a module path."""
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-levels:]) if len(parts) > levels else path


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

    async def review_global_consistency(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_paths: dict[str, str],
        module_summaries: dict[str, str],
        *,
        business_id: str = "",
        module_details: dict[str, dict[str, Any]] | None = None,
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

        prompt = _GLOBAL_REVIEW_PROMPT.format(
            business_id=business_id or "unknown",
            domain_listing=listing,
        )

        try:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
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
                if isinstance(new_name, str) and new_name and self._has_chinese(new_name):
                    new_display[target] = new_name
                for src in sources:
                    if src == target or src not in new_mapping:
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
                    if not self._has_chinese(new_name):
                        log.warning("global_review_rename_skipped_non_chinese", slug=slug, new_name=new_name)
                        continue
                    new_display[slug] = new_name
                    log.info("global_review_rename", slug=slug, new_name=new_name)

        # Apply moves (limited)
        total_modules = sum(len(v) for v in new_mapping.values())
        max_moves = max(int(total_modules * _MAX_MOVE_RATIO), 1)
        moves = parsed.get("moves", [])
        applied_moves = 0
        if isinstance(moves, list):
            module_to_repo: dict[str, str] = {}
            for pairs in new_mapping.values():
                for repo, mod_name in pairs:
                    module_to_repo[mod_name] = repo
            for move in moves:
                if applied_moves >= max_moves:
                    break
                mod_name = move.get("module", "")
                from_d = move.get("from", "")
                to_d = move.get("to", "")
                repo = module_to_repo.get(mod_name)
                if not all([mod_name, from_d, to_d, repo]):
                    continue
                if from_d not in new_mapping or to_d not in new_mapping:
                    continue
                pair = (repo, mod_name)
                if pair in new_mapping[from_d]:
                    new_mapping[from_d].remove(pair)
                    new_mapping[to_d].append(pair)
                    applied_moves += 1
                    log.info("global_review_move", module=mod_name, from_d=from_d, to_d=to_d)

        new_mapping = {k: v for k, v in new_mapping.items() if v}
        return new_mapping, new_display
