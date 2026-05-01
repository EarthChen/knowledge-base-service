"""Tests for adaptive reasoning level selection and enhancement."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.domain_complexity import DomainComplexity
from wiki.reasoning import (
    GuidedPromptEnhancer,
    MultiStepReasoner,
    ReasoningLevel,
    TaskType,
    select_reasoning_level,
)


class TestSelectReasoningLevel:
    def test_compose_low_returns_none(self):
        assert select_reasoning_level(TaskType.COMPOSE, DomainComplexity.LOW) == ReasoningLevel.NONE

    def test_compose_medium_returns_guided(self):
        assert select_reasoning_level(TaskType.COMPOSE, DomainComplexity.MEDIUM) == ReasoningLevel.GUIDED

    def test_compose_high_returns_multi_step(self):
        assert select_reasoning_level(TaskType.COMPOSE, DomainComplexity.HIGH) == ReasoningLevel.MULTI_STEP

    def test_classify_high_returns_guided(self):
        assert select_reasoning_level(TaskType.CLASSIFY, DomainComplexity.HIGH) == ReasoningLevel.GUIDED

    def test_heal_low_returns_guided(self):
        assert select_reasoning_level(TaskType.HEAL, DomainComplexity.LOW) == ReasoningLevel.GUIDED

    def test_heal_medium_returns_multi_step(self):
        assert select_reasoning_level(TaskType.HEAL, DomainComplexity.MEDIUM) == ReasoningLevel.MULTI_STEP

    def test_overview_low_returns_guided(self):
        assert select_reasoning_level(TaskType.OVERVIEW, DomainComplexity.LOW) == ReasoningLevel.GUIDED

    def test_overview_high_returns_multi_step(self):
        assert select_reasoning_level(TaskType.OVERVIEW, DomainComplexity.HIGH) == ReasoningLevel.MULTI_STEP


class TestGuidedPromptEnhancer:
    def setup_method(self):
        self.enhancer = GuidedPromptEnhancer()

    def test_enhance_classify_prepends_analysis(self):
        original = "Classify these modules into domains."
        result = self.enhancer.enhance_classify_prompt(original)
        assert "Before classifying, analyze:" in result
        assert result.endswith(original)

    def test_enhance_overview_prepends_analysis(self):
        original = "Generate overview for domain X."
        result = self.enhancer.enhance_overview_prompt(original)
        assert "Before writing the overview, analyze:" in result
        assert result.endswith(original)

    def test_enhance_heal_prepends_diagnostic(self):
        original = "Improve this wiki page."
        result = self.enhancer.enhance_heal_prompt(original)
        assert "Before rewriting, analyze:" in result
        assert result.endswith(original)


class TestMultiStepReasoner:
    def setup_method(self):
        self.reasoner = MultiStepReasoner()

    @pytest.mark.asyncio
    async def test_plan_and_compose_makes_two_llm_calls(self):
        llm = AsyncMock()
        plan_json = json.dumps(
            {
                "sections": [
                    {"heading": "业务概述", "key_points": ["order processing"]},
                    {"heading": "核心流程", "key_points": ["create→pay→ship"]},
                ],
                "diagrams": ["sequenceDiagram showing order flow"],
            }
        )
        llm.generate = AsyncMock(side_effect=[plan_json, "# Order Domain\n\n## 业务概述\nContent..."])
        domain = {
            "name": "order",
            "biz_entities": [{"name": "OrderService", "summary": "handles orders", "methods": ["create"], "calls": []}],
        }

        result = await self.reasoner.plan_and_compose(domain, llm, system="test", max_tokens=4000)

        assert llm.generate.call_count == 2
        assert "Order Domain" in result or "order" in result.lower()

    @pytest.mark.asyncio
    async def test_plan_and_compose_fallback_on_bad_plan(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=["not valid json", "# Fallback Content\nGenerated"])
        domain = {"name": "order", "biz_entities": []}

        result = await self.reasoner.plan_and_compose(domain, llm, system="test", max_tokens=4000)

        assert llm.generate.call_count == 2
        assert "Fallback" in result or len(result) > 0

    @pytest.mark.asyncio
    async def test_plan_and_overview_makes_two_llm_calls(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=["Domain A handles payments. Domain B handles orders.", "# System Overview\n..."])
        result = await self.reasoner.plan_and_overview("summary", llm, system="test", max_tokens=4000)

        assert llm.generate.call_count == 2
        assert len(result) > 0
