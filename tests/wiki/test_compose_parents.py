from __future__ import annotations

from dataclasses import fields

import pytest
from unittest.mock import AsyncMock

from wiki.models import LeafSummary
from wiki.pipeline_nodes import compose_parent_pages_node, has_parent_domains


def _leaf_summary_field_names() -> set[str]:
    return {f.name for f in fields(LeafSummary)}


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
    mock_llm.generate.return_value = (
        '{"title": "Parent Overview", "content": "Overview of parent.", '
        '"executive_summary": "Parent handles X and Y.", "page_type": "domain_overview"}'
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
    mock_llm.generate.assert_called_once()
    parent_summary = result.get("leaf_summaries", {}).get("parent_domain", {})
    assert _leaf_summary_field_names() == set(parent_summary.keys())
    assert parent_summary["domain_name"] == "parent_domain"
    assert parent_summary["key_entities"] == ["child1", "child2"]


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
