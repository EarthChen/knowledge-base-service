"""Unit tests for wiki Q&A crystallization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore
from wiki.crystallizer import _build_content, title_from_question


@pytest.mark.asyncio
async def test_crystallize_persists_page_and_backlinks() -> None:
    from wiki import crystallizer

    base = MagicMock()
    base.persist_wiki_pages = AsyncMock(return_value=1)
    store = WikiStore(base)
    store.add_wiki_reference_edge = AsyncMock(return_value=MagicMock())

    out = await crystallizer.crystallize(
        store,
        "my-repo",
        "What is X?",
        "X is the answer.",
        ["docs/a.md", "docs/b.md"],
        "default",
    )

    assert out["path"].startswith("crystallized/")
    assert out["path"].endswith(".md")
    assert out["title"] == "What is X?"
    assert out["page_uid"] == f"WikiPage:my-repo:{out['path']}"
    base.persist_wiki_pages.assert_awaited_once()
    _repo, pages = base.persist_wiki_pages.await_args.args
    assert _repo == "my-repo"
    assert len(pages) == 1
    p0 = pages[0]
    assert p0["page_type"] == "crystallized"
    assert p0["source_origin"] == "crystallized"
    assert "docs/a.md" in p0["content"]
    assert store.add_wiki_reference_edge.await_count == 2


def test_title_from_question_truncates() -> None:
    long_q = "word " * 80
    t = title_from_question(long_q, max_len=40)
    assert len(t) <= 42
    assert t.endswith("…") or len(long_q) <= 40


def test_build_content_includes_q_and_sources() -> None:
    body = _build_content("Q1?", "A1", ["p.md", "p.md", "q.md"])
    assert "Q1?" in body
    assert "A1" in body
    assert "p.md" in body
    assert "q.md" in body
