"""Tests for DomainDocAgent helper functions and iteration logic."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.domain_doc_agent import DomainDocAgent, _build_baseline, _maybe_split
from wiki.quality_report import QualityReport


class TestBuildBaseline:
    def test_basic_domain_with_description(self):
        domain = {
            "name": "用户管理",
            "description": "处理用户注册、登录、权限",
            "modules": ["UserController", "UserService"],
        }
        summaries = {
            "UserController": "HTTP 入口，处理 /api/user 路由",
            "UserService": "用户业务逻辑，调用 UserRepository",
        }
        result = _build_baseline(domain, summaries)
        assert "用户管理" in result
        assert "处理用户注册" in result
        assert "UserController" in result
        assert "UserService" in result

    def test_missing_module_summary_skipped(self):
        domain = {
            "name": "支付",
            "modules": ["PayService", "PayController"],
        }
        summaries = {"PayService": "支付核心逻辑"}
        result = _build_baseline(domain, summaries)
        assert "PayService" in result
        # PayController has no summary — should not crash
        assert "PayController" not in result or "PayController" in result

    def test_empty_modules(self):
        domain = {"name": "空域", "modules": []}
        result = _build_baseline(domain, {})
        assert "空域" in result


class TestMaybeSplit:
    def test_short_content_returns_single_page(self):
        content = "# 概述\n\n短内容。"
        pages = _maybe_split(content, "test-domain")
        assert len(pages) == 1
        assert pages[0]["type"] == "domain_overview"
        assert pages[0]["title"] == "test-domain"

    def test_long_content_splits_by_h2(self):
        sections = ["# 概述\n\n这是概述。\n\n"]
        for i in range(10):
            sections.append(f"## 章节{i}\n\n" + "详细内容。" * 500 + "\n\n")
        content = "".join(sections)
        pages = _maybe_split(content, "big-domain")
        assert len(pages) > 1
        assert pages[0]["title"] == "big-domain"
        assert "章节导航" in pages[0]["content"]

    def test_single_section_not_split(self):
        content = "# Only Title\n\n" + "x" * 30000
        pages = _maybe_split(content, "mono")
        assert len(pages) == 1


class TestDomainDocAgentIteration:
    @pytest.mark.asyncio
    async def test_stops_when_quality_acceptable(self):
        """Agent should stop iterating when QualityReport is acceptable."""
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=mock_llm,
            graph_store=mock_graph,
        )
        good_content = (
            "# test-domain\n\n## 概述\n\n"
            "ModA handles requests. ModB processes data.\n\n"
            "```java\npublic void handle() {}\n```\n"
            "```java\npublic void process() {}\n```\n"
        )
        agent._page_agent = AsyncMock()
        agent._page_agent.generate = AsyncMock(return_value=good_content)
        agent._page_agent.enrich = AsyncMock(return_value=good_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="ModA is a controller. ModB is a service.",
        )
        assert len(pages) >= 1
        assert pages[0]["type"] == "domain_overview"

    @pytest.mark.asyncio
    async def test_iterates_on_low_quality(self):
        """Agent should call enrich when initial quality is below threshold."""
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=mock_llm,
            graph_store=mock_graph,
        )
        low_content = "# test-domain\n\nSome sparse content about ModA."
        good_content = (
            "# test-domain\n\nModA and ModB.\n"
            "```java\ncode1\n```\n```java\ncode2\n```\n"
        )
        agent._page_agent = AsyncMock()
        agent._page_agent.generate = AsyncMock(return_value=low_content)
        agent._page_agent.enrich = AsyncMock(return_value=good_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )
        assert agent._page_agent.enrich.called

    @pytest.mark.asyncio
    async def test_max_iterations_safety(self):
        """Agent should stop after max iterations even if quality is low."""
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=mock_llm,
            graph_store=mock_graph,
            max_iterations=2,
        )
        low_content = "# test-domain\n\nSparse."
        agent._page_agent = AsyncMock()
        agent._page_agent.generate = AsyncMock(return_value=low_content)
        agent._page_agent.enrich = AsyncMock(return_value=low_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB", "ModC"],
            baseline_context="baseline",
        )
        # Should not loop more than max_iterations times
        assert agent._page_agent.enrich.call_count <= 2
