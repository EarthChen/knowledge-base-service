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
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.gateway_client import GatewayTaskClient
    from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """你是一个代码分析专家。请为以下代码生成一个简洁的业务语义描述。
要求：
1. 用自然语言描述这个函数/类的业务用途（而非技术实现）
2. 包含它属于哪个业务领域
3. 它在业务流程中扮演的角色
4. 不超过 200 字

代码信息:
文件: {file}
名称: {name}
签名: {signature}
文档: {docstring}
代码片段: {code_snippet}"""


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
        if self._gw is not None:
            return await self._enrich_via_gateway(items)
        if self._llm is not None:
            return await self._enrich_via_llm(items)
        logger.warning("No LLM backend configured — skipping enrichment")
        return [""] * len(items)

    # ------------------------------------------------------------------
    # Gateway task mode — one task for the whole batch
    # ------------------------------------------------------------------

    async def _enrich_via_gateway(self, items: list[dict[str, str]]) -> list[str]:
        try:
            return await self._gw.enrich_batch(items)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Gateway task enrichment failed, falling back to per-item LLM")
            if self._llm is not None:
                return await self._enrich_via_llm(items)
            return [""] * len(items)

    # ------------------------------------------------------------------
    # Legacy per-item LLM mode
    # ------------------------------------------------------------------

    async def _enrich_via_llm(self, items: list[dict[str, str]]) -> list[str]:
        results: list[str] = [""] * len(items)
        groups: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
        for idx, item in enumerate(items):
            groups[item.get("file", "unknown")].append((idx, item))

        tasks = [
            self._enrich_file_group(file_path, group, results)
            for file_path, group in groups.items()
        ]
        await asyncio.gather(*tasks)
        return results

    async def _enrich_file_group(
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
                    docstring=item.get("docstring", "")[:500],
                    code_snippet=item.get("code_snippet", "")[:1000],
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
