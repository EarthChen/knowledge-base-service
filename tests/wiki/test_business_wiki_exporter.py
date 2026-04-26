# tests/wiki/test_business_wiki_exporter.py
"""Unit tests for BusinessWikiExporter."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.business_wiki_exporter import (
    BusinessWikiExporter,
    ExportFile,
    ExportPlan,
)


class TestGenerateReadme:
    def test_contains_business_id(self):
        exporter = BusinessWikiExporter(store=None)
        readme = exporter.generate_readme("my-biz", ["用户管理", "订单处理"])
        assert "my-biz" in readme

    def test_contains_domain_names(self):
        exporter = BusinessWikiExporter(store=None)
        readme = exporter.generate_readme("biz", ["用户管理", "订单处理"])
        assert "用户管理" in readme
        assert "订单处理" in readme

    def test_markdown_links(self):
        exporter = BusinessWikiExporter(store=None)
        readme = exporter.generate_readme("biz", ["用户管理"])
        assert "[用户管理](用户管理/README.md)" in readme


class TestGenerateDomainIndex:
    def test_lists_all_domains_with_pages(self):
        exporter = BusinessWikiExporter(store=None)
        domains = {"用户管理": ["UserController.md", "UserService.md"]}
        index = exporter.generate_domain_index(domains)
        assert "用户管理" in index
        assert "UserController.md" in index
        assert "UserService.md" in index

    def test_empty_domains(self):
        exporter = BusinessWikiExporter(store=None)
        index = exporter.generate_domain_index({})
        assert "No domains found." in index

    def test_overview_pages_appear_as_readme(self):
        """Domain index must use README.md for overview pages, not _overview.md."""
        exporter = BusinessWikiExporter(store=None)
        domains = {"用户管理": ["README.md", "UserService.md"]}
        index = exporter.generate_domain_index(domains)
        assert "_overview.md" not in index
        assert "README.md" in index


class TestBuildExportPlan:
    @pytest.mark.asyncio
    async def test_empty_tree_returns_empty_plan(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(data=[])
        )
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("empty-biz")
        assert isinstance(plan, ExportPlan)
        assert plan.business_id == "empty-biz"
        assert len(plan.files) == 0

    @pytest.mark.asyncio
    async def test_plan_with_tree_data(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {
                        "uid": "section:domain:用户管理",
                        "title": "用户管理",
                        "label": "WikiSection",
                        "depth": 1,
                        "sort_order": 0,
                        "path": "",
                        "page_type": "",
                    },
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[
            {
                "uid": "wp1",
                "title": "UserService",
                "path": "/用户管理/UserService",
                "content": "# UserService\nSee [[/订单处理/OrderAPI]].",
                "page_type": "entity",
                "repository": "user-service",
                "importance_tier": "core",
                "content_hash": "abc123",
            }
        ])
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        assert plan.business_id == "biz"
        assert plan.total_pages == 1
        assert len(plan.files) > 0
        page_paths = [f.relative_path for f in plan.files]
        assert "README.md" in page_paths
        has_user_service = any("UserService" in p for p in page_paths)
        assert has_user_service

    @pytest.mark.asyncio
    async def test_overview_page_maps_to_readme(self):
        """_overview pages must be exported as README.md inside their domain dir."""
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"uid": "s1", "title": "用户管理", "label": "WikiSection", "depth": 1,
                     "sort_order": 0, "path": "", "page_type": ""},
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[
            {
                "uid": "wp-ov",
                "title": "用户管理概览",
                "path": "/用户管理/_overview",
                "content": "# Overview",
                "page_type": "domain_overview",
                "repository": "user-svc",
                "importance_tier": "core",
                "content_hash": "ov1",
            },
            {
                "uid": "wp-svc",
                "title": "UserService",
                "path": "/用户管理/UserService",
                "content": "# UserService",
                "page_type": "entity",
                "repository": "user-svc",
                "importance_tier": "standard",
                "content_hash": "svc1",
            },
        ])
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        page_paths = [f.relative_path for f in plan.files if not f.is_index]
        assert "用户管理/README.md" in page_paths
        assert "用户管理/UserService.md" in page_paths

    @pytest.mark.asyncio
    async def test_domain_index_links_match_export_files(self):
        """Domain index links must resolve to actual exported file paths."""
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"uid": "s1", "title": "用户管理", "label": "WikiSection", "depth": 1,
                     "sort_order": 0, "path": "", "page_type": ""},
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[
            {
                "uid": "wp-ov",
                "title": "概览",
                "path": "/用户管理/_overview",
                "content": "# 概览",
                "page_type": "domain_overview",
                "repository": "r1",
                "importance_tier": "core",
                "content_hash": "h1",
            },
        ])
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        domain_index_file = next(
            f for f in plan.files if f.relative_path == "_index/by-domain.md"
        )
        assert "_overview.md" not in domain_index_file.content
        assert "README.md" in domain_index_file.content

    @pytest.mark.asyncio
    async def test_wikilinks_converted_in_plan(self):
        """Wikilinks should be converted to standard markdown links in the plan."""
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"uid": "s1", "title": "Domain", "label": "WikiSection", "depth": 1,
                     "sort_order": 0, "path": "", "page_type": ""},
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[
            {
                "uid": "wp1",
                "title": "PageA",
                "path": "/Domain/PageA",
                "content": "See [[/Domain/PageB]].",
                "page_type": "entity",
                "repository": "r",
                "importance_tier": "core",
                "content_hash": "h",
            },
        ])
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        page_a = next(
            f for f in plan.files if f.relative_path == "Domain/PageA.md"
        )
        assert "[[" not in page_a.content
        assert "PageB" in page_a.content

    @pytest.mark.asyncio
    async def test_invalid_min_tier_raises(self):
        """Unknown min_tier values must raise ValueError."""
        mock_store = AsyncMock()
        exporter = BusinessWikiExporter(mock_store)
        with pytest.raises(ValueError, match="Invalid min_tier"):
            await exporter.build_export_plan("biz", min_tier="ultra")

    @pytest.mark.asyncio
    async def test_min_tier_passed_to_store(self):
        """min_tier should be forwarded to store.get_wiki_pages_for_business."""
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"uid": "s1", "title": "D", "label": "WikiSection", "depth": 1,
                     "sort_order": 0, "path": "", "page_type": ""},
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
        exporter = BusinessWikiExporter(mock_store)
        await exporter.build_export_plan("biz", min_tier="core")
        mock_store.get_wiki_pages_for_business.assert_called_once_with(
            "biz", min_tier="core"
        )


class TestExportFile:
    def test_dataclass_fields(self):
        f = ExportFile(relative_path="domain/page.md", content="# Title")
        assert f.relative_path == "domain/page.md"
        assert f.content == "# Title"


class TestExportToDirectory:
    @pytest.mark.asyncio
    async def test_writes_files(self, tmp_path):
        plan = ExportPlan(business_id="test")
        plan.files = [
            ExportFile(relative_path="README.md", content="# Test"),
            ExportFile(relative_path="domain/page.md", content="# Page"),
        ]
        exporter = BusinessWikiExporter(store=None)
        created = await exporter.export_to_directory(plan, str(tmp_path))
        assert len(created) == 2
        readme = tmp_path / "README.md"
        assert readme.exists()
        assert readme.read_text() == "# Test"
        page = tmp_path / "domain" / "page.md"
        assert page.exists()

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tmp_path):
        """Paths with '..' that escape output_dir must be rejected."""
        plan = ExportPlan(business_id="test")
        plan.files = [
            ExportFile(relative_path="../escape.md", content="# Escape"),
        ]
        exporter = BusinessWikiExporter(store=None)
        with pytest.raises(ValueError, match="Path traversal"):
            await exporter.export_to_directory(plan, str(tmp_path))
