"""End-to-end integration test: full pipeline with mock LLM."""
from __future__ import annotations

import json
import re

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

    if "## repositories (" in lower:
        # SystemOverviewComposer user prompt (`_build_prompt`) — synthesis node path
        return (
            "## System Purpose\nPayment and user management platform.\n\n"
            "## Microservice Architecture\n```mermaid\ngraph TD\nPayment-->User\n```\n\n"
            "## Business Domains\n- [[payment]]\n- [[user-management]]\n\n"
            "## Key Entry Points\n- Payments API\n"
        )

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

    if "分析以下代码模块" in prompt:
        return json.dumps({
            "summary_text": "E2E module summary.",
            "key_methods": [],
            "dependencies": [],
            "callers": [],
        })

    if "create a domain overview page" in lower and "sub-domain summaries" in lower:
        return json.dumps({
            "title": "Parent Overview",
            "content": "# Parent\n",
            "executive_summary": "E2E parent executive summary.",
            "page_type": "domain_overview",
        })

    return (
        "# Business Wiki Page\n\n"
        "## 业务概述\nThis service handles business logic.\n\n"
        "## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: process\n```\n\n"
        "## 核心服务详情\n### Service\nProcesses requests.\n\n"
        "## 关联主题\n- [[user-management]]"
    )


async def _mock_llm_complete_json(
    messages: list[dict[str, str]],
    schema: dict,
    **kwargs: object,
) -> dict:
    """Mirror ``_mock_llm_generate`` for call sites that use ``complete_json``."""
    prompt = ""
    system = ""
    for m in messages:
        if m.get("role") == "system":
            system = str(m.get("content", ""))
        elif m.get("role") == "user":
            prompt = str(m.get("content", ""))
    raw = _mock_llm_generate(prompt, system, **kwargs)
    text = raw.strip()
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _chat_generation_result(text: str):
    class _Msg:
        __slots__ = ("content",)

        def __init__(self, c: str) -> None:
            self.content = c

    class _Gen:
        __slots__ = ("message",)

        def __init__(self, c: str) -> None:
            self.message = _Msg(c)

    class _Res:
        __slots__ = ("generations",)

        def __init__(self, c: str) -> None:
            self.generations = [[_Gen(c)]]

    return _Res(text)


async def _mock_llm_agenerate(messages, **kwargs):
    """LangGraph v2 nodes call ``agenerate`` for titles and bottom-up composition."""
    prompt = ""
    system = ""
    for conv in messages:
        for m in conv:
            if m.get("role") == "system":
                system = str(m.get("content", ""))
            if m.get("role") == "user":
                prompt = str(m.get("content", ""))
    if "输出JSON" in prompt and ("标题" in prompt or "title" in prompt.lower()):
        uids = re.findall(r"Module::([A-Za-z0-9]+):", prompt)
        name = uids[0] if uids else "Module"
        text = json.dumps({"title": name, "description": f"Description for {name}"})
        return _chat_generation_result(text)
    if "为代码模块「" in prompt:
        m = re.search(r"为代码模块「([^」]+)」", prompt)
        mod = m.group(1) if m else "Module"
        peers = ["RefundService", "UserService", "PaymentService", "BaseController"]
        other = next((p for p in peers if p.lower() != mod.lower()), "RefundService")
        text = (
            f"# {mod}\n\n## 业务概述\nSynthetic page for {mod}.\n\n"
            f"## 关联主题\n- [[{other}]]\n"
        )
        return _chat_generation_result(text)
    if "基于以下子模块文档" in prompt:
        keys = re.findall(r"canonical_key:\s*(\S+)", prompt)
        link = keys[0] if keys else "child"
        text = f"# Parent overview\n\n## 子模块\n- [[{link}]]\n"
        return _chat_generation_result(text)
    raw = _mock_llm_generate(prompt, system)
    if not isinstance(raw, str):
        raw = json.dumps(raw)
    return _chat_generation_result(raw)


