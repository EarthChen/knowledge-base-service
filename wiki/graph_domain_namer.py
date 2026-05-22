"""LLM-based domain naming for graph communities."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

from core.log import get_logger
from wiki.json_robust import parse_json_robust_sync
from wiki.path_conventions import normalize_slug
from wiki.prompts import SYSTEM_JSON_ONLY

log = get_logger(__name__)

_NAMING_PROMPT_V2 = (
    "You are naming a group of code modules for a business documentation wiki.\n"
    "These modules were grouped by their semantic similarity (business function).\n"
    "{business_context_block}\n"
    "Module details:\n"
    "{module_details}\n\n"
    "Rules:\n"
    "- Name the BUSINESS capability these modules provide, not code structure\n"
    "- CRITICAL: display_name MUST be concise Chinese (2-6 Chinese characters), "
    "e.g. '好友关系', '家族系统', '用户资料'. NEVER use English for display_name\n"
    "- Prefer terms that appear in the code's own comments or class-level documentation\n"
    "- The slug should be kebab-case ASCII describing the business capability\n"
    "- Do NOT name based on technical patterns (Handler, Service, Dao, etc.)\n"
    "{used_names_block}\n"
    'Return ONLY valid JSON: {{"slug": "...", "display_name": "...", "description": "..."}}'
)

def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


_TECH_SUFFIXES = frozenset({
    "Handler", "Service", "Manager", "Executor", "Provider",
    "Dao", "Controller", "Impl", "WebService", "Listener",
    "Processor", "Worker", "Helper", "Adapter", "Factory",
})


def _extract_common_prefix(module_names: list[str]) -> str:
    if not module_names:
        return ""
    if len(module_names) == 1:
        return module_names[0]

    prefix = module_names[0]
    for name in module_names[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            return module_names[0]
    return prefix


def _fallback_name(module_names: list[str]) -> dict[str, str]:
    import re

    stripped = []
    for name in module_names:
        words = re.findall(r"[A-Z][a-z]+", name)
        while words and words[-1] in _TECH_SUFFIXES:
            words.pop()
        stripped.append("".join(words) if words else name)

    common = _extract_common_prefix(stripped)
    display_name = common or (stripped[0] if stripped else "unnamed")
    slug = normalize_slug(display_name)
    return {
        "slug": slug,
        "display_name": display_name,
        "description": f"Modules: {', '.join(module_names)}" if module_names else "",
    }


class GraphDomainNamer:
    """Name graph communities using LLM."""

    def __init__(self, llm: LLMPort | None):
        self._llm = llm

    async def name_community(
        self,
        module_names: list[str] | None = None,
        *,
        module_infos: list[dict[str, str]] | None = None,
        used_names: list[str] | None = None,
        business_id: str = "",
    ) -> dict[str, str]:
        """Name a community based on module names or detailed infos.

        Returns: {"slug": "family-system", "display_name": "家族系统", "description": "..."}
        Falls back to first module name based slug if LLM fails after retry.
        """
        if module_infos:
            detail_lines = []
            for info in module_infos:
                name = info.get("name", "")
                path = info.get("path", "")
                summary = info.get("summary", "")
                if summary:
                    detail_lines.append(f"- {name} [{path}] — {summary}")
                elif path:
                    detail_lines.append(f"- {name} [{path}]")
                else:
                    detail_lines.append(f"- {name}")
            names_for_fallback = [info.get("name", "") for info in module_infos]
        elif module_names:
            detail_lines = [f"- {n}" for n in module_names]
            names_for_fallback = list(module_names)
        else:
            return _fallback_name([])

        if not detail_lines:
            return _fallback_name(names_for_fallback)

        if self._llm is None:
            return _fallback_name(names_for_fallback)

        used_block = ""
        if used_names:
            used_block = (
                "\nIMPORTANT: These names are already in use, choose a DIFFERENT name:\n"
                + ", ".join(used_names)
                + "\n"
            )

        biz_block = f"\nBusiness context: {business_id}\n" if business_id else ""

        prompt = _NAMING_PROMPT_V2.format(
            module_details="\n".join(detail_lines),
            used_names_block=used_block,
            business_context_block=biz_block,
        )

        for attempt in range(2):
            try:
                raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
                parsed = parse_json_robust_sync(raw)
                if isinstance(parsed, dict):
                    slug = parsed.get("slug")
                    display_name = parsed.get("display_name")
                    description = parsed.get("description")
                    if isinstance(slug, str) and slug and isinstance(display_name, str) and display_name:
                        if not _has_chinese(display_name):
                            log.warning("graph_domain_namer_non_chinese_display", display_name=display_name, slug=slug)
                        return {
                            "slug": slug,
                            "display_name": display_name,
                            "description": str(description) if description is not None else "",
                        }
            except Exception:
                if attempt == 0:
                    log.warning("graph_domain_namer_retry", module_count=len(names_for_fallback), exc_info=True)
                    continue
                log.warning("graph_domain_namer_llm_failed", module_count=len(names_for_fallback), exc_info=True)

        return _fallback_name(names_for_fallback)

    async def name_communities_batch(
        self,
        communities: list[list[str]],
        *,
        used_names: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Name multiple communities. Returns list in same order as input."""
        all_used = list(used_names) if used_names else []
        results = []
        for modules in communities:
            result = await self.name_community(modules, used_names=all_used)
            all_used.append(result["slug"])
            results.append(result)
        return results
