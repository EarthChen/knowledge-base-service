"""Document concept extraction — extracts business concepts from documents using LLM."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """以下是项目文档。请提取其中的业务概念和业务流程。

文档内容:
{content}

请输出 JSON:
{{
  "concepts": [
    {{"name": "概念名称", "description": "概念描述", "aliases": ["别名1", "别名2"], "category": "分类"}}
  ],
  "flows": [
    {{"name": "流程名称", "description": "流程描述", "category": "分类"}}
  ]
}}

如果文档中没有明确的业务概念或流程，返回空列表。"""


class ConceptExtractor:
    """Extracts business concepts and flow descriptions from documents."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        concept_extraction_enabled: bool | None = None,
    ) -> None:
        self._llm = llm
        if concept_extraction_enabled is None:
            from core.config import get_settings

            concept_extraction_enabled = get_settings().llm.concept_extraction_enabled
        self._concept_extraction_enabled = concept_extraction_enabled

    async def extract(self, content: str) -> dict[str, list[dict[str, Any]]]:
        """Extract concepts and flows from document content."""
        if not self._concept_extraction_enabled:
            return {"concepts": [], "flows": []}
        if not content or not content.strip():
            return {"concepts": [], "flows": []}

        prompt = _EXTRACT_PROMPT.format(content=content[:3000])
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
            )
        except Exception:
            logger.warning("Failed to extract concepts from document", exc_info=True)
            return {"concepts": [], "flows": []}

    async def extract_batch(self, documents: list[dict[str, str]]) -> list[dict[str, list[dict[str, Any]]]]:
        """Extract concepts from multiple documents."""
        import asyncio

        tasks = [self.extract(doc.get("content", "")) for doc in documents]
        return await asyncio.gather(*tasks)
