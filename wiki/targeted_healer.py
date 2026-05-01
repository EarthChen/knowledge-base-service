"""Targeted wiki page healer using LLM diagnosis and JSON patches."""
from __future__ import annotations

import json
import re
from typing import Any

from log import get_logger
from wiki.models import WikiPage

log = get_logger(__name__)


class TargetedHealer:
    """Diagnose wiki page issues and generate targeted patches instead of full regeneration."""

    _DIAGNOSIS_SYSTEM = (
        "You are a wiki quality analyst. Diagnose content issues and suggest "
        "targeted patches. Return ONLY valid JSON. No markdown fences."
    )

    def _normalize_heading_title(self, heading: str) -> str:
        """Strip markdown heading markers so target_heading matches '## Foo' titles."""
        t = (heading or "").strip()
        t = re.sub(r"^[#]+\s*", "", t)
        return t.strip()

    def _build_diagnosis_prompt(
        self,
        page: WikiPage,
        bench_hints: str,
        domain_context: str,
        *,
        content_for_diagnosis: str,
    ) -> str:
        """Ask the LLM for root causes and ordered JSON patches."""
        schema = """{
  "root_causes": ["string"],
  "preserved_sections": ["heading titles whose sections stay as-is"],
  "patches": [
    {"action": "replace_section"|"insert_after"|"append", "target_heading": "section title without #", "content": "markdown snippet"}
  ]
}"""
        return (
            "Analyze the wiki page below.\n\n"
            "Goals:\n"
            "1. Explain the root cause of each issue implied by quality hints.\n"
            "2. List headings (## level only) whose sections are already adequate (preserved_sections).\n"
            "3. Produce an ordered patches array to fix remaining problems:\n"
            "   - replace_section — replace ONLY the body under that ## heading (heading line unchanged). "
            "Section runs from after that line until just before the next line starting with '## '\n."
            '   - insert_after — insert content immediately after that heading line\'s newline.\n'
            "   - append — append markdown at end of document (target_heading ignored).\n\n"
            f"Quality hints:\n{bench_hints}\n\n"
            f"Domain context:\n{domain_context or '(none)'}\n\n"
            f"Page path: {page.path}\n"
            f"Page title: {page.title}\n\n"
            f"Markdown content:\n---\n{content_for_diagnosis}\n---\n\n"
            "Return JSON exactly matching:\n"
            f"{schema}\n"
            "Rules: headings in target_heading MUST match existing ## headings' text without leading hashes. "
            "Patches run in sequence; later patches see earlier results. Prefer minimal edits.\n"
            "Patches apply to the FULL stored page markdown (the preview above may be truncated only for sizing).\n"
        )

    async def heal(
        self,
        page: WikiPage,
        bench_hints: str,
        llm: Any,
        domain_context: str,
        *,
        content_char_limit: int | None = None,
        max_tokens: int | None = None,
    ) -> WikiPage | None:
        """Attempt targeted fix. Returns patched WikiPage or None if failed."""
        content_for_prompt = (
            page.content[:content_char_limit]
            if content_char_limit is not None and len(page.content) > content_char_limit
            else page.content
        )
        prompt = self._build_diagnosis_prompt(
            page,
            bench_hints,
            domain_context,
            content_for_diagnosis=content_for_prompt,
        )
        try:
            gen_kw: dict[str, Any] = {}
            if max_tokens is not None:
                gen_kw["max_tokens"] = max_tokens
            response = await llm.generate(prompt, system=self._DIAGNOSIS_SYSTEM, **gen_kw)
            result = self._parse_response(response)
            if not result or not isinstance(result.get("patches"), list):
                return None
            patches_raw = result["patches"]
            if not patches_raw:
                return None

            patches: list[dict] = []
            for p in patches_raw:
                if isinstance(p, dict):
                    patches.append(p)
            if not patches:
                return None

            new_content = self._apply_patches(page.content, patches)
            return WikiPage(
                path=page.path,
                title=page.title,
                page_type=page.page_type,
                content=new_content,
                diagrams=page.diagrams,
                source_locations=page.source_locations,
                metadata=page.metadata,
                method_locations=page.method_locations,
                navigation=page.navigation,
            )
        except Exception:
            log.warning("targeted_heal_failed", page=page.path, exc_info=True)
            return None

    def _parse_response(self, response: str) -> dict | None:
        """Parse JSON response from LLM, handling common format issues."""
        raw = (response or "").strip()
        if not raw:
            return None

        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if fenced:
            raw = fenced.group(1).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            brace = raw.find("{")
            if brace == -1:
                return None
            tail = raw[brace:]
            try:
                data = json.loads(tail)
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict):
            return None
        return data

    def _apply_patches(self, content: str, patches: list[dict]) -> str:
        """Apply patches to content sequentially."""
        result = content
        for patch in patches:
            action = patch.get("action", "")
            heading = patch.get("target_heading", "") or ""
            new_content_patch = patch.get("content")
            if new_content_patch is None:
                continue
            new_content_str = str(new_content_patch)

            if action == "replace_section":
                result = self._replace_section(result, heading, new_content_str)
            elif action == "insert_after":
                result = self._insert_after_heading(result, heading, new_content_str)
            elif action == "append":
                result = (
                    result.rstrip()
                    + "\n\n"
                    + new_content_str.strip()
                    + ("\n" if new_content_str.strip() else "")
                )
        return result

    def _replace_section(self, content: str, heading: str, replacement: str) -> str:
        """Replace body under an H2 heading; keep heading line unchanged."""
        title = self._normalize_heading_title(heading)
        if not title:
            return content

        escaped = re.escape(title)
        pattern = re.compile(
            rf"(?ms)(\n|^)(##\s*{escaped}\s*\n)(.*?)(?=\n##\s|\Z)",
        )
        m = pattern.search(content)
        if not m:
            log.debug("targeted_healer_replace_heading_not_found", heading=title)
            return content

        body = replacement.lstrip("\n")
        new_block = m.group(1) + m.group(2) + body
        span_end = m.end()
        return content[: m.start()] + new_block + content[span_end:]

    def _insert_after_heading(self, content: str, heading: str, insertion: str) -> str:
        """Insert content immediately after an H2 heading line."""
        title = self._normalize_heading_title(heading)
        if not title:
            return content

        escaped = re.escape(title)
        pattern = re.compile(rf"(?ms)(\n|^)(##\s*{escaped}\s*\n)")
        m = pattern.search(content)
        if not m:
            log.debug("targeted_healer_insert_heading_not_found", heading=title)
            return content

        inserted = insertion.strip("\n")
        if not inserted:
            return content
        at = m.end()
        snippet = ("\n\n" + inserted + "\n\n") if at < len(content) else ("\n\n" + inserted)
        return content[:at] + snippet + content[at:]
