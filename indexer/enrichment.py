"""Code summary enrichment — generates business_summary via LLM."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    """Batch-generates business summaries for code entities using LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def enrich_batch(self, items: list[dict[str, str]]) -> list[str]:
        """Generate business_summary for each item. Returns list of summaries (same order as input).
        On LLM failure, returns empty string for that item.
        """
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
                summary = await self._llm.complete(
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
