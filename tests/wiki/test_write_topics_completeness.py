from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWriteTopicsEntityUids:
    @pytest.mark.asyncio
    async def test_entity_uids_attached_to_topic_pages(self):
        """_write_topics attaches covered_entity_uids from memory."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.domain_display_name = "Test"
        agent.content_language = "简体中文"
        agent._output_guardrail = None
        agent._term_glossary = {}

        outline = MagicMock()
        outline.should_split = True
        outline.topics = [MagicMock(), MagicMock()]
        agent._topic_outline = outline

        pages = [
            {"title": "Overview", "content": "x" * 3000, "metadata": {}},
            {"title": "Topic A", "content": "y" * 2000, "metadata": {}},
        ]
        agent._write_with_outline = AsyncMock(return_value=pages)

        memory = MagicMock()
        memory.discovered_entity_uids = {"uid1", "uid2"}

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = True
            mock_settings.return_value.wiki.topic_split_quality_check = False
            result = await agent._write_topics(
                outline.topics, "baseline", memory, ["m1", "m2", "m3", "m4", "m5", "m6"]
            )

        assert result is not None
        for page in result:
            assert "covered_entity_uids" in page
            assert set(page["covered_entity_uids"]) == {"uid1", "uid2"}

    @pytest.mark.asyncio
    async def test_no_entity_uids_when_empty(self):
        """No covered_entity_uids when memory has none."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.domain_display_name = "Test"
        agent.content_language = "简体中文"
        agent._output_guardrail = None
        agent._term_glossary = {}

        outline = MagicMock()
        outline.should_split = True
        outline.topics = [MagicMock(), MagicMock()]
        agent._topic_outline = outline

        pages = [{"title": "Overview", "content": "x" * 3000, "metadata": {}}]
        agent._write_with_outline = AsyncMock(return_value=pages)

        memory = MagicMock()
        memory.discovered_entity_uids = set()

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = True
            mock_settings.return_value.wiki.topic_split_quality_check = False
            result = await agent._write_topics(
                outline.topics, "baseline", memory, ["m1", "m2", "m3", "m4", "m5", "m6"]
            )

        assert result is not None
        for page in result:
            assert "covered_entity_uids" not in page


class TestWriteTopicsQualityCheck:
    @pytest.mark.asyncio
    async def test_quality_check_logs_low_coverage(self):
        """Quality check logs warning for low-coverage topic pages."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.domain_display_name = "Test"
        agent.content_language = "简体中文"
        agent._output_guardrail = None
        agent._term_glossary = {}

        outline = MagicMock()
        outline.should_split = True
        outline.topics = [MagicMock(), MagicMock()]
        agent._topic_outline = outline

        pages = [
            {"title": "Topic A", "content": "short content", "metadata": {}},
            {"title": "Topic B", "content": "y" * 3000, "metadata": {}},
        ]
        agent._write_with_outline = AsyncMock(return_value=pages)

        memory = MagicMock()
        memory.discovered_entity_uids = set()

        low_quality = MagicMock()
        low_quality.coverage = 0.1
        low_quality.uncovered_modules = ["m1", "m2"]
        high_quality = MagicMock()
        high_quality.coverage = 0.9
        high_quality.uncovered_modules = []

        with (
            patch("wiki.domain_doc_agent.get_settings") as mock_settings,
            patch(
                "wiki.domain_doc_agent.evaluate_quality",
                side_effect=[low_quality, high_quality],
            ),
            patch("wiki.domain_doc_agent.log") as mock_log,
        ):
            mock_settings.return_value.wiki.enable_topic_pages = True
            mock_settings.return_value.wiki.topic_split_quality_check = True
            mock_settings.return_value.wiki.domain_agent_early_exit_quality = 0.5
            mock_settings.return_value.wiki.language_guardrail_cn_ratio = 0.4
            result = await agent._write_topics(
                outline.topics, "baseline", memory, ["m1", "m2", "m3", "m4", "m5", "m6"]
            )

        assert result is not None
        mock_log.warning.assert_called()
        warning_events = [c[0][0] for c in mock_log.warning.call_args_list]
        assert "topic_page_low_quality" in warning_events


class TestWriteTopicsFallback:
    @pytest.mark.asyncio
    async def test_all_low_quality_falls_back(self):
        """When ALL topic pages have low quality, _write_topics returns None for fallback."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent.domain_name = "test"
        agent.domain_display_name = "Test"
        agent.content_language = "简体中文"
        agent._output_guardrail = None
        agent._term_glossary = {}

        outline = MagicMock()
        outline.should_split = True
        outline.topics = [MagicMock(), MagicMock()]
        agent._topic_outline = outline

        pages = [
            {"title": "Topic A", "content": "short", "metadata": {}},
            {"title": "Topic B", "content": "also short", "metadata": {}},
        ]
        agent._write_with_outline = AsyncMock(return_value=pages)

        mock_quality = MagicMock()
        mock_quality.coverage = 0.1
        mock_quality.uncovered_modules = ["m1"]

        with (
            patch("wiki.domain_doc_agent.get_settings") as mock_settings,
            patch("wiki.domain_doc_agent.evaluate_quality", return_value=mock_quality),
        ):
            mock_settings.return_value.wiki.enable_topic_pages = True
            mock_settings.return_value.wiki.topic_split_quality_check = True
            mock_settings.return_value.wiki.domain_agent_early_exit_quality = 0.5
            mock_settings.return_value.wiki.language_guardrail_cn_ratio = 0.4
            result = await agent._write_topics(
                outline.topics, "baseline", MagicMock(discovered_entity_uids=set()),
                ["m1", "m2", "m3", "m4", "m5", "m6"],
            )

        assert result is None
