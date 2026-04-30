"""End-to-end integration test: full pipeline with mock LLM."""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_graph import build_wiki_pipeline


def _mock_llm_generate(prompt: str, system: str = "", **kwargs) -> str:
    """Route LLM responses based on prompt content."""
    lower = prompt.lower()

    if "organize them into a hierarchical" in lower:
        return json.dumps({
            "domains": [
                {
                    "name": "payment",
                    "description": "Payment processing",
                    "modules": ["PaymentService", "RefundService"],
                    "children": [],
                },
                {
                    "name": "user-management",
                    "description": "User management",
                    "modules": ["UserService"],
                    "children": [],
                },
            ],
        })

    if "group these" in lower and "sub-groups" in lower:
        return json.dumps([
            {"name": "core-payment", "entities": ["PaymentService", "RefundService"]},
        ])

    if "generate a system overview" in lower:
        return (
            "# System Overview\n\n"
            "## 系统概览\nPayment and user management system.\n\n"
            "## 架构图\n```mermaid\ngraph TD\nPayment-->User\n```\n\n"
            "## 域列表\n- [[payment]]\n- [[user-management]]"
        )

    if "generate a domain overview" in lower or "域概览" in lower:
        return (
            "# Domain Overview\n\n"
            "## 域概览\nThis domain handles core business.\n\n"
            "## 架构关系图\n```mermaid\ngraph TD\nA-->B\n```\n\n"
            "## 子主题\n- PaymentService\n- RefundService"
        )

    if "classify the following modules" in lower:
        return json.dumps({
            "payment": [["test-repo", "PaymentService"], ["test-repo", "RefundService"]],
            "user-management": [["test-repo", "UserService"]],
        })

    if "unify the following per-repository" in lower:
        return json.dumps({
            "payment": {"test-repo": "payment"},
            "user-management": {"test-repo": "user-management"},
        })

    return (
        "# Business Wiki Page\n\n"
        "## 业务概述\nThis service handles business logic.\n\n"
        "## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
        "## 核心服务详情\n### Service\nProcesses requests.\n\n"
        "## 关联主题\n- [[user-management]]"
    )


