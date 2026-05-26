"""Tests for module summaries loading priority."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLoadExistingModuleSummariesPriority:
    @pytest.mark.asyncio
    async def test_graph_preferred_over_checkpoint(self):
        """When prefer_graph_for_incremental=True and graph has data, graph should be used."""
        from wiki.pipeline_orchestrator import load_existing_module_summaries

        mock_module = MagicMock()
        mock_module.uid = "uid1"
        mock_module.properties = {"name": "TestModule", "business_summary": "Test summary from graph"}
        all_modules = {"repo1": [mock_module]}

        with patch("wiki.pipeline_orchestrator.get_settings") as mock_settings:
            mock_wiki = MagicMock()
            mock_wiki.prefer_graph_for_incremental = True
            mock_settings.return_value.wiki = mock_wiki
            summaries = await load_existing_module_summaries("test-biz", all_modules)

        assert len(summaries) > 0
        found = summaries.get("TestModule") or summaries.get("repo1|TestModule")
        assert found is not None
        assert "graph" in found.get("summary_text", "").lower() or found.get("summary_text") == "Test summary from graph"

    @pytest.mark.asyncio
    async def test_checkpoint_fallback_when_graph_empty(self):
        """When graph has no summaries, checkpoint should be used as fallback."""
        from wiki.pipeline_orchestrator import load_existing_module_summaries

        all_modules = {"repo1": []}

        with (
            patch("wiki.pipeline_orchestrator.get_settings") as mock_settings,
            patch("wiki.pipeline_orchestrator._load_summaries_from_checkpoint", new_callable=AsyncMock) as mock_cp,
        ):
            mock_wiki = MagicMock()
            mock_wiki.prefer_graph_for_incremental = True
            mock_settings.return_value.wiki = mock_wiki
            mock_cp.return_value = {"Module1": {"summary_text": "from checkpoint"}}
            summaries = await load_existing_module_summaries("test-biz", all_modules)

        assert "Module1" in summaries
        assert summaries["Module1"]["summary_text"] == "from checkpoint"
