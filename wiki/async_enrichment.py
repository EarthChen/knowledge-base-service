"""Async multi-round enrichment pipeline for wiki pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from log import get_logger
from wiki.models import EnrichmentLevel, ImportanceTier, WikiPage
from wiki.tiered_prompts import TieredPromptBuilder

if TYPE_CHECKING:
    from wiki.context import LLMPort

log = get_logger(__name__)


class AsyncEnrichmentPipeline:
    """Enriches a WikiPage through multiple LLM rounds based on importance tier.

    - Round 1 (enrichment): core + standard entities
    - Round 2 (encyclopedia): core only
    """

    def __init__(
        self,
        llm: LLMPort,
        *,
        round1_enabled: bool = True,
        round2_enabled: bool = True,
    ) -> None:
        self._llm = llm
        self._round1_enabled = round1_enabled
        self._round2_enabled = round2_enabled
        self._prompt_builder = TieredPromptBuilder()

    async def enrich_page(
        self,
        page: WikiPage,
        entity_name: str,
        entity_label: str,
        tier: ImportanceTier,
        language: str = "en",
    ) -> WikiPage:
        if tier == ImportanceTier.SKELETON:
            return page

        current_level = EnrichmentLevel.BASE

        # Round 1: enrichment layer for core + standard
        if self._round1_enabled and tier in (ImportanceTier.CORE, ImportanceTier.STANDARD):
            round1_result = await self._run_round1(page, entity_name, entity_label, language)
            if round1_result:
                page.content = page.content.rstrip() + "\n\n" + round1_result.strip() + "\n"
                current_level = EnrichmentLevel.ENRICHED

        # Round 2: encyclopedia layer for core only (requires Round 1 success)
        if (
            self._round2_enabled
            and tier == ImportanceTier.CORE
            and current_level == EnrichmentLevel.ENRICHED
        ):
            round2_result = await self._run_round2(page, entity_name, entity_label, language)
            if round2_result:
                page.content = page.content.rstrip() + "\n\n" + round2_result.strip() + "\n"
                current_level = EnrichmentLevel.ENCYCLOPEDIA

        page.metadata.enrichment_level = current_level
        return page

    async def _run_round1(self, page, entity_name, entity_label, language) -> str | None:
        prompt = self._prompt_builder.build_enrichment_prompt(
            page_content=page.content,
            entity_name=entity_name,
            entity_label=entity_label,
            language=language,
        )
        system = self._prompt_builder.enrichment_system_prompt(language)
        try:
            result = await self._llm.generate(prompt, system=system)
            return result.strip() if result and result.strip() else None
        except Exception:
            log.warning("enrichment_round1_failed", entity=entity_name, exc_info=True)
            return None

    async def _run_round2(self, page, entity_name, entity_label, language) -> str | None:
        prompt = self._prompt_builder.build_encyclopedia_prompt(
            page_content=page.content,
            entity_name=entity_name,
            entity_label=entity_label,
            language=language,
        )
        system = self._prompt_builder.encyclopedia_system_prompt(language)
        try:
            result = await self._llm.generate(prompt, system=system)
            return result.strip() if result and result.strip() else None
        except Exception:
            log.warning("enrichment_round2_failed", entity=entity_name, exc_info=True)
            return None
