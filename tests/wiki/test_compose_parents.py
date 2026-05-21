from __future__ import annotations

from dataclasses import fields

import json

import pytest
from unittest.mock import AsyncMock

from wiki.models import LeafSummary
from wiki.nodes.aggregate import _compute_cross_domain_call_stats
from wiki.pipeline_nodes import compose_parent_pages_node, has_parent_domains
from wiki.prompts import system_wiki_parent_overview


def _leaf_summary_field_names() -> set[str]:
    return {f.name for f in fields(LeafSummary)}


def test_system_wiki_parent_overview_language_param():
    prompt = system_wiki_parent_overview("English")
    assert "English" in prompt
    assert "简体中文" not in prompt

    default = system_wiki_parent_overview()
    assert "简体中文" in default


def test_cross_domain_call_stats_basic():
    parent = {
        "name": "commerce",
        "children": [
            {"name": "payment", "display_name": "Payment", "modules": ["PaySvc", "PayDao"]},
            {"name": "billing", "display_name": "Billing", "modules": ["BillSvc"]},
        ],
    }
    edges = [
        {"source": "PaySvc", "target": "BillSvc", "weight": 5},
        {"source": "BillSvc", "target": "PayDao", "weight": 3},
    ]
    result = _compute_cross_domain_call_stats(parent, edges)
    assert "Payment → Billing: 5" in result
    assert "Billing → Payment: 3" in result


def test_cross_domain_call_stats_from_tuple_edges():
    """Edges converted from graph_domain_decompose tuple format should work."""
    raw_edges = [
        (("repo", "PaySvc"), ("repo", "BillSvc"), 5),
        (("repo", "BillSvc"), ("repo", "PayDao"), 3),
    ]
    converted = [
        {"source": src[1], "target": dst[1], "weight": w}
        for src, dst, w in raw_edges
    ]
    parent = {
        "name": "commerce",
        "children": [
            {"name": "payment", "display_name": "Payment", "modules": ["PaySvc", "PayDao"]},
            {"name": "billing", "display_name": "Billing", "modules": ["BillSvc"]},
        ],
    }
    result = _compute_cross_domain_call_stats(parent, converted)
    assert "Payment → Billing: 5" in result
    assert "Billing → Payment: 3" in result


def test_cross_domain_call_stats_no_edges():
    parent = {"name": "test", "children": []}
    result = _compute_cross_domain_call_stats(parent, None)
    assert "No cross-domain call data" in result


def test_cross_domain_call_stats_same_domain_ignored():
    parent = {
        "name": "test",
        "children": [
            {"name": "sub1", "display_name": "Sub1", "modules": ["A", "B"]},
        ],
    }
    edges = [{"source": "A", "target": "B", "weight": 10}]
    result = _compute_cross_domain_call_stats(parent, edges)
    assert "No cross-sub-domain calls" in result


def test_has_parent_domains_true():
    state = {
        "domain_tree": [
            {"name": "root", "modules": [], "children": [
                {"name": "child1", "modules": ["A"], "children": []},
            ]},
        ],
    }
    assert has_parent_domains(state) is True


def test_has_parent_domains_false_flat():
    state = {
        "domain_tree": [
            {"name": "domain1", "modules": ["A"], "children": []},
            {"name": "domain2", "modules": ["B"], "children": []},
        ],
    }
    assert has_parent_domains(state) is False


def test_has_parent_domains_empty():
    state = {"domain_tree": []}
    assert has_parent_domains(state) is False


def test_has_parent_domains_none():
    state = {"domain_tree": None}
    assert has_parent_domains(state) is False


@pytest.mark.asyncio
async def test_compose_parent_pages_flat_tree():
    state = {
        "domain_tree": [
            {"name": "domain1", "modules": ["A"], "children": []},
        ],
        "leaf_summaries": {"domain1": {"summary_text": "test", "module_count": 1}},
        "modules": {},
        "entity_roles": {},
    }
    result = await compose_parent_pages_node(state)
    assert result.get("pages", []) == []


@pytest.mark.asyncio
async def test_compose_parent_pages_nested(monkeypatch):
    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        return_value=json.loads(
            '{"title": "Parent Overview", "content": "Overview of parent.", '
            '"executive_summary": "Parent handles X and Y.", "page_type": "domain_overview"}'
        )
    )

    state = {
        "domain_tree": [
            {"name": "parent_domain", "modules": [], "children": [
                {"name": "child1", "modules": ["ServiceA"], "children": []},
                {"name": "child2", "modules": ["ServiceB"], "children": []},
            ]},
        ],
        "leaf_summaries": {
            "child1": {
                "domain_name": "child1",
                "summary_text": "Service A handles X.",
                "module_count": 1,
                "key_entities": ["ServiceA"],
                "source": "llm",
            },
            "child2": {
                "domain_name": "child2",
                "summary_text": "Service B handles Y.",
                "module_count": 1,
                "key_entities": ["ServiceB"],
                "source": "llm",
            },
        },
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": mock_llm}}
    result = await compose_parent_pages_node(state, config)
    pages = result.get("pages", [])
    assert len(pages) >= 1
    assert pages[0]["page_type"] == "domain_overview"
    mock_llm.complete_json.assert_awaited_once()
    parent_summary = result.get("leaf_summaries", {}).get("parent_domain", {})
    assert _leaf_summary_field_names() == set(parent_summary.keys())
    assert parent_summary["domain_name"] == "parent_domain"
    assert parent_summary["key_entities"] == ["child1", "child2"]


@pytest.mark.asyncio
async def test_compose_parent_pages_uses_domain_path_convention():
    """Parent overview pages must use /__domains__/{slug}/_overview path."""
    llm = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value={
            "title": "家族核心运营",
            "content": "## 业务概述\n家族系统...\n## 子域架构\n...",
            "executive_summary": "家族核心运营总览",
            "page_type": "domain_overview",
        }
    )
    state = {
        "domain_tree": [
            {
                "name": "family-core-operations",
                "display_name": "家族核心运营",
                "modules": [],
                "children": [
                    {"name": "family-interaction", "modules": ["FamilyService"], "children": []},
                    {"name": "family-task", "modules": ["TaskService"], "children": []},
                ],
            },
        ],
        "leaf_summaries": {
            "family-interaction": {"summary_text": "家族互动", "module_count": 1},
            "family-task": {"summary_text": "家族任务", "module_count": 1},
        },
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": llm}}
    result = await compose_parent_pages_node(state, config)
    pages = result.get("pages", [])
    assert len(pages) == 1
    assert pages[0]["path"] == "/__domains__/family-core-operations/_overview"
    assert pages[0].get("business_domain") == "family-core-operations"
    assert pages[0]["title"] == "家族核心运营"


@pytest.mark.asyncio
async def test_compose_parent_pages_no_llm():
    state = {
        "domain_tree": [{"name": "p", "modules": [], "children": [{"name": "c", "modules": ["A"], "children": []}]}],
        "leaf_summaries": {"c": {"summary_text": "test"}},
        "modules": {},
        "entity_roles": {},
    }
    result = await compose_parent_pages_node(state)
    assert result.get("pages", []) == []
