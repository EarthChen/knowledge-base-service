"""compose_pages_node integration with SemanticDiagramGenerator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import compose_pages_node


def _many_methods(prefix: str, n: int = 11) -> list[str]:
    """Enough methods per entity for DomainComplexityScorer to choose MEDIUM depth."""
    return [f"{prefix}_m{i}" for i in range(n)]


@pytest.fixture
def base_state():
    # Three business-logic modules × ~11 methods → raw_score > low_threshold (see domain_complexity).
    return {
        "domain_tree": [
            {
                "name": "user-management",
                "modules": ["UserService", "AuthService", "NotifyService"],
                "children": [],
            }
        ],
        "entity_roles": {
            "Module::UserService:0": "has_business_logic",
            "Module::AuthService:0": "has_business_logic",
            "Module::NotifyService:0": "has_business_logic",
        },
        "modules": {
            "repo1": [
                {
                    "uid": "Module::UserService:0",
                    "label": "Module",
                    "properties": {
                        "name": "UserService",
                        "business_summary": "User management service",
                        "methods": _many_methods("createUser"),
                        "calls": ["AuthService.validateToken"],
                    },
                },
                {
                    "uid": "Module::AuthService:0",
                    "label": "Module",
                    "properties": {
                        "name": "AuthService",
                        "business_summary": "Authentication service",
                        "methods": _many_methods("generateToken"),
                        "calls": [],
                    },
                },
                {
                    "uid": "Module::NotifyService:0",
                    "label": "Module",
                    "properties": {
                        "name": "NotifyService",
                        "business_summary": "Notification dispatch service",
                        "methods": _many_methods("notify"),
                        "calls": [],
                    },
                },
            ]
        },
    }


async def _llm_side_effect_wiki_and_mermaid(prompt: str, system: str = "", **kwargs) -> str:
    if any(
        s in prompt
        for s in (
            "Generate a wiki page",
            "Generate a domain overview",
            "Generate a wiki sub-page",
            "Group these",
        )
    ):
        return "## 业务概述\n用户管理模块\n## 核心业务流程\n..."
    pl = prompt.lower()
    if "overview context" in pl:
        return "graph TD\n  A-->B"
    if "statediagram-v2" in pl:
        return "stateDiagram-v2\n[*] --> A\n"
    if "flowchart" in pl and "data processing" in pl:
        return "flowchart TD\n  A-->B\n"
    return "sequenceDiagram\n    participant U as UserSvc\n    participant A as AuthSvc\n    U->>A: validate\n"


class TestComposePagesWithDiagrams:
    @pytest.mark.asyncio
    async def test_pages_include_diagrams(self, base_state):
        """生成的页面应包含 diagrams 字段。"""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=_llm_side_effect_wiki_and_mermaid)
        config = {"configurable": {"llm": mock_llm}}

        result = await compose_pages_node(base_state, config)
        pages = result.get("pages", [])
        assert len(pages) > 0
        has_diagrams = any(p.get("diagrams") for p in pages)
        assert has_diagrams, "At least one page should have diagrams"

    @pytest.mark.asyncio
    async def test_diagram_generation_failure_no_crash(self, base_state):
        """图表生成失败不应阻塞页面生成。"""
        mock_llm = AsyncMock()

        async def side_effect(prompt, system="", **kwargs):
            if any(
                s in prompt
                for s in (
                    "Generate a wiki page",
                    "Generate a domain overview",
                    "Generate a wiki sub-page",
                    "Group these",
                )
            ):
                return "## 业务概述\n内容\n## 核心业务流程\n..."
            raise RuntimeError("LLM diagram generation failed")

        mock_llm.generate = AsyncMock(side_effect=side_effect)
        config = {"configurable": {"llm": mock_llm}}

        result = await compose_pages_node(base_state, config)
        pages = result.get("pages", [])
        assert len(pages) > 0

    @pytest.mark.asyncio
    async def test_no_diagrams_without_llm(self, base_state):
        """没有 LLM 时不生成图表。"""
        config = {"configurable": {}}
        result = await compose_pages_node(base_state, config)
        pages = result.get("pages", [])
        for p in pages:
            assert not p.get("diagrams"), "No diagrams without LLM"
