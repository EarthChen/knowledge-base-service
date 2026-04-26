# tests/wiki/test_mkdocs_exporter.py
"""Unit tests for MkDocsExporter."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.mkdocs_exporter import MkDocsExporter


class TestGenerateMkDocsYml:
    def test_contains_site_name(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("my-wiki", ["用户管理", "订单处理"])
        assert "site_name:" in yml
        assert "my-wiki" in yml

    def test_contains_nav_section(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("wiki", ["用户管理"])
        assert "nav:" in yml
        assert "用户管理" in yml

    def test_contains_mermaid_plugin(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("wiki", [])
        assert "pymdownx" in yml.lower()

    def test_empty_domains_fallback(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("wiki", [])
        assert "nav:" in yml


class TestMkDocsExportPlan:
    @pytest.mark.asyncio
    async def test_plan_includes_mkdocs_yml(self):
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
                "uid": "wp1", "title": "Page", "path": "/Domain/Page",
                "content": "# Page",
                "page_type": "entity", "repository": "r",
                "importance_tier": "core", "content_hash": "h1",
            },
        ])
        exporter = MkDocsExporter(mock_store)
        plan = await exporter.build_export_plan("test-biz")
        paths = [f.relative_path for f in plan.files]
        assert "mkdocs.yml" in paths

    @pytest.mark.asyncio
    async def test_mkdocs_uses_markdown_mode(self):
        exporter = MkDocsExporter(store=None)
        assert exporter._link_mode == "markdown"

    @pytest.mark.asyncio
    async def test_mkdocs_wraps_files_in_docs_dir(self):
        """MkDocs should prefix content files with docs/."""
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"uid": "s1", "title": "D", "label": "WikiSection", "depth": 1,
                     "sort_order": 0, "path": "", "page_type": ""},
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[
            {
                "uid": "wp1", "title": "A", "path": "/D/A",
                "content": "# A",
                "page_type": "entity", "repository": "r",
                "importance_tier": "core", "content_hash": "h",
            },
        ])
        exporter = MkDocsExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        content_files = [f for f in plan.files if f.relative_path != "mkdocs.yml"]
        for f in content_files:
            assert f.relative_path.startswith("docs/"), f"Expected docs/ prefix: {f.relative_path}"

    @pytest.mark.asyncio
    async def test_mkdocs_content_has_standard_links(self):
        """MkDocs should convert wikilinks to standard markdown links."""
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"uid": "s1", "title": "D", "label": "WikiSection", "depth": 1,
                     "sort_order": 0, "path": "", "page_type": ""},
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[
            {
                "uid": "wp1", "title": "A", "path": "/D/A",
                "content": "See [[/D/B]].",
                "page_type": "entity", "repository": "r",
                "importance_tier": "core", "content_hash": "h",
            },
        ])
        exporter = MkDocsExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        page_a = next(f for f in plan.files if "A.md" in f.relative_path)
        assert "[[" not in page_a.content
        assert "B" in page_a.content
