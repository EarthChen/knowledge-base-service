"""Tests for WikiPipelineState field definitions and detect_reorg_node metrics."""

from __future__ import annotations

import typing

import pytest

from wiki.nodes.classify import detect_reorg_node
from wiki.pipeline_state import WikiPipelineState


def test_pipeline_state_accepts_new_optional_fields() -> None:
    """WikiPipelineState TypedDict should include J-0 optional fields."""
    hints = typing.get_type_hints(WikiPipelineState)
    for field in (
        "heal_cycles",
        "existing_domain_mapping",
        "pinned_modules",
        "affected_modules",
        "persistence",
        "existing_summaries",
    ):
        assert field in hints, f"missing field: {field}"

    state: WikiPipelineState = {
        "business_id": "test-biz",
        "repositories": ["repo-a"],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "errors": [],
        "entity_roles": {},
        "role_stats": {},
        "is_incremental": False,
        "reorg_type": "",
        "affected_domains": [],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
        "heal_cycles": {"/wiki/page": 1},
        "existing_domain_mapping": {"old-domain": [("repo-a", "ModuleA")]},
        "pinned_modules": {"mod-a": "domain-a"},
        "affected_modules": {"mod-a", "mod-b"},
        "persistence": object(),
        "existing_summaries": {"mod-a": {"summary_text": "hello"}},
    }
    assert state["heal_cycles"]["/wiki/page"] == 1
    assert state["affected_modules"] == {"mod-a", "mod-b"}


def _domain_tree_with_modules(count: int) -> list[dict]:
    return [{"name": "root", "modules": [f"mod-{i}" for i in range(count)]}]


@pytest.mark.asyncio
async def test_detect_reorg_light_when_few_affected_modules() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(100),
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {f"mod-{i}" for i in range(3)},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "light"


@pytest.mark.asyncio
async def test_detect_reorg_heavy_when_many_affected_modules() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(100),
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {f"mod-{i}" for i in range(50)},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "heavy"


@pytest.mark.asyncio
async def test_detect_reorg_first_run_when_no_domain_tree() -> None:
    state = {
        "domain_tree": None,
        "is_incremental": True,
        "affected_domains": ["payment"],
        "affected_modules": {"mod-0"},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "first_run"


@pytest.mark.asyncio
async def test_detect_reorg_full_when_not_incremental() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(10),
        "is_incremental": False,
        "affected_domains": ["payment"],
        "affected_modules": {"mod-0"},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "full"


@pytest.mark.asyncio
async def test_detect_reorg_none_when_no_affected_domains() -> None:
    state = {
        "domain_tree": _domain_tree_with_modules(10),
        "is_incremental": True,
        "affected_domains": [],
        "affected_modules": set(),
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "none"
