# tests/wiki/test_obsidian_exporter.py
"""Unit tests for ObsidianExporter."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.obsidian_exporter import ObsidianExporter


class TestGenerateObsidianConfig:
    def test_app_json_content(self):
        exporter = ObsidianExporter(store=None)
        config = exporter.generate_app_config()
        parsed = json.loads(config)
        assert "useMarkdownLinks" in parsed
        assert parsed["useMarkdownLinks"] is False

    def test_graph_json_content(self):
        exporter = ObsidianExporter(store=None)
        config = exporter.generate_graph_config()
        parsed = json.loads(config)
        assert isinstance(parsed, dict)
        assert "collapse-filter" in parsed


class TestObsidianExportPlan:
    @pytest.mark.asyncio
    async def test_plan_includes_obsidian_config(self):
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
                "content": "# Page\nSee [[/Domain/Other]].",
                "page_type": "entity", "repository": "r",
                "importance_tier": "core", "content_hash": "h1",
            },
        ])
        exporter = ObsidianExporter(mock_store)
        plan = await exporter.build_export_plan("test-biz")
        paths = [f.relative_path for f in plan.files]
        assert ".obsidian/app.json" in paths
        assert ".obsidian/graph.json" in paths

    @pytest.mark.asyncio
    async def test_obsidian_uses_wikilink_mode(self):
        exporter = ObsidianExporter(store=None)
        assert exporter._link_mode == "obsidian"

    @pytest.mark.asyncio
    async def test_obsidian_content_preserves_wikilinks(self):
        """Obsidian mode should keep [[wikilinks]] but strip leading /."""
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
        exporter = ObsidianExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        page_a = next(f for f in plan.files if f.relative_path == "D/A.md")
        assert "[[D/B]]" in page_a.content
        assert "[[/" not in page_a.content

    @pytest.mark.asyncio
    async def test_empty_tree_still_has_obsidian_config(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(return_value=MagicMock(data=[]))
        exporter = ObsidianExporter(mock_store)
        plan = await exporter.build_export_plan("empty-biz")
        paths = [f.relative_path for f in plan.files]
        assert ".obsidian/app.json" in paths
