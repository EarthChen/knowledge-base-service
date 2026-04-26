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
        assert "用户管理/README.md" in readme or "用户管理/" in readme


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
        assert "No domains" in index or len(index.strip()) > 0


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
