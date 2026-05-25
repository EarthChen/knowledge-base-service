"""Tests for heal_hints flow from quality_gate to heal node."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.models import (
    DiagramType,
    PageType,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
)
from wiki.pipeline_state import WikiPipelineState


def _make_page(path: str, content: str) -> dict:
    page = WikiPage(
        path=path,
        title=path.split("/")[-1],
        page_type=PageType.CLASS_DETAIL,
        content=content,
        diagrams=[
            WikiDiagram(diagram_type=DiagramType.CLASS_DIAGRAM, content="graph TB; A-->B"),
        ],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )
    return page.to_dict()


GOOD_CONTENT = (
    "## Overview\nThis is a service component.\n\n"
    "## Key components\n- method_a\n- method_b\n\n"
    "## Relationships\n- Depends on X, called by Y\n\n"
    "Detailed explanation of the internal logic and patterns used by this component."
)

BAD_CONTENT = "Short stub."


@pytest.mark.asyncio
async def test_quality_gate_populates_heal_hints_for_flagged_pages() -> None:
    from wiki.nodes.quality_gate import quality_gate_node

    state: WikiPipelineState = {
        "business_id": "biz",
        "repositories": [],
        "config": {"importance_tiers": {"bad_page": "core"}},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [_make_page("bad_page", BAD_CONTENT)],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await quality_gate_node(state)

    assert "bad_page" in result.get("pages_to_heal", [])
    assert "heal_hints" in result
    assert "bad_page" in result["heal_hints"]
    assert len(result["heal_hints"]["bad_page"]) > 0


@pytest.mark.asyncio
async def test_heal_uses_existing_heal_hints_from_quality_gate() -> None:
    from wiki.heal_strategy import HealResult
    from wiki.nodes.heal import _heal_one_page
    from wiki.quality_evaluator import WikiQualityEvaluator

    precomputed_hint = "## WikiQualityBench improvement hints\n- Structure: fix gaps."
    page_dict = {
        "path": "fix_me",
        "content": BAD_CONTENT,
        "domain": "d",
        "title": "Fix Me",
        "page_type": "topic",
    }
    heal_hints = {"fix_me": precomputed_hint}
    heal_attempts: dict[str, int] = {}
    captured_hint: list[str] = []

    mock_chain = AsyncMock()

    async def capture_execute(ctx):
        captured_hint.append(ctx.hint)
        return HealResult(content="# Fixed\nGood content", strategy_name="targeted")

    mock_chain.execute = capture_execute

    with (
        patch("wiki.nodes.heal._make_strategy_chain", lambda: mock_chain),
        patch("wiki.nodes.heal._update_heal_hint") as mock_update,
    ):
        ok = await _heal_one_page(
            page_path="fix_me",
            page_dict=page_dict,
            state={"pages": [page_dict], "domain_tree": []},
            evaluator=WikiQualityEvaluator(),
            llm=MagicMock(),
            heal_hints=heal_hints,
            heal_attempts=heal_attempts,
        )

    assert ok is True
    mock_update.assert_not_called()
    assert captured_hint == [precomputed_hint]
