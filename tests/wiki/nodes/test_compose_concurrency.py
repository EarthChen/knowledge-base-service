"""Tests for compose.py PipelineConcurrency integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_compose_leaf_modules_uses_pipeline_concurrency(monkeypatch):
    """compose_leaf_modules_node should acquire concurrency via PipelineConcurrency."""
    from wiki.nodes.compose import compose_leaf_modules_node

    calls: list[str] = []

    def _fake_semaphore(stage: str) -> asyncio.Semaphore:
        calls.append(stage)
        return asyncio.Semaphore(1)

    monkeypatch.setattr(
        "wiki.nodes.compose.PipelineConcurrency.semaphore",
        staticmethod(_fake_semaphore),
    )

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"summary_text": "test summary"}')
    mock_graph = MagicMock()

    state = {
        "modules": {
            "repo1": [
                {"uid": "mod1", "name": "UserController", "properties": {"name": "UserController"}},
            ],
        },
        "entity_roles": {},
    }
    config = {"configurable": {"llm": mock_llm, "graph_store": mock_graph}}

    await compose_leaf_modules_node(state, config)

    assert calls == ["module_compose"]
