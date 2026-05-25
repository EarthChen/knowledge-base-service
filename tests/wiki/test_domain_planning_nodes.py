# tests/wiki/test_domain_planning_nodes.py
from __future__ import annotations

import pytest

from wiki.pipeline_nodes import set_review_status_node


@pytest.mark.asyncio
async def test_set_review_status_marks_domain_tree_pending_review():
    state = {
        "domain_tree": [{"name": "payment", "children": []}],
        "review_status": {},
    }
    result = await set_review_status_node(state)
    assert "review_status" in result
    assert result["review_status"].get("domain_tree") == "pending_review"
