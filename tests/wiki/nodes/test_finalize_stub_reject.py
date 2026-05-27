"""Tests for hard-rejecting stub topic pages in finalize."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.finalize import finalize_node


def _topic_page(path: str, content: str) -> dict:
    return {
        "title": "Topic",
        "path": path,
        "page_type": "topic",
        "content": content,
    }


class TestFinalizeStubTopicReject:
    @pytest.mark.asyncio
    async def test_stub_topic_excluded_long_topic_published(self) -> None:
        stub_content = "# Stub Topic\n\n" + ("Brief paragraph. " * 20)  # ~363 chars
        long_content = "# Full Topic\n\n" + ("这是一段完整的中文文档内容。" * 120)

        state = {
            "pages": [
                _topic_page("/__domains__/test/stub-topic", stub_content),
                _topic_page("/__domains__/test/full-topic", long_content),
            ]
        }

        mock_settings = MagicMock()
        mock_settings.wiki.topic_min_content_chars = 1000
        mock_settings.wiki.topic_min_publish_chars = 1000
        mock_settings.wiki.overview_min_content_chars = 2000
        mock_settings.wiki.cn_ratio_hard_min = 0.4

        with patch("core.config.get_settings", return_value=mock_settings):
            with patch("wiki.nodes.finalize.log") as mock_log:
                result = await finalize_node(state)

        paths = {p["path"] for p in result.get("pages", [])}
        assert "/__domains__/test/stub-topic" in paths
        stub = next(p for p in result["pages"] if p["path"] == "/__domains__/test/stub-topic")
        assert stub.get("__rejected__") is True
        assert "/__domains__/test/full-topic" in paths
        full = next(p for p in result["pages"] if p["path"] == "/__domains__/test/full-topic")
        assert not full.get("__rejected__")

        warning_calls = [
            c for c in mock_log.warning.call_args_list if c[0][0] == "stub_topic_rejected"
        ]
        assert len(warning_calls) == 1
        assert warning_calls[0][1]["page_path"] == "/__domains__/test/stub-topic"
