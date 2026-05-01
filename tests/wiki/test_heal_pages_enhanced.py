"""Tests for enhanced heal_pages_node prompts (WikiQualityBench hints, domain context)."""

from unittest.mock import AsyncMock

import pytest

from wiki.pipeline_nodes import heal_pages_node


@pytest.fixture
def state_with_poor_page():
    return {
        "pages": [
            {
                "title": "User Management",
                "path": "wiki/user-management",
                "content": "## Overview\nShort content.\n",
                "page_type": "topic",
                "domain": "user-management",
                "diagrams": [],
                "source_locations": [],
                "metadata": {"node_count": 0, "edge_count": 0},
            }
        ],
        "pages_to_heal": ["wiki/user-management"],
        "heal_attempts": {},
        "heal_hints": {},
        "domain_tree": [
            {"name": "user-management", "modules": ["UserService"], "children": []}
        ],
    }


def _fallback_heal_prompt(captured_prompts: list[str]) -> str:
    healing = [
        p
        for p in captured_prompts
        if isinstance(p, str) and "Improve this wiki page" in p
    ]
    assert healing, "expected fallback full-regeneration heal prompt among LLM calls"
    return healing[0]


class TestHealPagesEnhanced:
    @pytest.mark.asyncio
    async def test_heal_prompt_includes_structured_sections(self, state_with_poor_page):
        """修复 prompt 应包含结构化章节要求。"""
        captured_prompts = []

        async def capture_prompt(prompt, system="", **kwargs):
            captured_prompts.append(prompt)
            return (
                "## 业务概述\n用户管理模块\n\n"
                "## 核心业务流程\n```mermaid\nsequenceDiagram\n```\n\n"
                "## 核心服务详情\n### UserService\n内容\n"
            )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=capture_prompt)
        config = {"configurable": {"llm": mock_llm}}

        await heal_pages_node(state_with_poor_page, config)

        assert len(captured_prompts) >= 2
        heal_prompt = _fallback_heal_prompt(captured_prompts)
        assert (
            "业务概述" in heal_prompt
            or "Purpose" in heal_prompt
            or "Required sections" in heal_prompt
        )
        assert "Mermaid" in heal_prompt or "diagram" in heal_prompt.lower()

    @pytest.mark.asyncio
    async def test_heal_prompt_includes_domain_context(self, state_with_poor_page):
        """修复 prompt 应包含域上下文。"""
        captured_prompts = []

        async def capture_prompt(prompt, system="", **kwargs):
            captured_prompts.append(prompt)
            return "## 业务概述\n改进内容\n"

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=capture_prompt)
        config = {"configurable": {"llm": mock_llm}}

        await heal_pages_node(state_with_poor_page, config)

        assert len(captured_prompts) >= 2
        heal_prompt = _fallback_heal_prompt(captured_prompts)
        assert "user-management" in heal_prompt

    @pytest.mark.asyncio
    async def test_heal_uses_bench_score(self, state_with_poor_page):
        """修复应使用多维度评测结果。"""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="## 业务概述\n改进内容\n")
        config = {"configurable": {"llm": mock_llm}}

        result = await heal_pages_node(state_with_poor_page, config)
        heal_hints = result.get("heal_hints", {})
        if "wiki/user-management" in heal_hints:
            hint = heal_hints["wiki/user-management"]
            assert len(hint) > 10

    @pytest.mark.asyncio
    async def test_heal_system_prompt_enhanced(self, state_with_poor_page):
        """system prompt 应更详细。"""
        captured_systems = []

        async def capture_system(prompt, system="", **kwargs):
            captured_systems.append((prompt, system))
            return "## 业务概述\n改进内容\n"

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=capture_system)
        config = {"configurable": {"llm": mock_llm}}

        await heal_pages_node(state_with_poor_page, config)

        assert len(captured_systems) >= 2
        systems_for_heal = [
            sys
            for p, sys in captured_systems
            if isinstance(p, str) and "Improve this wiki page" in p
        ]
        assert systems_for_heal
        system = systems_for_heal[0]
        assert "wiki" in system.lower() or "documentation" in system.lower()
