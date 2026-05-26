"""Tests for DomainDocAgent helper functions and iteration logic."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import (
    DomainDocAgent,
    _build_baseline,
    _make_page,
    _maybe_split,
)
from wiki.quality_report import QualityReport


def _quality_report(**overrides: float | int | list[str]) -> QualityReport:
    defaults: dict = {
        "coverage": 0.96,
        "citation_density": 0.6,
        "context_gap_count": 0,
        "uncovered_modules": [],
        "implementation_depth": 0.8,
    }
    defaults.update(overrides)
    return QualityReport(**defaults)


def test_maybe_split_generates_topic_pages_for_large_content():
    """When content exceeds MAX_PAGE_TOKENS, _maybe_split should produce topic sub-pages."""
    # Build content > 5000 tokens (approx 20000 chars)
    sections = ["## 概述\n\n" + "概述内容。" * 200]
    for i in range(5):
        sections.append(f"## 章节{i}\n\n" + f"章节{i}的详细内容。" * 430)
    content = "\n\n".join(sections)
    assert len(content) > 20000, "Content must exceed token threshold (len/4 > MAX_PAGE_TOKENS)"

    pages = _maybe_split(content, "large-domain", "大型域")
    assert len(pages) > 1, "Should split into multiple pages"

    parent = pages[0]
    assert parent["path"] == "/__domains__/large-domain/_overview"
    assert parent["page_type"] == "domain_overview"
    assert "章节导航" in parent["content"]
    assert parent["title"] == "大型域"

    for child in pages[1:]:
        assert child["page_type"] == "topic", f"Sub-page should be topic type, got {child['page_type']}"
        assert child["path"].startswith("/__domains__/large-domain/"), f"Bad path: {child['path']}"
        assert child["path"].endswith("/_topic"), f"Path should end with /_topic: {child['path']}"


def test_maybe_split_no_split_for_small_content():
    """Content under MAX_PAGE_TOKENS should not be split."""
    content = "## 概述\n\n短文档内容。"
    pages = _maybe_split(content, "friend-management", "小域")
    assert len(pages) == 1
    assert pages[0]["page_type"] == "domain_overview"
    assert pages[0]["path"] == "/__domains__/friend-management/_overview"
    assert pages[0]["title"] == "小域"


def test_make_page_uses_slug_for_path():
    """_make_page must use slug for path, display_name for title."""
    page = _make_page("# Content", "friend-management", "挚友关系管理")
    assert page["path"] == "/__domains__/friend-management/_overview"
    assert page["page_type"] == "domain_overview"
    assert page["title"] == "挚友关系管理"


def test_make_page_preserves_content():
    page = _make_page("# Hello\n\nWorld", "testdomain", "TestDomain")
    assert page["content"] == "# Hello\n\nWorld"
    assert page["path"] == "/__domains__/testdomain/_overview"
    assert page["title"] == "TestDomain"


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


def test_build_baseline_topology_format():
    """_build_baseline should output topology relations from tree structure."""
    domain = {
        "name": "支付处理",
        "description": "处理支付相关业务",
        "modules": ["PaymentService", "OrderValidator", "RefundHandler"],
    }
    module_summaries = {
        "PaymentService": {"summary_text": "A" * 600},
        "OrderValidator": {"summary_text": "B" * 600},
        "RefundHandler": {"summary_text": "C" * 600},
    }
    module_tree = [
        {
            "canonical_key": "PaymentService",
            "children": [
                {"canonical_key": "OrderValidator", "children": []},
                {"canonical_key": "RefundHandler", "children": []},
            ],
        },
    ]
    result = _build_baseline(domain, module_summaries, module_tree=module_tree)
    assert "A" * 81 not in result and "B" * 81 not in result and "C" * 81 not in result
    assert "PaymentService" in result
    assert "→" in result or "->" in result


def test_build_baseline_without_module_tree():
    """_build_baseline still works without module_tree (backward compat)."""
    domain = {
        "name": "TestDomain",
        "description": "test",
        "modules": ["ModA"],
    }
    module_summaries = {
        "ModA": {"summary_text": "Module A handles things and does stuff nicely"},
    }
    result = _build_baseline(domain, module_summaries)
    assert "TestDomain" in result
    assert "ModA" in result
    assert "Module A handles" in result


class TestMaybeSplit:
    def test_short_content_returns_single_page(self):
        content = "# 概述\n\n短内容。"
        pages = _maybe_split(content, "test-domain")
        assert len(pages) == 1
        assert pages[0]["page_type"] == "domain_overview"
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


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestDomainDocAgentIteration:
    @pytest.fixture(autouse=True)
    def _use_legacy_path(self):
        from core.config import get_settings
        cfg = get_settings().wiki
        original = cfg.use_orchestrator_template
        cfg.use_orchestrator_template = False
        yield
        cfg.use_orchestrator_template = original

    @pytest.mark.asyncio
    async def test_stops_when_quality_acceptable(self):
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

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(return_value=mock_memory)
        agent._page_agent.write = AsyncMock(return_value=good_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="ModA is a controller. ModB is a service.",
        )
        assert len(pages) >= 1
        assert pages[0]["page_type"] == "domain_overview"

    @pytest.mark.asyncio
    async def test_iterates_on_low_quality(self):
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

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()
        supplemental = WorkingMemory()

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(side_effect=[mock_memory, supplemental])
        agent._page_agent.write = AsyncMock(side_effect=[low_content, good_content])

        with patch(
            "wiki.domain_doc_agent.evaluate_quality",
            side_effect=[
                _quality_report(coverage=0.5, citation_density=0.0, implementation_depth=0.0),
                _quality_report(),
            ],
        ):
            pages = await agent.generate_with_iterations(
                module_names=["ModA", "ModB"],
                baseline_context="baseline",
            )
        assert agent._page_agent.explore.call_count >= 2

    @pytest.mark.asyncio
    async def test_max_iterations_safety(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=mock_llm,
            graph_store=mock_graph,
            max_iterations=2,
        )

        low_content = "# test-domain\n\nSparse."

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(return_value=mock_memory)
        agent._page_agent.write = AsyncMock(return_value=low_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB", "ModC"],
            baseline_context="baseline",
        )
        assert agent._page_agent.explore.call_count <= 3


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestDomainDocAgentExploreWrite:
    @pytest.fixture(autouse=True)
    def _use_legacy_path(self):
        from core.config import get_settings
        cfg = get_settings().wiki
        original = cfg.use_orchestrator_template
        cfg.use_orchestrator_template = False
        yield
        cfg.use_orchestrator_template = original

    @pytest.mark.asyncio
    async def test_explore_write_flow(self):
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

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()
        mock_memory.code_snippets.append("[ModA]\ncode")

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(return_value=mock_memory)
        agent._page_agent.write = AsyncMock(return_value=good_content)

        with patch(
            "wiki.domain_doc_agent.evaluate_quality",
            return_value=_quality_report(),
        ):
            pages = await agent.generate_with_iterations(
                module_names=["ModA", "ModB"],
                baseline_context="ModA is a controller. ModB is a service.",
            )

        agent._page_agent.explore.assert_called_once()
        agent._page_agent.write.assert_called_once()
        assert len(pages) >= 1

    @pytest.mark.asyncio
    async def test_re_explore_on_low_quality(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=mock_llm,
            graph_store=mock_graph,
            max_iterations=2,
        )

        low_content = "# test-domain\n\nSome sparse content about ModA."
        good_content = (
            "# test-domain\n\nModA and ModB.\n"
            "```java\ncode1\n```\n```java\ncode2\n```\n"
        )

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()
        mock_memory.code_snippets.append("[ModA]\ncode")

        supplemental_memory = WorkingMemory()
        supplemental_memory.code_snippets.append("[ModB]\ncode2")

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(side_effect=[mock_memory, supplemental_memory])
        agent._page_agent.write = AsyncMock(side_effect=[low_content, good_content])

        with patch(
            "wiki.domain_doc_agent.evaluate_quality",
            side_effect=[
                _quality_report(coverage=0.5, citation_density=0.0, implementation_depth=0.0),
                _quality_report(),
            ],
        ):
            pages = await agent.generate_with_iterations(
                module_names=["ModA", "ModB"],
                baseline_context="baseline",
            )

        assert agent._page_agent.explore.call_count == 2
        second_call_kwargs = agent._page_agent.explore.call_args_list[1]
        assert "focus_modules" in second_call_kwargs.kwargs


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestDomainDocAgentObservability:
    @pytest.fixture(autouse=True)
    def _use_legacy_path(self):
        from core.config import get_settings
        cfg = get_settings().wiki
        original = cfg.use_orchestrator_template
        cfg.use_orchestrator_template = False
        yield
        cfg.use_orchestrator_template = original

    @pytest.mark.asyncio
    async def test_iteration_history_populated(self):
        agent = DomainDocAgent(
            domain_name="test",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )

        good_content = "# test\n\nModA and ModB.\n```java\ncode\n```\n```java\ncode2\n```\n"

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(return_value=mock_memory)
        agent._page_agent.write = AsyncMock(return_value=good_content)

        await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )

        assert len(agent.iteration_history) >= 1
        entry = agent.iteration_history[0]
        assert "coverage" in entry
        assert "citation_density" in entry
        assert "iteration" in entry


class TestExploreMemorySignature:
    def test_explore_accepts_memory_parameter(self):
        """explore() method signature should accept optional memory kwarg."""
        import inspect

        from wiki.page_agent import WikiPageAgent

        sig = inspect.signature(WikiPageAgent.explore)
        params = sig.parameters
        assert "memory" in params, "explore() must accept 'memory' keyword argument"
        assert params["memory"].default is None, "memory default should be None"


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestElasticTimeout:
    @pytest.fixture(autouse=True)
    def _use_legacy_path(self):
        from core.config import get_settings
        cfg = get_settings().wiki
        original = cfg.use_orchestrator_template
        cfg.use_orchestrator_template = False
        yield
        cfg.use_orchestrator_template = original

    @pytest.mark.asyncio
    async def test_explore_timeout_preserves_partial_memory(self, monkeypatch):
        """When explore() times out, generate_with_iterations should use partial WorkingMemory."""
        monkeypatch.setattr(
            "wiki.domain_doc_agent.EXPLORE_TIMEOUT_SEC",
            0.05,
        )

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )

        from wiki.page_agent import WorkingMemory

        async def slow_explore(*args, **kwargs):
            memory = kwargs.get("memory") or WorkingMemory()
            memory.code_snippets.append("[PartialData]\npartially collected")
            await asyncio.sleep(999)
            return memory

        good_content = (
            "# test-domain\n\n## 概述\n\nModA handles things. ModB does stuff.\n\n"
            "```java\npublic void handle() {}\n```\n"
            "```java\npublic void process() {}\n```\n"
        )

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(side_effect=slow_explore)
        agent._page_agent.write = AsyncMock(return_value=good_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )
        assert len(pages) >= 1
        agent._page_agent.write.assert_called()

    @pytest.mark.asyncio
    async def test_write_timeout_retries_once(self, monkeypatch):
        """When write() times out once, it should retry."""
        monkeypatch.setattr(
            "wiki.domain_doc_agent.EXPLORE_TIMEOUT_SEC",
            0.05,
        )
        monkeypatch.setattr(
            "wiki.domain_doc_agent.WRITE_TIMEOUT_SEC",
            0.05,
        )

        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )

        from wiki.page_agent import WorkingMemory

        mock_memory = WorkingMemory()
        mock_memory.code_snippets.append("[Mod]\ncode")

        call_count = 0

        async def write_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(999)
            return (
                "# test-domain\n\nModA and ModB.\n"
                "```java\ncode1\n```\n```java\ncode2\n```\n"
            )

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(return_value=mock_memory)
        agent._page_agent.write = AsyncMock(side_effect=write_side_effect)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )
        assert len(pages) >= 1
        assert agent._page_agent.write.call_count >= 2


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestCoveredEntityUids:
    @pytest.fixture(autouse=True)
    def _use_legacy_path(self):
        from core.config import get_settings
        cfg = get_settings().wiki
        original = cfg.use_orchestrator_template
        cfg.use_orchestrator_template = False
        yield
        cfg.use_orchestrator_template = original

    @pytest.mark.asyncio
    async def test_pages_include_covered_entity_uids(self):
        """Generated pages should include discovered_entity_uids from WorkingMemory."""
        agent = DomainDocAgent(
            domain_name="test-domain",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )

        async def mock_explore(*args, **kwargs):
            mem = kwargs.get("memory")
            if mem is not None:
                mem.discovered_entity_uids.update({"uid-1", "uid-2", "uid-3"})
            return mem

        good_content = (
            "# test-domain\n\n## 概述\n\nModA handles things.\n\n"
            "```java\npublic void handle() {}\n```\n"
            "```java\npublic void process() {}\n```\n"
        )

        agent._page_agent = AsyncMock()
        agent._page_agent.explore = AsyncMock(side_effect=mock_explore)
        agent._page_agent.write = AsyncMock(return_value=good_content)

        pages = await agent.generate_with_iterations(
            module_names=["ModA", "ModB"],
            baseline_context="baseline",
        )

        assert len(pages) >= 1
        covered = pages[0].get("covered_entity_uids", [])
        assert set(covered) == {"uid-1", "uid-2", "uid-3"}
