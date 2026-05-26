"""LLM-driven wiki structure planning by business topics.

Generates a topic-based wiki structure from domain mappings and module metadata,
targeting a configurable page count range. Falls back to domain-direct mapping
when LLM output is invalid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger
from wiki.json_robust import parse_json_robust_sync
from wiki.llm_port import LLMPort

log = get_logger(__name__)


def _should_use_chinese(language: str, domain_mapping: dict[str, list[tuple[str, str]]]) -> bool:
    has_chinese_domains = any(
        any("\u4e00" <= c <= "\u9fff" for c in domain)
        for domain in domain_mapping
    )
    return language == "zh" or has_chinese_domains


def _is_ascii_only_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return all(ord(c) < 128 for c in t)


def _best_domain_for_modules(
    covered_modules: list[tuple[str, str]],
    domain_mapping: dict[str, list[tuple[str, str]]],
) -> str | None:
    """Pick a domain key from ``domain_mapping`` that best explains ``covered_modules``."""
    if not covered_modules:
        return None
    covered_set = set(covered_modules)
    full_containers: list[str] = []
    best_partial: tuple[str, int] | None = None
    for domain, mods in domain_mapping.items():
        mod_set = set(mods)
        if covered_set <= mod_set:
            full_containers.append(domain)
        else:
            overlap = len(covered_set & mod_set)
            if overlap > 0 and (best_partial is None or overlap > best_partial[1]):
                best_partial = (domain, overlap)
    if len(full_containers) == 1:
        return full_containers[0]
    if len(full_containers) > 1:
        return full_containers[0]
    if best_partial is not None:
        return best_partial[0]
    return None


@dataclass
class TopicPage:
    title: str
    description: str
    covered_modules: list[tuple[str, str]]
    sub_topics: list[TopicPage] = field(default_factory=list)


class TopicBasedStructurePlanner:
    """LLM-driven wiki structure planning by business topics."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def plan(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        module_metadata: dict[tuple[str, str], dict[str, Any]],
        importance_tiers: dict[str, str],
        *,
        target_pages: tuple[int, int] = (40, 80),
        language: str = "zh",
    ) -> list[TopicPage]:
        prompt = self._build_prompt(domain_mapping, module_metadata, importance_tiers, target_pages, language=language)
        system = (
            'Respond with valid JSON only: a single JSON object of the form {"topics": [...]} '
            "where \"topics\" is the array of topic objects described in the user message. "
            "No markdown fences or explanation."
        )

        llm_raw: str | None = None
        try:
            if hasattr(self._llm, "complete_json"):
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ]
                try:
                    parsed = await self._llm.complete_json(messages, {})
                except (ValueError, Exception) as exc:
                    log.warning("topic_planner_llm_failed", error=str(exc)[:200])
                    return self._fallback(domain_mapping)
                parsed_list = parsed.get("topics") if isinstance(parsed, dict) else parsed
            else:
                llm_raw = await self._llm.generate(prompt, system=system)
                parsed = parse_json_robust_sync(llm_raw)
                parsed_list = parsed
        except Exception as exc:
            log.warning("topic_planner_llm_failed", error=str(exc)[:200])
            return self._fallback(domain_mapping)

        if not isinstance(parsed_list, list):
            raw_preview = llm_raw[:200] if llm_raw is not None else str(parsed_list)[:200]
            log.warning("topic_planner_parse_failed", raw_preview=raw_preview)
            return self._fallback(domain_mapping)

        try:
            pages = self._parse_pages(parsed_list)
        except (TypeError, KeyError, ValueError) as exc:
            log.warning("topic_planner_validation_failed", error=str(exc)[:200])
            return self._fallback(domain_mapping)

        if not pages:
            return self._fallback(domain_mapping)

        if _should_use_chinese(language, domain_mapping):
            self._fix_ascii_only_titles(pages, domain_mapping)

        covered = set()
        for p in pages:
            covered.update(p.covered_modules)
            for sp in p.sub_topics:
                covered.update(sp.covered_modules)

        expected = set()
        for modules in domain_mapping.values():
            expected.update(modules)

        if not covered or len(covered) < len(expected) * 0.5:
            log.warning(
                "topic_planner_low_coverage",
                covered=len(covered),
                expected=len(expected),
            )
            return self._fallback(domain_mapping)

        return pages

    def _fix_ascii_only_titles(
        self,
        pages: list[TopicPage],
        domain_mapping: dict[str, list[tuple[str, str]]],
    ) -> None:
        """Replace ASCII-only titles using Chinese domain keys that cover the page modules."""

        def fix_page(page: TopicPage) -> None:
            for st in page.sub_topics:
                fix_page(st)
            if not _is_ascii_only_text(page.title):
                return
            domain_guess = _best_domain_for_modules(page.covered_modules, domain_mapping)
            if not domain_guess:
                log.warning(
                    "topic_planner_ascii_title_no_domain",
                    title=page.title[:120],
                    module_count=len(page.covered_modules),
                )
                return
            log.warning(
                "topic_planner_ascii_title_fallback",
                old_title=page.title[:200],
                domain=domain_guess,
            )
            page.title = domain_guess

        for p in pages:
            fix_page(p)

    def _build_prompt(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        module_metadata: dict[tuple[str, str], dict[str, Any]],
        importance_tiers: dict[str, str],
        target_pages: tuple[int, int],
        *,
        language: str = "zh",
    ) -> str:
        domain_lines: list[str] = []
        for domain, modules in domain_mapping.items():
            mod_details: list[str] = []
            for repo, name in modules:
                meta = module_metadata.get((repo, name), {})
                summary = meta.get("summary", "(no description)")
                tier = importance_tiers.get(name, "standard")
                mod_details.append(f"    - [{repo}] {name} (tier={tier}): {summary}")
            domain_lines.append(f"  {domain}:\n" + "\n".join(mod_details))

        domains_text = "\n".join(domain_lines)
        min_pages, max_pages = target_pages

        use_chinese = _should_use_chinese(language, domain_mapping)
        lang_block = ""
        if use_chinese:
            lang_block = (
                "Rules — READ THIS BLOCK FIRST (HIGHEST PRIORITY, NON-NEGOTIABLE):\n"
                "- OUTPUT LANGUAGE IS 简体中文 ONLY for every \"title\" and \"description\" field in the JSON. "
                "English-only titles or descriptions are INVALID and FORBIDDEN.\n"
                "- Topic titles MUST contain Chinese characters (CJK). Pure ASCII titles like "
                "\"User Relationship and Rank Management\" or \"Gift Sending\" are REJECTED.\n"
                "- Each topic title MUST semantically align with its domain label and modules below: "
                "reuse meaningful words from the Chinese domain name. "
                "Example: domain \"用户关系管理\" → title MUST include wording such as \"用户关系\" / \"关系管理\" (not \"User Relationship\").\n"
                "Example: domain \"礼物订单处理\" → title MUST include \"礼物\" or \"订单\" in Chinese (not \"Gift Order\").\n"
                "Example ACCEPTED titles: \"用户关系与等级管理\", \"亲密度与亲密关系\", \"礼物与订单流转\".\n"
                "Example REJECTED titles: \"User Relationship Management\", \"Intimacy Handling\", \"App Store Interaction\".\n"
                "- Sub-topic titles follow the same rules: Chinese only, domain-aligned vocabulary.\n\n"
                "Further rules:\n"
            )

        return (
            "Based on the following business domain classification, plan a Wiki structure.\n\n"
            f"{lang_block}"
            f"1. Generate {min_pages}-{max_pages} topic pages total\n"
            "2. Each top-level topic = one business domain or a merge of related domains\n"
            "3. Each topic can have 3-5 sub-pages\n"
            "4. Each page should cover a complete business capability\n"
            "5. Assign every module to exactly one page\n"
            "6. SKELETON-tier modules can be grouped together in infrastructure topics\n"
            "7. CRITICAL: Topic titles MUST directly reflect the actual modules and their descriptions below. "
            "Do NOT invent capabilities (e.g., 'Analytics', 'Monitoring', 'Dashboard') that have NO corresponding modules. "
            "If a domain has only 1-2 handler modules, the topic should describe what those handlers actually do, "
            "not speculate about broader infrastructure.\n"
            "8. Each topic's description MUST be derivable from the module summaries listed under it.\n"
            "9. IMPORTANT: Each domain listed below MUST have at least one dedicated topic page. "
            "Do NOT merge all modules from different domains into a single topic. "
            "Even if a domain only has 1-2 modules, create a focused topic for it.\n\n"
            f"Domains:\n{domains_text}\n\n"
            'Output JSON: an object {"topics": [<array of {title, description, '
            "modules: [[repo, name], ...], sub_topics: [...]}>]}. "
            'The root must be a JSON object with key "topics".'
        )

    def _parse_pages(self, data: list[Any]) -> list[TopicPage]:
        pages: list[TopicPage] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            description = item.get("description", "")
            raw_modules = item.get("modules", [])
            covered = self._parse_module_list(raw_modules)

            sub_topics: list[TopicPage] = []
            for sub in item.get("sub_topics", []) or []:
                if not isinstance(sub, dict):
                    continue
                sub_modules = self._parse_module_list(sub.get("modules", []))
                sub_topics.append(TopicPage(
                    title=sub.get("title", ""),
                    description=sub.get("description", ""),
                    covered_modules=sub_modules,
                ))

            pages.append(TopicPage(
                title=title,
                description=description,
                covered_modules=covered,
                sub_topics=sub_topics,
            ))
        return pages

    @staticmethod
    def _parse_module_list(raw: Any) -> list[tuple[str, str]]:
        if not isinstance(raw, list):
            return []
        result: list[tuple[str, str]] = []
        for entry in raw:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                result.append((str(entry[0]), str(entry[1])))
        return result

    def _fallback(self, domain_mapping: dict[str, list[tuple[str, str]]]) -> list[TopicPage]:
        """Each domain becomes a top-level topic page."""
        log.info("topic_planner_fallback", domain_count=len(domain_mapping))
        pages: list[TopicPage] = []
        for domain, modules in domain_mapping.items():
            pages.append(TopicPage(
                title=domain,
                description=f"Wiki pages for {domain} domain",
                covered_modules=list(modules),
            ))
        return pages
