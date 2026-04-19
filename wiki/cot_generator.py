"""Two-step chain-of-thought wiki generation (analysis JSON → wiki pages)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from wiki.doc_wiki_fusion import find_related_docs, format_related_docs_for_prompt
from wiki.models import PageType, WikiPage, WikiPageMetadata

logger = logging.getLogger(__name__)


@dataclass
class CoTAnalysis:
    core_responsibilities: list[str] = field(default_factory=list)
    key_interactions: list[dict[str, str]] = field(default_factory=list)
    contradictions: list[dict[str, str]] = field(default_factory=list)
    structure_suggestions: list[str] = field(default_factory=list)
    review_items: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CoTGenerationResult:
    analysis: CoTAnalysis
    pages: list[WikiPage]
    contradictions: list[dict[str, str]]
    review_items: list[dict[str, str]]
    source_documents: list[dict[str, str]] = field(default_factory=list)


def _parse_json_object_from_llm(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from LLM text (fenced code or raw)."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    candidate = code_block.group(1).strip() if code_block else text.strip()
    start = candidate.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(candidate[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _coerce_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, (int, float, bool)):
            out.append(str(x))
    return out


def _coerce_str_dict_list(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append({str(k): str(v) for k, v in item.items()})
    return out


def _cot_analysis_from_dict(obj: dict[str, Any]) -> CoTAnalysis:
    return CoTAnalysis(
        core_responsibilities=_coerce_str_list(obj.get("core_responsibilities")),
        key_interactions=_coerce_str_dict_list(obj.get("key_interactions")),
        contradictions=_coerce_str_dict_list(obj.get("contradictions")),
        structure_suggestions=_coerce_str_list(obj.get("structure_suggestions")),
        review_items=_coerce_str_dict_list(obj.get("review_items")),
    )


def _analysis_is_empty(analysis: CoTAnalysis) -> bool:
    return not any(
        (
            analysis.core_responsibilities,
            analysis.key_interactions,
            analysis.contradictions,
            analysis.structure_suggestions,
            analysis.review_items,
        ),
    )


def _wiki_pages_from_generation_dict(data: dict[str, Any]) -> list[WikiPage]:
    raw_pages = data.get("pages")
    if not isinstance(raw_pages, list):
        return []
    pages: list[WikiPage] = []
    for item in raw_pages:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        title = item.get("title")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(title, str) or not isinstance(content, str):
            continue
        pt_raw = item.get("page_type", "architecture")
        try:
            page_type = PageType(str(pt_raw))
        except ValueError:
            page_type = PageType.ARCHITECTURE
        pages.append(
            WikiPage(
                path=path,
                title=title,
                page_type=page_type,
                content=content,
                diagrams=[],
                source_locations=[],
                metadata=WikiPageMetadata(
                    node_count=0,
                    edge_count=0,
                    generation_mode="full",
                    fallback_tier=2,
                ),
            ),
        )
    return pages


def _inject_review_markers(pages: list[WikiPage], review_items: list[dict[str, str]]) -> None:
    if not review_items:
        return
    lines = ["", "---", "[REVIEW_NEEDED] The following items need human verification:"]
    for ri in review_items:
        parts = [f"- {v}" for v in ri.values()]
        lines.append(" ".join(parts) if parts else "- (item)")
    block = "\n".join(lines)
    for p in pages:
        p.content = f"{p.content.rstrip()}{block}"


class CoTWikiGenerator:
    """Runs analysis (step 1) then wiki JSON generation (step 2)."""

    def __init__(
        self,
        llm_provider: Any | None = None,
        analysis_model: str = "",
        generation_model: str = "",
        *,
        cot_enabled: bool | None = None,
    ) -> None:
        self._llm = llm_provider
        self._analysis_model = analysis_model or None
        self._generation_model = generation_model or None
        if cot_enabled is None:
            try:
                from config import get_settings

                self._cot_enabled = bool(get_settings().wiki.cot_enabled)
            except Exception:
                self._cot_enabled = False
        else:
            self._cot_enabled = bool(cot_enabled)

    async def generate_with_cot(
        self,
        code_context: str,
        existing_wiki: str = "",
        *,
        scope_name: str = "",
        store: Any | None = None,
        entity_names: list[str] | None = None,
    ) -> CoTGenerationResult:
        if not self._cot_enabled or self._llm is None:
            return CoTGenerationResult(
                analysis=CoTAnalysis(),
                pages=[],
                contradictions=[],
                review_items=[],
                source_documents=[],
            )

        related_docs: list[dict[str, str]] = []
        effective_code_ctx = code_context
        if store is not None and entity_names:
            related_docs = await find_related_docs(store, entity_names)
            doc_block = format_related_docs_for_prompt(related_docs)
            if doc_block:
                effective_code_ctx = f"{code_context.rstrip()}\n\n{doc_block}"

        analysis = await self._analyze(effective_code_ctx, existing_wiki, scope_name)
        if _analysis_is_empty(analysis):
            return CoTGenerationResult(
                analysis=analysis,
                pages=[],
                contradictions=list(analysis.contradictions),
                review_items=list(analysis.review_items),
                source_documents=related_docs,
            )

        pages = await self._generate(analysis, effective_code_ctx, scope_name)
        _inject_review_markers(pages, analysis.review_items)
        return CoTGenerationResult(
            analysis=analysis,
            pages=pages,
            contradictions=list(analysis.contradictions),
            review_items=list(analysis.review_items),
            source_documents=related_docs,
        )

    async def _analyze(self, code_context: str, existing_wiki: str, scope_name: str) -> CoTAnalysis:
        prompt = (
            "You analyze code and wiki drafts for internal documentation.\n\n"
            f"Scope: {scope_name or '(unspecified)'}\n\n"
            "## Code / graph context\n"
            f"{code_context}\n\n"
            "## Existing wiki (may be empty)\n"
            f"{existing_wiki or '(none)'}\n\n"
            "Return ONLY a JSON object with keys:\n"
            '- "core_responsibilities": string[]\n'
            '- "key_interactions": object[] with string values (e.g. from/to/note)\n'
            '- "contradictions": object[] with string values (e.g. topic/detail)\n'
            '- "structure_suggestions": string[]\n'
            '- "review_items": object[] with string values (e.g. id/question)\n'
        )
        system = "Reply with a single JSON object only. No markdown fences, no commentary."
        raw = await self._complete(prompt, system, self._analysis_model)
        parsed = _parse_json_object_from_llm(raw) if raw else None
        if parsed is None:
            logger.warning("CoT analysis step returned no valid JSON")
            return CoTAnalysis()
        return _cot_analysis_from_dict(parsed)

    async def _generate(
        self,
        analysis: CoTAnalysis,
        code_context: str,
        scope_name: str,
    ) -> list[WikiPage]:
        analysis_blob = json.dumps(
            {
                "core_responsibilities": analysis.core_responsibilities,
                "key_interactions": analysis.key_interactions,
                "contradictions": analysis.contradictions,
                "structure_suggestions": analysis.structure_suggestions,
                "review_items": analysis.review_items,
            },
            ensure_ascii=False,
        )
        prompt = (
            "Write wiki pages as JSON using the prior analysis.\n\n"
            f"Scope: {scope_name or '(unspecified)'}\n\n"
            "## Analysis (JSON)\n"
            f"{analysis_blob}\n\n"
            "## Code / graph context\n"
            f"{code_context}\n\n"
            'Return ONLY JSON: {"pages": [{"path": "...", "title": "...", '
            '"page_type": "architecture|repo_overview|module_overview|class_detail|api_reference|data_flow", '
            '"content": "markdown body"}]}\n'
        )
        system = "Reply with a single JSON object only. No markdown fences, no commentary."
        raw = await self._complete(prompt, system, self._generation_model)
        parsed = _parse_json_object_from_llm(raw) if raw else None
        if parsed is None:
            logger.warning("CoT generation step returned no valid JSON")
            return []
        return _wiki_pages_from_generation_dict(parsed)

    async def _complete(self, prompt: str, system: str, model: str | None) -> str:
        if self._llm is None:
            return ""
        complete_fn = getattr(self._llm, "complete", None)
        if callable(complete_fn):
            messages: list[dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            return str(await complete_fn(messages, model=model))
        generate_fn = getattr(self._llm, "generate", None)
        if callable(generate_fn):
            return str(await generate_fn(prompt, system=system))
        return ""