def _build_test_modules() -> dict[str, list[dict]]:
    """Build realistic test module data with mixed entity types."""
    return {
        "test-repo": [
            {
                "uid": "Module::PaymentService:0",
                "label": "Module",
                "properties": {
                    "name": "PaymentService",
                    "file_path": "src/main/java/com/example/PaymentService.java",
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
                    "file_path": "src/main/java/com/example/RefundService.java",
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
                    "file_path": "src/main/java/com/example/UserService.java",
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
                    "file_path": "src/main/java/com/example/dto/PaymentDTO.java",
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
                    "file_path": "src/main/java/com/example/enums/StatusEnum.java",
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
                    "file_path": "src/main/java/com/example/web/BaseController.java",
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
    mock_llm.complete_json = AsyncMock(side_effect=_mock_llm_complete_json)
    mock_llm.agenerate = AsyncMock(side_effect=_mock_llm_agenerate)

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
    assert roles.get("Module::BaseController:0") == "entry_point"

    # Resolved wiki links from [[...]] in generated Markdown (v2 graph pipeline pages).
    resolved = result.get("resolved_links") or {}
    if resolved:
        all_targets = {e["target_path"] for v in resolved.values() for e in v}
        assert any(t for t in all_targets), "expected non-empty link targets when links exist"

    # Phase 1: detect_reorg should return first_run (no prior domain_tree in state).
    assert result.get("reorg_type") == "first_run"

    # v2 pipeline: graph decomposition + bottom-up composition (no domain_mapping pass).
    assert result.get("domain_mapping") == {}
    assert result.get("domain_tree") is None
    module_tree = result.get("module_tree") or []
    assert isinstance(module_tree, list) and len(module_tree) >= 1

    # Review gate is still marked for human review of structure.
    assert result.get("review_status", {}).get("domain_tree") == "pending_review"

    # Phase 3+4: pages were generated (bottom-up from module_tree + leaf summaries path).
    pages = result.get("pages", [])
    assert len(pages) >= 1, f"Expected generated pages, got {len(pages)}"

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


@pytest.mark.asyncio
async def test_pipeline_light_reorg():
    """Incremental run with affected domains and small change should route through classify_domains."""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=_mock_llm_generate)
    mock_llm.complete_json = AsyncMock(side_effect=_mock_llm_complete_json)

    pipeline = build_wiki_pipeline()

    initial_state = {
        "business_id": "light-reorg-test",
        "repositories": ["test-repo"],
        "config": {},
        "modules": _build_test_modules(),
        "domain_mapping": {},
        "domain_tree": [
            {
                "name": "payment",
                "modules": ["PaymentService", "RefundService", "UserService"],
                "children": [],
            },
        ],
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
        "affected_domains": ["payment"],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
    }

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "light-reorg-1", "llm": mock_llm}},
    )

    assert result is not None
    # Should detect reorg as light or heavy (depends on ratio calculation)
    assert result.get("reorg_type") in ("light", "heavy")
    # Should still generate pages
    assert len(result.get("pages", [])) >= 1


@pytest.mark.asyncio
async def test_pipeline_full_reorg():
    """Non-incremental run with existing domain_tree should do full reorg."""
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=_mock_llm_generate)
    mock_llm.complete_json = AsyncMock(side_effect=_mock_llm_complete_json)

    pipeline = build_wiki_pipeline()

    initial_state = {
        "business_id": "full-reorg-test",
        "repositories": ["test-repo"],
        "config": {},
        "modules": _build_test_modules(),
        "domain_mapping": {},
        "domain_tree": [
            {"name": "old-domain", "modules": ["OldService"], "children": []},
        ],
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
        config={"configurable": {"thread_id": "full-reorg-1", "llm": mock_llm}},
    )

    assert result is not None
    assert result.get("reorg_type") == "full"
    assert len(result.get("pages", [])) >= 1
