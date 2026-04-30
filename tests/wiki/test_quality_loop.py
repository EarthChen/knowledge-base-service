"""Tests for LangGraph quality loop — quality_gate_node + heal_pages_node."""

from __future__ import annotations

import pytest

from wiki.models import (
    DiagramType,
    ImportanceTier,
    PageType,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiPageQualityScore,
)
from wiki.pipeline_state import WikiPipelineState


def _make_page(path: str, content: str, diagrams: int = 0) -> dict:
    page = WikiPage(
        path=path,
        title=path.split("/")[-1],
        page_type=PageType.CLASS_DETAIL,
        content=content,
        diagrams=[
            WikiDiagram(diagram_type=DiagramType.CLASS_DIAGRAM, content="graph TB; A-->B")
            for _ in range(diagrams)
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
async def test_quality_gate_identifies_low_quality_pages() -> None:
    from wiki.pipeline_graph import quality_gate_node

    state: WikiPipelineState = {
        "business_id": "biz",
        "repositories": [],
        "config": {"importance_tiers": {"good_page": "core", "bad_page": "core"}},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [
            _make_page("good_page", GOOD_CONTENT, diagrams=1),
            _make_page("bad_page", BAD_CONTENT),
        ],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await quality_gate_node(state)

    assert "quality_scores" in result
    assert "pages_to_heal" in result
    assert result["quality_scores"]["good_page"] > result["quality_scores"]["bad_page"]
    assert "bad_page" in result["pages_to_heal"]


@pytest.mark.asyncio
async def test_quality_gate_skips_skeleton_pages() -> None:
    from wiki.pipeline_graph import quality_gate_node

    state: WikiPipelineState = {
        "business_id": "biz",
        "repositories": [],
        "config": {"importance_tiers": {"skel_page": "skeleton"}},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [_make_page("skel_page", BAD_CONTENT)],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await quality_gate_node(state)
    assert result["quality_scores"]["skel_page"] == 1.0
    assert "skel_page" not in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_quality_gate_respects_max_retries() -> None:
    from wiki.pipeline_graph import quality_gate_node

    state: WikiPipelineState = {
        "business_id": "biz",
        "repositories": [],
        "config": {"importance_tiers": {"bad_page": "standard"}},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [_make_page("bad_page", BAD_CONTENT)],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {"bad_page": 2},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await quality_gate_node(state)
    assert "bad_page" not in result.get("pages_to_heal", [])


@pytest.mark.asyncio
async def test_heal_pages_increments_attempts() -> None:
    from wiki.pipeline_graph import heal_pages_node

    page_dict = _make_page("fix_me", BAD_CONTENT)
    state: WikiPipelineState = {
        "business_id": "biz",
        "repositories": [],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [page_dict],
        "quality_scores": {"fix_me": 0.3},
        "pages_to_heal": ["fix_me"],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await heal_pages_node(state)
    assert result["heal_attempts"]["fix_me"] == 1
    assert result["pages_to_heal"] == []
    assert "fix_me" in result.get("heal_hints", {})


@pytest.mark.asyncio
async def test_quality_gate_handles_topic_page_dict() -> None:
    """quality_gate should evaluate pages produced by compose_pages_node (no metadata)."""
    from wiki.pipeline_graph import quality_gate_node

    topic_page = {
        "path": "wiki/payment",
        "title": "Payment Service",
        "content": (
            "## 业务概述\nPayment handling.\n\n"
            "## 核心业务流程\nSequence of calls.\n\n"
            "## 核心服务详情\n### PaymentService\nProcesses payments.\n\n"
            "## 关联主题\n- [[messaging]]"
        ),
        "page_type": "topic",
        "domain": "payment",
    }
    state: WikiPipelineState = {
        "business_id": "biz",
        "repositories": [],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [topic_page],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await quality_gate_node(state)
    assert "wiki/payment" in result["quality_scores"]
