"""Verify parallel parent page composition matches expected structure."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from wiki.nodes.aggregate import compose_parent_pages_node


@pytest.mark.asyncio
async def test_parallel_parent_pages_same_structure_as_serial():
    """Two same-level parents produce two overview pages with correct metadata."""
    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        side_effect=[
            json.loads(
                '{"title": "Parent A Overview", "content": "Overview A.", '
                '"executive_summary": "Parent A summary.", "page_type": "domain_overview"}'
            ),
            json.loads(
                '{"title": "Parent B Overview", "content": "Overview B.", '
                '"executive_summary": "Parent B summary.", "page_type": "domain_overview"}'
            ),
        ]
    )

    state = {
        "domain_tree": [
            {
                "name": "parent_a",
                "modules": [],
                "children": [
                    {"name": "child_a1", "modules": ["SvcA1"], "children": []},
                ],
            },
            {
                "name": "parent_b",
                "modules": [],
                "children": [
                    {"name": "child_b1", "modules": ["SvcB1"], "children": []},
                ],
            },
        ],
        "leaf_summaries": {
            "child_a1": {"summary_text": "Child A1 handles alpha.", "module_count": 1},
            "child_b1": {"summary_text": "Child B1 handles beta.", "module_count": 1},
        },
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": mock_llm}}

    with patch("wiki.nodes.aggregate.PipelineConcurrency.semaphore") as mock_sem:
        mock_sem.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_sem.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await compose_parent_pages_node(state, config)

    pages = result.get("pages", [])
    assert len(pages) == 2
    paths = {p["path"] for p in pages}
    assert "/__domains__/parent-a/_overview" in paths
    assert "/__domains__/parent-b/_overview" in paths
    for page in pages:
        assert page["page_type"] == "domain_overview"
        assert page.get("metadata", {}).get("executive_summary")

    leaf_summaries = result.get("leaf_summaries", {})
    assert "parent_a" in leaf_summaries
    assert "parent_b" in leaf_summaries
    assert leaf_summaries["parent_a"]["summary_text"] == "Parent A summary."
    assert leaf_summaries["parent_b"]["summary_text"] == "Parent B summary."
    assert mock_llm.complete_json.await_count == 2