def _build_test_modules() -> dict[str, list[dict]]:
    """Build realistic test module data with mixed entity types."""
    return {
        "test-repo": [
            {
                "uid": "Module::PaymentService:0",
                "label": "Module",
                "properties": {
                    "name": "PaymentService",
                    "annotations": ["@Service", "@Transactional"],
                    "methods_count": 12,
                    "start_line": 0,
                    "end_line": 350,
                    "business_summary": "Handles payment processing and validation",
                    "methods": ["processPayment", "validateCard", "createOrder"],
                    "calls": ["UserService", "RefundService"],
                    "semantic_roles": ["service"],
                },
            },
            {
                "uid": "Module::RefundService:0",
                "label": "Module",
                "properties": {
                    "name": "RefundService",
                    "annotations": ["@Service"],
                    "methods_count": 8,
                    "start_line": 0,
                    "end_line": 200,
                    "business_summary": "Handles refund processing",
                    "methods": ["processRefund", "calculateRefund"],
                    "calls": ["PaymentService"],
                    "semantic_roles": ["service"],
                },
            },
            {
                "uid": "Module::UserService:0",
                "label": "Module",
                "properties": {
                    "name": "UserService",
                    "annotations": ["@Service"],
                    "methods_count": 15,
                    "start_line": 0,
                    "end_line": 400,
                    "business_summary": "User management and authentication",
                    "methods": ["register", "login", "updateProfile"],
                    "calls": [],
                    "semantic_roles": ["service"],
                },
            },
            {
                "uid": "Module::PaymentDTO:0",
                "label": "Module",
                "properties": {
                    "name": "PaymentDTO",
                    "annotations": ["@Data"],
                    "methods_count": 0,
                    "start_line": 0,
                    "end_line": 20,
                    "fields": ["id", "amount", "currency", "status"],
                },
            },
            {
                "uid": "Module::StatusEnum:0",
                "label": "Module",
                "properties": {
                    "name": "StatusEnum",
                    "annotations": [],
                    "methods_count": 0,
                    "start_line": 0,
                    "end_line": 10,
                    "is_enum": True,
                    "fields": ["PENDING", "SUCCESS", "FAILED"],
                },
            },
            {
                "uid": "Module::BaseController:0",
                "label": "Module",
                "properties": {
                    "name": "BaseController",
                    "annotations": ["@RestController", "@RequestMapping"],
                    "methods_count": 2,
                    "start_line": 0,
                    "end_line": 30,
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_full_pipeline_e2e_with_mock_llm():
    """Exercise the complete pipeline: Phase 1-4 with realistic data."""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=_mock_llm_generate)

    pipeline = build_wiki_pipeline()

    initial_state = {
        "business_id": "test-e2e",
        "repositories": ["test-repo"],
        "config": {},
        "modules": _build_test_modules(),
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

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "e2e-test-1", "llm": mock_llm}},
    )

    assert result is not None
    assert result["business_id"] == "test-e2e"

    # Phase 1: entity classification happened
    assert result.get("entity_roles"), "entity_roles should be populated"
    roles = result["entity_roles"]
    assert roles.get("Module::PaymentService:0") == "has_business_logic"
    assert roles.get("Module::PaymentDTO:0") == "data_model"
    # Outgoing calls → edge_count for dim_graph (PaymentService: 2; BaseController: none).
    assert roles.get("Module::BaseController:0") == "supporting"

    # Resolved wiki links from [[...]] without mutating pages (operator.add safe).
    resolved = result.get("resolved_links") or {}
    sys_path = "wiki/_system_overview"
    assert sys_path in resolved
    targets = {entry["target_path"] for entry in resolved[sys_path]}
    assert "wiki/payment" in targets
    assert "wiki/user-management" in targets

    # Phase 1: detect_reorg should return first_run
    assert result.get("reorg_type") == "first_run"

    # Phase 2: domain classification happened
    assert result.get("domain_mapping"), "domain_mapping should be populated"

    # Phase 2c: domain tree was built
    assert result.get("domain_tree") is not None

    # Phase 2c: review status was marked
    assert result.get("review_status", {}).get("domain_tree") == "pending_review"

    # Phase 3+4: pages were generated
    pages = result.get("pages", [])
    assert len(pages) >= 1, f"Expected generated pages, got {len(pages)}"

    # System overview should exist
    system_pages = [p for p in pages if p.get("page_type") == "system_overview"]
    assert len(system_pages) >= 1, "System overview page should be generated"

    # No errors
    assert len(result.get("errors", [])) == 0


@pytest.mark.asyncio
async def test_pipeline_empty_modules_completes():
    """Pipeline with empty modules should complete without errors."""
    pipeline = build_wiki_pipeline()

    initial_state = {
        "business_id": "empty-test",
        "repositories": [],
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

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "empty-test-1"}},
    )

    assert result is not None
    assert result["reorg_type"] == "first_run"


@pytest.mark.asyncio
async def test_pipeline_incremental_no_change_skips():
    """Incremental run with no affected domains should route to finalize."""
    pipeline = build_wiki_pipeline()

    initial_state = {
        "business_id": "incr-test",
        "repositories": ["repo-1"],
        "config": {},
        "modules": {
            "repo-1": [
                {
                    "uid": "Module::Svc:0",
                    "label": "Module",
                    "properties": {
                        "name": "Svc",
                        "annotations": ["@Service"],
                        "methods_count": 5,
                        "start_line": 0,
                        "end_line": 100,
                    },
                }
            ]
        },
        "domain_mapping": {},
        "domain_tree": [{"name": "svc-domain", "modules": ["Svc"], "children": []}],
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
        "is_incremental": True,
        "reorg_type": "",
        "affected_domains": [],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
    }

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "incr-test-1"}},
    )

    assert result is not None
    assert result["reorg_type"] == "none"
    assert len(result.get("pages", [])) == 0
