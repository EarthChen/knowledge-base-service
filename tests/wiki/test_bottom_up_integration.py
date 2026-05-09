"""Integration tests for bottom-up wiki stages: summarize_leaves, compose_parent_pages."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import (
    compose_parent_pages_node,
    has_parent_domains,
    summarize_leaves_node,
)
from wiki.snippet_selector import select_key_snippets


def _base_state() -> dict:
    return {
        "business_id": "bottom-up-test",
        "repositories": ["test-repo"],
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
        "stage_timings": {},
        "llm_call_count": 0,
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
    }


async def test_flat_domain_tree_summarize_and_routes_to_synthesize_overviews():
    """No nested domains: leaf summaries are produced; router skips compose_parent_pages."""
    domain_tree = [
        {"name": "payment", "modules": ["PaymentService"], "children": []},
        {"name": "user-management", "modules": ["UserService"], "children": []},
    ]
    pages = [
        {
            "path": "wiki/payment",
            "title": "Payment",
            "content": "# Payment\n\n## Overview\nProcesses payments.",
            "page_type": "domain_wiki",
            "metadata": {
                "executive_summary": "Handles payment capture and settlement for the platform.",
            },
        },
        {
            "path": "wiki/user-management",
            "title": "Users",
            "content": "# Users\n\n## Summary\nUser accounts.",
            "page_type": "domain_wiki",
            "metadata": {
                "executive_summary": "Manages identity, profiles, and access for end users.",
            },
        },
    ]
    state = {**_base_state(), "domain_tree": domain_tree, "pages": pages}

    out = await summarize_leaves_node(state)
    leaf_summaries = out.get("leaf_summaries") or {}
    assert "payment" in leaf_summaries
    assert "user-management" in leaf_summaries
    assert leaf_summaries["payment"]["summary_text"].startswith("Handles payment")
    assert leaf_summaries["payment"]["source"] == "llm"
    assert leaf_summaries["user-management"]["source"] == "llm"

    merged = {**state, **out}
    assert not has_parent_domains(merged)


async def test_nested_domain_tree_compose_parent_pages_and_executive_summary():
    """Parent domains trigger compose_parent_pages; parent pages include executive_summary metadata."""
    modules = {
        "test-repo": [
            {
                "uid": "Module::PaymentService:0",
                "label": "Module",
                "properties": {
                    "name": "PaymentService",
                    "methods": ["processPayment"],
                    "business_summary": "Payments",
                },
            },
            {
                "uid": "Module::BillingService:0",
                "label": "Module",
                "properties": {
                    "name": "BillingService",
                    "methods": ["sendInvoice"],
                    "business_summary": "Billing",
                },
            },
        ],
    }
    entity_roles = {
        "Module::PaymentService:0": "has_business_logic",
        "Module::BillingService:0": "has_business_logic",
    }
    domain_tree = [
        {
            "name": "commerce",
            "modules": [],
            "children": [
                {
                    "name": "payment",
                    "modules": ["PaymentService"],
                    "children": [],
                },
                {
                    "name": "billing",
                    "modules": ["BillingService"],
                    "children": [],
                },
            ],
        },
    ]
    pages = [
        {
            "path": "wiki/payment",
            "title": "Payment",
            "content": "# Payment\n\nBody.",
            "page_type": "domain_wiki",
            "metadata": {"executive_summary": "Leaf summary for payment."},
        },
        {
            "path": "wiki/billing",
            "title": "Billing",
            "content": "# Billing\n\nBody.",
            "page_type": "domain_wiki",
            "metadata": {"executive_summary": "Leaf summary for billing."},
        },
    ]
    state = {
        **_base_state(),
        "domain_tree": domain_tree,
        "pages": pages,
        "modules": modules,
        "entity_roles": entity_roles,
    }

    sum_out = await summarize_leaves_node(state)
    assert sum_out.get("leaf_summaries", {}).get("payment", {}).get("source") == "llm"

    pre_route = {**state, **sum_out}
    assert has_parent_domains(pre_route)

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(
        return_value={
            "title": "Commerce",
            "content": "# Commerce\n\nSynthesizes payment and billing.",
            "executive_summary": "Unified commerce: payments and billing under one umbrella.",
            "page_type": "domain_overview",
        }
    )
    config = {"configurable": {"llm": mock_llm}}

    comp_out = await compose_parent_pages_node(pre_route, config=config)
    new_pages = comp_out.get("pages") or []
    assert len(new_pages) == 1
    parent = new_pages[0]
    assert parent.get("path") == "wiki/commerce"
    meta = parent.get("metadata") or {}
    assert meta.get("executive_summary"), "parent metadata should carry executive_summary"
    assert "Unified commerce" in str(meta.get("executive_summary"))


async def test_compose_parent_prompt_includes_code_snippets_from_modules():
    """Key code interfaces from select_key_snippets appear in the LLM prompt."""
    modules = {
        "r1": [
            {
                "uid": "Module::ApiSvc:0",
                "label": "Module",
                "properties": {
                    "name": "ApiSvc",
                    "path": "src/ApiSvc.java",
                    "docstring": "Public API boundary",
                    "methods": ["handleRequest", "validateInput"],
                    "business_summary": "API",
                },
            },
        ],
    }
    entity_roles = {"Module::ApiSvc:0": "entry_point"}
    mod_list = modules["r1"]
    snippets = select_key_snippets(mod_list, entity_roles, budget_tokens=2000)
    assert snippets, "expected snippets from modules with methods"

    domain_tree = [
        {
            "name": "platform",
            "modules": [],
            "children": [
                {"name": "api-layer", "modules": ["ApiSvc"], "children": []},
            ],
        },
    ]
    pages = [
        {
            "path": "wiki/api-layer",
            "title": "API",
            "content": "# API\n\n## Overview\nEdge layer.",
            "page_type": "domain_wiki",
            "metadata": {"executive_summary": "Exposes HTTP APIs."},
        },
    ]
    state = {
        **_base_state(),
        "domain_tree": domain_tree,
        "pages": pages,
        "modules": modules,
        "entity_roles": entity_roles,
    }
    sum_out = await summarize_leaves_node(state)
    pre_route = {**state, **sum_out}

    captured: list[str] = []

    async def _complete_json(messages: list, schema: dict, **kwargs: object) -> dict:
        user = next((str(m.get("content", "")) for m in messages if m.get("role") == "user"), "")
        captured.append(user)
        return {
            "title": "Platform",
            "content": "x",
            "executive_summary": "y",
            "page_type": "domain_overview",
        }

    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(side_effect=_complete_json)
    await compose_parent_pages_node(pre_route, config={"configurable": {"llm": mock_llm}})

    assert captured, "LLM should be called for parent composition"
    full_prompt = "\n".join(captured)
    assert "## Key Code Interfaces" in full_prompt
    assert "ApiSvc" in full_prompt
    assert "handleRequest" in full_prompt or "Method: handleRequest" in full_prompt


async def test_summarize_leaves_empty_content_fallback():
    """Empty page content without executive_summary yields empty rule-extracted summary."""
    domain_tree = [{"name": "empty-domain", "modules": [], "children": []}]
    pages = [
        {
            "path": "wiki/empty-domain",
            "title": "Empty",
            "content": "",
            "page_type": "domain_wiki",
            "metadata": {},
        },
    ]
    state = {**_base_state(), "domain_tree": domain_tree, "pages": pages}
    out = await summarize_leaves_node(state)
    entry = (out.get("leaf_summaries") or {}).get("empty-domain") or {}
    assert entry.get("source") == "rule_extracted"
    assert entry.get("summary_text") == ""
