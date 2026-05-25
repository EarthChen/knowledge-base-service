"""tests/wiki/test_business_domain_injection.py"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBusinessDomainProperty:
    def test_update_business_domain_allowed(self):
        """business_domain should be in allowed properties for update_node_property."""
        from store.falkordb_store import FalkorDBStore

        assert "business_domain" in FalkorDBStore._ALLOWED_PROPERTIES


class TestFindDescendants:
    @pytest.mark.asyncio
    async def test_find_descendants_returns_children(self):
        """find_descendants should return UIDs of CONTAINS descendants."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = [["child_class_uid"], ["child_func_uid"]]
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                result = await store.find_descendants(
                    "module_uid", edge_type="CONTAINS", max_depth=3
                )

        assert isinstance(result, list)
        assert "child_class_uid" in result
        assert "child_func_uid" in result

    @pytest.mark.asyncio
    async def test_find_descendants_empty_for_leaf(self):
        """Leaf node should return empty descendants list."""
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore.__new__(FalkorDBStore)
        mock_graph = MagicMock()
        mock_result = MagicMock()
        mock_result.result_set = []
        mock_graph.query.return_value = mock_result
        store._graph = mock_graph

        with patch("store.falkordb_store._graph_executor", None):
            with patch("asyncio.get_running_loop") as mock_loop:
                def run_executor(ex, fn):
                    return fn()

                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=lambda ex, fn: run_executor(ex, fn)
                )

                result = await store.find_descendants(
                    "leaf_uid", edge_type="CONTAINS", max_depth=3
                )

        assert result == []


class TestDomainEntryPoints:
    def test_entry_points_not_hardcoded_empty(self):
        """Verify that generate_business_wiki source code no longer has 'domain_entry_points: list[str] = []'."""
        import inspect

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        source = inspect.getsource(BusinessPipelineRunner.run)
        assert "all_entry_point_pairs" in source, (
            "BusinessPipelineRunner.run should reference all_entry_point_pairs"
        )


class TestBusinessDomainInjection:
    def test_entity_digest_includes_business_domain(self):
        """When business_domain is set on node properties, _entity_digest should include it."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType
        from store.schema import GraphNode, NodeLabel

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(uid="test_uid", label=NodeLabel.CLASS, properties={
            "name": "UserService",
            "business_domain": "User Management",
            "path": "user_service.py",
        })
        from dataclasses import dataclass, field
        from typing import Any

        @dataclass
        class FakePageData:
            node: Any
            edges: list = field(default_factory=list)
            children: list = field(default_factory=list)
            methods: list = field(default_factory=list)
            code_snippets: list = field(default_factory=list)
            related_chunks: list = field(default_factory=list)

        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
        assert "Business Domain: User Management" in digest

    def test_entity_digest_no_domain_when_absent(self):
        """When business_domain is not set, digest should not contain domain line."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType
        from store.schema import GraphNode, NodeLabel

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(uid="test_uid", label=NodeLabel.CLASS, properties={
            "name": "UserService",
            "path": "user_service.py",
        })
        from dataclasses import dataclass, field
        from typing import Any

        @dataclass
        class FakePageData:
            node: Any
            edges: list = field(default_factory=list)
            children: list = field(default_factory=list)
            methods: list = field(default_factory=list)
            code_snippets: list = field(default_factory=list)
            related_chunks: list = field(default_factory=list)

        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.CLASS_DETAIL)
        assert "Business Domain" not in digest


class TestModuleDescriptionInjection:
    def test_entity_digest_includes_module_description(self):
        """Module description should appear in digest when present and different from business_summary."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType
        from store.schema import GraphNode, NodeLabel

        composer = WikiComposer.__new__(WikiComposer)
        node = GraphNode(uid="test_uid", label=NodeLabel.MODULE, properties={
            "name": "UserModule",
            "path": "user_module.py",
            "description": "Handles user registration and authentication workflows",
            "business_summary": "User service module",
        })
        from dataclasses import dataclass, field
        from typing import Any

        @dataclass
        class FakePageData:
            node: Any
            edges: list = field(default_factory=list)
            children: list = field(default_factory=list)
            methods: list = field(default_factory=list)
            code_snippets: list = field(default_factory=list)
            related_chunks: list = field(default_factory=list)

        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.MODULE_OVERVIEW)
        assert "Module Description:" in digest
        assert "Handles user registration" in digest

    def test_entity_digest_no_description_when_same_as_summary(self):
        """Module description should be skipped if identical to business_summary."""
        from wiki.composer import WikiComposer
        from wiki.models import PageType
        from store.schema import GraphNode, NodeLabel

        composer = WikiComposer.__new__(WikiComposer)
        same_text = "User service module"
        node = GraphNode(uid="test_uid", label=NodeLabel.MODULE, properties={
            "name": "UserModule",
            "path": "user_module.py",
            "description": same_text,
            "business_summary": same_text,
        })
        from dataclasses import dataclass, field
        from typing import Any

        @dataclass
        class FakePageData:
            node: Any
            edges: list = field(default_factory=list)
            children: list = field(default_factory=list)
            methods: list = field(default_factory=list)
            code_snippets: list = field(default_factory=list)
            related_chunks: list = field(default_factory=list)

        page_data = FakePageData(node=node)
        digest = composer._entity_digest(page_data, PageType.MODULE_OVERVIEW)
        assert "Module Description:" not in digest


class TestDomainPersistence:
    def test_service_persists_domain_in_source(self):
        """generate_business_wiki should contain domain persistence logic."""
        import inspect

        from wiki.business_pipeline_runner import BusinessPipelineRunner

        source = inspect.getsource(BusinessPipelineRunner.run)
        assert "business_domain" in source
        assert "find_descendants" in source
        assert "update_node_property" in source


class TestComposePageDomainPassing:
    def test_compose_leaf_passes_business_domain(self):
        """compose_all_pages should pass business_domain to compose_page."""
        import inspect

        from wiki.page_composer_service import WikiPageComposerService

        source = inspect.getsource(WikiPageComposerService.compose_all_pages)
        assert "business_domain" in source
        assert "is_entry_point" in source
