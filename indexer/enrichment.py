"""Code summary enrichment — generates business_summary via LLM.

Supports two backends:
- **OpenAI compat** (``LLMProvider``): one HTTP request per entity,
  each consuming a separate ACP task.
- **Gateway task** (``GatewayTaskClient``): one ACP task for the entire
  batch, driven through the feedback-tool loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.gateway_client import GatewayTaskClient
    from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Prompt / payload limits (keep gateway prompts small for faster turns)
ENRICHMENT_SUMMARY_MAX_ZH = 100
DOCSTRING_MAX_CHARS = 200
CODE_SNIPPET_MAX_LINES = 10
# Meaningful (non-blank) lines below this count → treat as trivial (functions only)
TRIVIAL_FUNCTION_MAX_LINES = 4

_SUMMARY_PROMPT = f"""你是一个代码分析专家。请为以下代码生成一个简洁的业务语义描述。
要求：
1. 用自然语言描述这个函数/类的业务用途（而非技术实现）
2. 包含它属于哪个业务领域
3. 它在业务流程中扮演的角色
4. 不超过 {ENRICHMENT_SUMMARY_MAX_ZH} 字

代码信息:
文件: {{file}}
名称: {{name}}
签名: {{signature}}
文档: {{docstring}}
代码片段: {{code_snippet}}"""

_PY_ACCESSOR = re.compile(r"^(get|set|is|has)_[a-zA-Z0-9_]+$")
_CAMEL_ACCESSOR = re.compile(r"^(get|is|has)([A-Z][a-zA-Z0-9]+)$")
_CAMEL_SETTER = re.compile(r"^set([A-Z][a-zA-Z0-9]+)$")
_CONSTRUCTOR_NAMES = frozenset({"__init__", "__new__", "<init>"})


def truncate_enrichment_item(item: dict[str, str]) -> dict[str, str]:
    """Return a copy with docstring and code_snippet shortened for LLM prompts."""
    out = dict(item)
    ds = out.get("docstring") or ""
    out["docstring"] = ds[:DOCSTRING_MAX_CHARS]
    code = out.get("code_snippet") or ""
    lines = code.splitlines()
    out["code_snippet"] = "\n".join(lines[:CODE_SNIPPET_MAX_LINES])
    return out


def _meaningful_line_count(snippet: str) -> int | None:
    lines = [ln for ln in snippet.splitlines() if ln.strip()]
    if not lines:
        return None
    return len(lines)


def is_trivial_enrichment_entity(item: dict[str, str]) -> bool:
    """Whether to skip LLM enrichment (getter/setter, ctor, tiny function)."""
    name = (item.get("name") or "").strip()
    snippet = item.get("code_snippet") or ""
    kind = (item.get("entity_kind") or "function").lower()

    if name in _CONSTRUCTOR_NAMES:
        return True

    if _is_accessor_name(name):
        return True

    if kind != "function":
        return False

    mlines = _meaningful_line_count(snippet)
    if mlines is not None and mlines <= TRIVIAL_FUNCTION_MAX_LINES:
        return True

    return False


def _is_accessor_name(name: str) -> bool:
    if not name or name in _CONSTRUCTOR_NAMES:
        return False
    if name in ("setUp", "tearDown", "setUpClass", "tearDownClass"):
        return False
    if _PY_ACCESSOR.match(name):
        return True
    if _CAMEL_ACCESSOR.match(name) or _CAMEL_SETTER.match(name):
        return True
    return False


class CodeSummaryEnricher:
    """Batch-generates business summaries for code entities using LLM.

    When *gateway_client* is provided it takes precedence over *llm*,
    processing the entire batch inside a single ACP task via the
    feedback-tool loop (= one Cursor task for all entities).
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
        gateway_client: GatewayTaskClient | None = None,
    ) -> None:
        self._llm = llm
        self._gw = gateway_client

    async def enrich_batch(self, items: list[dict[str, str]]) -> list[str]:
        """Generate business_summary for each item (same order as input)."""
        if not items:
            return []

        trivial_mask = [is_trivial_enrichment_entity(it) for it in items]
        skipped = sum(trivial_mask)
        if skipped:
            logger.info(
                "enrichment_prefilter",
                total=len(items),
                skipped_trivial=skipped,
                sent_to_llm=len(items) - skipped,
            )

        if skipped == len(items):
            return [""] * len(items)

        to_run: list[tuple[int, dict[str, str]]] = [
            (i, truncate_enrichment_item(items[i]))
            for i in range(len(items))
            if not trivial_mask[i]
        ]

        if self._gw is not None:
            merged = await self._enrich_via_gateway_masked(items, to_run)
        elif self._llm is not None:
            merged = await self._enrich_via_llm_masked(items, to_run)
        else:
            logger.warning("No LLM backend configured — skipping enrichment")
            merged = [""] * len(items)

        return merged

    async def _enrich_via_gateway_masked(
        self,
        items: list[dict[str, str]],
        to_run: list[tuple[int, dict[str, str]]],
    ) -> list[str]:
        batch = [pair[1] for pair in to_run]
        try:
            out_partial = await self._gw.enrich_batch(batch)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Gateway task enrichment failed, falling back to per-item LLM")
            if self._llm is not None:
                return await self._enrich_via_llm_masked(items, to_run)
            return [""] * len(items)

        results = [""] * len(items)
        if len(out_partial) != len(to_run):
            logger.warning(
                "enrichment_gateway_length_mismatch",
                expected=len(to_run),
                got=len(out_partial),
            )
        for (orig_idx, _), summary in zip(to_run, out_partial, strict=False):
            results[orig_idx] = (summary or "").strip()
        return results

    async def _enrich_via_llm_masked(
        self,
        items: list[dict[str, str]],
        to_run: list[tuple[int, dict[str, str]]],
    ) -> list[str]:
        """Run legacy per-file LLM only for *to_run* indices."""
        results = [""] * len(items)
        by_file: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
        for orig_idx, payload in to_run:
            fp = payload.get("file", "unknown")
            by_file[fp].append((orig_idx, payload))

        tasks = [
            self._enrich_file_group_masked(file_path, group, results)
            for file_path, group in by_file.items()
        ]
        await asyncio.gather(*tasks)
        return results

    async def _enrich_file_group_masked(
        self,
        file_path: str,
        group: list[tuple[int, dict[str, str]]],
        results: list[str],
    ) -> None:
        for idx, item in group:
            try:
                prompt = _SUMMARY_PROMPT.format(
                    file=file_path,
                    name=item.get("name", ""),
                    signature=item.get("signature", ""),
                    docstring=item.get("docstring", ""),
                    code_snippet=item.get("code_snippet", ""),
                )
                summary = await self._llm.complete(  # type: ignore[union-attr]
                    [{"role": "user", "content": prompt}]
                )
                results[idx] = summary.strip()
            except Exception:
                logger.warning("Failed to enrich %s in %s", item.get("name"), file_path, exc_info=True)
                results[idx] = ""

    async def enrich_single(self, item: dict[str, str]) -> str:
        """Generate business_summary for a single item."""
        summaries = await self.enrich_batch([item])
        return summaries[0]
