"""tests/wiki/test_system_overview.py — Sprint 2 tests for System Architecture Overview."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGetRepoStats:
    @pytest.mark.asyncio
    async def test_get_repo_stats_returns_counts(self):
        """get_repo_stats should return module/class/function counts."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        # Simulate results for Module, Class, Function count queries
        module_result = MagicMock()
        module_result.result_set = [[5]]
        class_result = MagicMock()
        class_result.result_set = [[20]]
        func_result = MagicMock()
        func_result.result_set = [[100]]

        mock_graph.query.side_effect = [module_result, class_result, func_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                stats = await store.get_repo_stats("test-repo")

        assert isinstance(stats, dict)
        assert stats["module_count"] == 5
        assert stats["class_count"] == 20
        assert stats["function_count"] == 100

    @pytest.mark.asyncio
    async def test_get_repo_stats_empty_repo(self):
        """Empty/nonexistent repo should return zero counts."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        empty_result = MagicMock()
        empty_result.result_set = [[0]]
        mock_graph.query.side_effect = [empty_result, empty_result, empty_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                stats = await store.get_repo_stats("nonexistent_repo")

        assert stats["module_count"] == 0
        assert stats["class_count"] == 0
        assert stats["function_count"] == 0

    @pytest.mark.asyncio
    async def test_get_repo_stats_handles_query_failure(self):
        """If a query fails, that count should be 0."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()

        module_result = MagicMock()
        module_result.result_set = [[3]]
        # Second query fails, third returns normally
        func_result = MagicMock()
        func_result.result_set = [[10]]
        mock_graph.query.side_effect = [module_result, Exception("DB error"), func_result]
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                stats = await store.get_repo_stats("partial-repo")

        assert stats["module_count"] == 3
        assert stats["class_count"] == 0
        assert stats["function_count"] == 10
        assert stats["query_failed"] is True


class TestSystemOverviewComposer:
    @pytest.mark.asyncio
    async def test_compose_returns_wiki_page(self):
        """SystemOverviewComposer.compose should return a WikiPage with REPO_OVERVIEW type."""
        from wiki.system_overview_composer import SystemOverviewComposer
        from wiki.models import WikiPage, PageType

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=(
            "## System Purpose\nE-commerce platform\n\n"
            "## Microservice Architecture\n```mermaid\ngraph TD\nA-->B\n```\n\n"
            "## Repositories\n### user-service\nHandles user management\n\n"
            "## Business Domains\n- User Management\n\n"
            "## Cross-Service Communication\nRPC via Dubbo\n\n"
            "## Key Entry Points\n- UserController\n\n"
            "## Technology Stack Summary\nJava, Spring Boot, MySQL"
        ))
        composer = SystemOverviewComposer(mock_llm)
        page = await composer.compose(
            business_id="test_biz",
            repositories=["user-service", "order-service"],
            domain_tree=[],
            entry_points_by_repo={"user-service": ["UserController"], "order-service": ["OrderController"]},
            domain_overviews={"User Management": "Handles users"},
            stats_by_repo={"user-service": {"module_count": 5, "class_count": 20, "function_count": 100}},
            language="en",
        )
        assert isinstance(page, WikiPage)
        assert page.page_type == PageType.REPO_OVERVIEW
        assert "system_overview_" in page.path

    @pytest.mark.asyncio
    async def test_compose_includes_all_repos(self):
        """LLM prompt should mention all repositories."""
        from wiki.system_overview_composer import SystemOverviewComposer

        captured_prompts = []
        mock_llm = AsyncMock()

        async def tracking_generate(prompt, system="", **kwargs):
            captured_prompts.append(prompt)
            return "# Overview\nTest content"

        mock_llm.generate = tracking_generate
        composer = SystemOverviewComposer(mock_llm)
        await composer.compose(
            business_id="test_biz",
            repositories=["user-service", "order-service", "payment-service"],
            domain_tree=[],
            entry_points_by_repo={},
            domain_overviews={},
            stats_by_repo={},
            language="en",
        )
        assert len(captured_prompts) >= 1
        prompt = captured_prompts[0]
        assert "user-service" in prompt
        assert "order-service" in prompt
        assert "payment-service" in prompt

    @pytest.mark.asyncio
    async def test_compose_has_mermaid(self):
        """Mermaid blocks are extracted to diagrams, not duplicated in page body."""
        from wiki.system_overview_composer import SystemOverviewComposer

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="# Overview\n```mermaid\ngraph TD\nA-->B\n```\nDone.")
        composer = SystemOverviewComposer(mock_llm)
        page = await composer.compose(
            business_id="test_biz",
            repositories=["svc-a"],
            domain_tree=[],
            entry_points_by_repo={},
            domain_overviews={},
            stats_by_repo={},
            language="en",
        )
        assert "mermaid" not in page.content.lower()
        assert page.diagrams
        assert "graph td" in page.diagrams[0].content.lower()
        assert "overview" in page.content.lower() and "done" in page.content.lower()

    @pytest.mark.asyncio
    async def test_compose_fallback_on_llm_failure(self):
        """If LLM fails, should produce fallback content."""
        from wiki.system_overview_composer import SystemOverviewComposer
        from wiki.models import WikiPage

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        composer = SystemOverviewComposer(mock_llm)
        page = await composer.compose(
            business_id="test_biz",
            repositories=["svc-a", "svc-b"],
            domain_tree=[],
            entry_points_by_repo={},
            domain_overviews={},
            stats_by_repo={"svc-a": {"module_count": 3, "class_count": 10, "function_count": 30}},
            language="en",
        )
        assert isinstance(page, WikiPage)
        assert "svc-a" in page.content
        assert "svc-b" in page.content

    @pytest.mark.asyncio
    async def test_compose_without_llm(self):
        """When no LLM is provided, should produce structural content."""
        from wiki.system_overview_composer import SystemOverviewComposer
        from wiki.models import WikiPage

        composer = SystemOverviewComposer(None)
        page = await composer.compose(
            business_id="test_biz",
            repositories=["svc-a"],
            domain_tree=[],
            entry_points_by_repo={"svc-a": ["Main"]},
            domain_overviews={"Core": "Core domain"},
            stats_by_repo={"svc-a": {"module_count": 2, "class_count": 5, "function_count": 10}},
            language="en",
        )
        assert isinstance(page, WikiPage)
        assert "svc-a" in page.content


class TestSystemOverviewIntegration:
    def test_service_creates_system_overview(self):
        """generate_business_wiki should use LangGraph pipeline (which includes synthesize_overviews_node)."""
        import inspect

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        source = inspect.getsource(BusinessPipelineRunner.run)
        assert "run_langgraph_pipeline" in source

    def test_domain_sort_idx_starts_from_1(self):
        """Domain section sort_idx should start from 1 (not 0) since system overview takes position 0."""
        import inspect

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        source = inspect.getsource(BusinessPipelineRunner.run)
        assert "sort_idx = 1" in source
