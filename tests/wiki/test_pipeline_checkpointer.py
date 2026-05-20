"""Verify LangGraph checkpointer with SQLite persistence."""

from __future__ import annotations

import os

import pytest


@pytest.mark.asyncio
async def test_get_checkpointer_creates_sqlite_db(tmp_path):
    """get_checkpointer should create a SQLite DB file for the business."""
    from wiki.pipeline_graph import get_checkpointer

    checkpoint_dir = str(tmp_path / "checkpoints")
    async with get_checkpointer("test-biz", checkpoint_dir=checkpoint_dir) as cp:
        assert cp is not None
    db_path = os.path.join(checkpoint_dir, "test-biz_wiki.db")
    assert os.path.exists(db_path)


@pytest.mark.asyncio
async def test_get_checkpointer_default_dir(tmp_path, monkeypatch):
    """get_checkpointer uses WIKI_CHECKPOINT_DIR when checkpoint_dir is omitted."""
    from wiki.pipeline_graph import get_checkpointer

    default_dir = str(tmp_path / "default_checkpoints")
    monkeypatch.setenv("WIKI_CHECKPOINT_DIR", default_dir)

    async with get_checkpointer("biz-2") as cp:
        assert cp is not None
    db_path = os.path.join(default_dir, "biz-2_wiki.db")
    assert os.path.exists(db_path)


@pytest.mark.asyncio
async def test_build_wiki_pipeline_with_checkpointer(tmp_path):
    """build_wiki_pipeline accepts a checkpointer argument."""
    from wiki.pipeline_graph import build_wiki_pipeline, get_checkpointer

    async with get_checkpointer("test", checkpoint_dir=str(tmp_path)) as cp:
        pipeline = build_wiki_pipeline(checkpointer=cp)
        assert pipeline is not None
