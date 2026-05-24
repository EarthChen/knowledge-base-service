"""Verify citation_verifier is integrated into quality_gate_node."""

import pytest


def test_quality_gate_uses_citation_verifier():
    """quality_gate_node must call verify_citations or reference citation_verifier."""
    with open("wiki/nodes/quality_gate.py") as f:
        source = f.read()
    assert "citation_verifier" in source or "verify_citations" in source, (
        "quality_gate_node must use citation_verifier"
    )


def test_quality_gate_collects_module_names():
    """quality_gate_node must collect module names for entity verification."""
    with open("wiki/nodes/quality_gate.py") as f:
        source = f.read()
    assert "all_module_names" in source or "known_entities" in source or "module_names" in source, (
        "quality_gate_node must collect entity names for citation verification"
    )


_CONTENT_WITH_INVALID_CITATIONS = (
    "## 业务概述\nThis service handles payments and settlement for the platform. "
    "It references `GhostServiceOne`, `GhostServiceTwo`, `GhostServiceThree`, "
    "and `GhostServiceFour` in the narrative.\n\n"
    "## 核心业务流程\n- Validate request\n- Charge customer\n- Record transaction\n\n"
    "## 关联主题\n- [[billing]]\n- [[ledger]]\n"
)


def _make_page(path: str, content: str) -> dict:
    return {
        "path": path,
        "title": path.split("/")[-1],
        "content": content,
        "page_type": "topic",
        "domain": "test",
        "diagrams": [],
        "source_locations": [],
        "metadata": {"domain": "test"},
    }


@pytest.mark.asyncio
async def test_quality_gate_heal_uses_citation_penalized_structural_score():
    """Pages above raw L1 threshold but below penalized score must enter heal."""
    from wiki.nodes.quality_gate import quality_gate_node

    state = {
        "pages": [_make_page("wiki/svc", _CONTENT_WITH_INVALID_CITATIONS)],
        "config": {
            "quality_levels": ["L1"],
            "importance_tiers": {"wiki/svc": "core"},
        },
        "heal_attempts": {},
        "modules": {"repo": [{"properties": {"name": "RealService"}}]},
    }
    result = await quality_gate_node(state)
    scores = result.get("quality_scores", {})
    score = scores["wiki/svc"]

    assert score["citation_invalid_count"] >= 4
    assert score["l1_structural"] < 0.7
    assert "wiki/svc" in result.get("pages_to_heal", [])
