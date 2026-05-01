from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import synthesize_overviews_node


@pytest.mark.asyncio
async def test_synthesize_overviews_uses_leaf_summaries():
    """When leaf_summaries exist, prompts should use summary_text instead of raw page truncation."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "# System Overview\n\nThis is the overview."

    state = {
        "domain_tree": [
            {"name": "payment", "modules": ["PaymentService"], "children": []},
            {"name": "user-mgmt", "modules": ["UserService"], "children": []},
        ],
        "pages": [
            {
                "path": "wiki/payment",
                "domain": "payment",
                "content": "X" * 500,
                "page_type": "topic",
            },
            {
                "path": "wiki/user-mgmt",
                "domain": "user-mgmt",
                "content": "Y" * 500,
                "page_type": "topic",
            },
        ],
        "leaf_summaries": {
            "payment": {
                "summary_text": "Handles payment processing and billing.",
                "source": "llm",
            },
            "user-mgmt": {
                "summary_text": "Manages user accounts and authentication.",
                "source": "llm",
            },
        },
        "modules": {},
    }
    config = {"configurable": {"llm": mock_llm}}

    await synthesize_overviews_node(state, config)

    call_args = mock_llm.generate.call_args
    assert call_args is not None
    prompt_text = (
        call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    )
    assert "Handles payment processing" in prompt_text or "payment processing" in str(
        call_args
    )
    assert "XXXXX" not in prompt_text


@pytest.mark.asyncio
async def test_synthesize_overviews_fallback_without_leaf_summaries():
    """When leaf_summaries is empty/missing, behavior still produces overview pages."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "# System Overview\n\nFallback overview."

    state = {
        "domain_tree": [
            {"name": "svc", "modules": ["Svc"], "children": []},
        ],
        "pages": [
            {
                "path": "wiki/svc",
                "domain": "svc",
                "content": "Service does things.",
                "page_type": "topic",
            },
        ],
        "modules": {},
    }
    config = {"configurable": {"llm": mock_llm}}

    result = await synthesize_overviews_node(state, config)
    assert result.get("pages")


@pytest.mark.asyncio
async def test_synthesize_overviews_handles_page_without_content_key():
    """Pages missing 'content' key should not cause KeyError."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "# System Overview\n\nOverview."

    state = {
        "domain_tree": [
            {"name": "broken", "modules": ["BrokenSvc"], "children": []},
        ],
        "pages": [
            {
                "path": "wiki/broken",
                "domain": "broken",
                "page_type": "topic",
            },
        ],
        "modules": {},
    }
    config = {"configurable": {"llm": mock_llm}}

    result = await synthesize_overviews_node(state, config)
    assert result.get("pages") is not None
