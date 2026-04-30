"""Tests for merge_wiki_pages path merging and observability."""

from __future__ import annotations

from unittest.mock import patch

from wiki.pipeline_state import merge_wiki_pages


def test_merge_wiki_pages_warns_when_page_has_no_path() -> None:
    with patch("wiki.pipeline_state.log") as mock_log:
        left = [{"path": "", "title": "orphan-left"}]
        right = [{"path": "/wiki/ok", "title": "ok"}]
        out = merge_wiki_pages(left, right)

    assert len(out) == 1
    assert out[0]["path"] == "/wiki/ok"
    mock_log.warning.assert_any_call(
        "merge_wiki_pages_skip_no_path",
        page_title="orphan-left",
    )
