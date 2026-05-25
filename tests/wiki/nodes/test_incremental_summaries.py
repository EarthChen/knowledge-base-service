"""Tests that incremental mode only summarizes affected modules."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_LONG = "A detailed module summary. " * 5  # >= 100 chars to skip round 2


@pytest.mark.asyncio
async def test_incremental_mode_filters_target_modules():
    """In incremental mode, only affected modules should be summarized."""
    from wiki.nodes.compose import compose_leaf_modules_node

    state = {
        "modules": {
            "repo_a": [
                {"properties": {"name": "UserService", "repository": "repo_a", "path": "a/user.py"}, "labels": ["Module"]},
                {"properties": {"name": "OrderService", "repository": "repo_a", "path": "a/order.py"}, "labels": ["Module"]},
                {"properties": {"name": "PaymentService", "repository": "repo_a", "path": "a/pay.py"}, "labels": ["Module"]},
            ],
        },
        "entity_roles": {},
        "is_incremental": True,
        "affected_modules": {"UserService"},
        "module_summaries": {
            "OrderService": {"summary_text": _LONG + " Handles orders", "key_methods": ["create_order"]},
            "PaymentService": {"summary_text": _LONG + " Processes payments", "key_methods": ["charge"]},
        },
    }

    call_count = 0

    async def mock_gen(name, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return (name, {"summary_text": _LONG + f" Summary of {name}", "key_methods": []})

    configurable = {"llm": AsyncMock(), "graph_store": None}

    with patch("wiki.nodes.compose._generate_single_module_summary", side_effect=mock_gen):
        with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            result = await compose_leaf_modules_node(state, {"configurable": configurable})

    summaries = result.get("module_summaries", {})
    # Only UserService should have been LLM-summarized (1 call)
    assert call_count == 1
    # But all 3 modules should be in the result (2 from existing + 1 newly generated)
    assert len(summaries) >= 3


@pytest.mark.asyncio
async def test_non_incremental_mode_summarizes_all():
    """Without incremental mode, all modules are summarized."""
    from wiki.nodes.compose import compose_leaf_modules_node

    state = {
        "modules": {
            "repo_a": [
                {"properties": {"name": "UserService", "repository": "repo_a", "path": "a/user.py"}, "labels": ["Module"]},
                {"properties": {"name": "OrderService", "repository": "repo_a", "path": "a/order.py"}, "labels": ["Module"]},
            ],
        },
        "entity_roles": {},
    }

    call_count = 0

    async def mock_gen(name, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return (name, {"summary_text": _LONG + f" Summary of {name}", "key_methods": []})

    configurable = {"llm": AsyncMock(), "graph_store": None}

    with patch("wiki.nodes.compose._generate_single_module_summary", side_effect=mock_gen):
        with patch("wiki.nodes.compose.PipelineConcurrency") as mock_pc:
            mock_pc.semaphore.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
            await compose_leaf_modules_node(state, {"configurable": configurable})

    # Both modules should be summarized
    assert call_count == 2
