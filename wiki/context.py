"""Global and per-page context building for wiki generation (Layer 1 + Layer 2)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.log import get_logger
from wiki.llm_port import LLMPort
from wiki.prompts import SYSTEM_JSON_ONLY

log = get_logger(__name__)


@dataclass
class WikiContext:
    repository_context: str
    module_contexts: dict[str, str]
    page_contexts: dict[str, str]
    glossary: dict[str, str]


class WikiContextBuilder:
    """Builds glossary, repository narrative, style rules, and per-page prompt context."""

    def __init__(self, llm: LLMPort | None = None) -> None:
        self._llm = llm

    async def build_glossary(self, module_names: list[str], entry_points: list[str]) -> dict[str, str]:
        log.info("build_glossary_start", module_count=len(module_names), using_llm=self._llm is not None)
        if self._llm is not None:
            prompt = (
                "Create a short glossary for this codebase wiki.\n\n"
                f"Modules:\n{json.dumps(module_names, indent=2)}\n\n"
                f"Entry points:\n{json.dumps(entry_points, indent=2)}\n\n"
                "Return ONLY valid JSON: an object whose keys are terms and values are one-line definitions."
            )
            messages = [
                {"role": "system", "content": SYSTEM_JSON_ONLY},
                {"role": "user", "content": prompt},
            ]
            parsed: dict[str, str] = {}
            if hasattr(self._llm, "complete_json"):
                try:
                    data = await self._llm.complete_json(messages, {})
                except (ValueError, Exception):
                    log.warning("build_glossary_complete_json_failed", exc_info=True)
                    data = None
                if isinstance(data, dict):
                    parsed = {
                        k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)
                    }
            else:
                raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
                parsed = self._parse_json_object(raw)
            if parsed:
                log.info("build_glossary_done", term_count=len(parsed), source="llm")
                return parsed
            log.warning("build_glossary_llm_parse_failed", raw_len=0)
        result = {name: f"Module `{name}` — code area in this repository." for name in module_names}
        log.info("build_glossary_done", term_count=len(result), source="fallback")
        return result

    def _parse_json_object(self, raw: str) -> dict[str, str]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
        return out

    async def build_repository_context(self, modules: list[str], arch_summary: str = "") -> str:
        log.info("build_repo_context_start", module_count=len(modules), using_llm=self._llm is not None)
        if self._llm is not None:
            prompt = (
                "Summarize the repository for wiki readers in 2-4 sentences.\n\n"
                f"Modules (paths or names): {', '.join(modules) if modules else '(none)'}\n"
                f"Architecture notes: {arch_summary or '(none)'}\n"
            )
            result = (await self._llm.generate(prompt, system="Be factual and concise.")).strip()
            log.info("build_repo_context_done", result_len=len(result), source="llm")
            return result

        parts: list[str] = []
        if modules:
            parts.append(f"Modules in this repository: {', '.join(modules)}.")
        if arch_summary:
            parts.append(arch_summary.strip())
        return " ".join(parts) if parts else "Repository context is not yet specified."

    def build_style_sheet(self, language: str = "en") -> str:
        lang = language if language in ("en", "zh") else "en"
        if lang == "zh":
            return (
                "## 语气\n"
                "- 使用准确、中性的技术表述。\n"
                "- 避免营销式措辞；描述行为与职责。\n\n"
                "## 结构\n"
                "- 先说明单元的用途，再说明与周边模块的关系。\n"
                "- 列举信息时优先使用短段落与列表。\n\n"
                "## 格式\n"
                "- 按调用方要求的 Markdown 标题层级撰写。\n"
                "- 在有助于理解时对类型与包名使用反引号标注。\n"
            )
        return (
            "## Tone\n"
            "- Prefer precise, neutral technical language.\n"
            "- Avoid marketing language; describe behavior and responsibilities.\n\n"
            "## Structure\n"
            "- Start with what the unit is for, then how it fits neighbors.\n"
            "- Prefer short paragraphs and bullet lists for enumerations.\n\n"
            "## Formatting\n"
            "- Use Markdown headings exactly as requested by the caller.\n"
            "- Reference types and packages with backticks when helpful.\n"
        )

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def truncate_to_budget(self, text: str, budget: int) -> str:
        """Truncate ``text`` to fit a token *budget* (chars ≈ 4 × tokens)."""
        max_chars = max(0, budget * 4)
        if len(text) <= max_chars:
            return text
        suffix = "... and more"
        room = max_chars - len(suffix)
        if room <= 0:
            return suffix[:max_chars]
        return text[:room].rstrip() + suffix

    def build_page_context(
        self,
        parent_summary: str,
        glossary: dict[str, str],
        style_sheet: str,
        language: str = "en",
    ) -> str:
        lang = language if language in ("en", "zh") else "en"
        glossary_heading = "## Glossary" if lang == "en" else "## 术语表"
        authoring_heading = "## Authoring rules" if lang == "en" else "## 撰写规范"
        parent_heading = "## Parent context" if lang == "en" else "## 上级上下文"
        blocks: list[str] = []
        if parent_summary.strip():
            blocks.append(parent_heading + "\n" + parent_summary.strip())
        if glossary:
            lines = [f"- **{term}**: {definition}" for term, definition in sorted(glossary.items())]
            blocks.append(glossary_heading + "\n" + "\n".join(lines))
        blocks.append(authoring_heading + "\n" + style_sheet)
        return "\n\n".join(blocks)
