"""Tests for budget_resolver injection via pipeline configurable."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.aggregate import compose_parent_pages_node
from wiki.pipeline_orchestrator import run_langgraph_pipeline
from wiki.token_budget import TokenBudgetResolver


@pytest.mark.asyncio
async def test_budget_resolver_passed_in_configurable() -> None:
    captured: dict = {}

    async def fake_ainvoke(state, config=None):
        captured["config"] = config
        return {
            "domain_mapping": {},
            "domain_tree": [],
            "pages": [],
            "resolved_links": {},
            "entity_roles": {},
            "errors": [],
        }

    custom = TokenBudgetResolver(base=42_000)
    fake_pipeline = AsyncMock()
    fake_pipeline.ainvoke = fake_ainvoke

    with patch("wiki.pipeline_orchestrator.build_wiki_pipeline", return_value=fake_pipeline):
        await run_langgraph_pipeline(
            business_id="biz-1",
            repositories=["repo-a"],
            all_modules={"repo-a": []},
            llm="fake-llm",
            budget_resolver=custom,
        )

    cfg = captured["config"]["configurable"]
    assert cfg["budget_resolver"] is custom


@pytest.mark.asyncio
async def test_compose_parent_uses_config_budget_resolver() -> None:
    """When budget_resolver is in config, nodes use it instead of a fresh default."""
    custom = MagicMock(spec=TokenBudgetResolver)
    custom.budget.return_value = 12_345
    custom.claim.return_value = 900

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        return_value=json.loads(
            '{"title": "Parent", "content": "Overview.", '
            '"executive_summary": "Summary.", "page_type": "domain_overview"}'
        )
    )

    state = {
        "domain_tree": [
            {
                "name": "parent_domain",
                "modules": [],
                "children": [
                    {"name": "child1", "modules": ["ServiceA"], "children": []},
                    {"name": "child2", "modules": ["ServiceB"], "children": []},
                ],
            },
        ],
        "leaf_summaries": {
            "child1": {"summary_text": "Child 1.", "module_count": 1},
            "child2": {"summary_text": "Child 2.", "module_count": 1},
        },
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": mock_llm, "budget_resolver": custom}}

    await compose_parent_pages_node(state, config)

    custom.budget.assert_called()
    custom.claim.assert_called()
    claim_args = custom.claim.call_args[0]
    assert claim_args[0] == "snippets"


@pytest.mark.asyncio
async def test_snippet_claim_reduces_remaining() -> None:
    """claim('snippets', ...) should deduct from resolver remaining budget."""
    resolver = TokenBudgetResolver(base=30_000)
    initial = resolver.remaining("snippets")

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        return_value=json.loads(
            '{"title": "Parent", "content": "Overview.", '
            '"executive_summary": "Summary.", "page_type": "domain_overview"}'
        )
    )

    state = {
        "domain_tree": [
            {
                "name": "parent_domain",
                "modules": [],
                "children": [
                    {"name": "child1", "modules": ["ServiceA"], "children": []},
                ],
            },
        ],
        "leaf_summaries": {"child1": {"summary_text": "Child.", "module_count": 1}},
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": mock_llm, "budget_resolver": resolver}}

    await compose_parent_pages_node(state, config)

    assert resolver.remaining("snippets") < initial
