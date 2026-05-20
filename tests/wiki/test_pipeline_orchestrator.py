"""Tests for pipeline_orchestrator: GraphNode⇔dict conversion, domain tree
conversion, and end-to-end run_langgraph_pipeline with mock LLM."""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock

from store.schema import GraphNode, NodeLabel
from wiki.dependency_graph import DomainNode
from wiki.models import PageType, WikiPage
from wiki.pipeline_orchestrator import (
    PipelineResult,
    _dicts_to_domain_tree,
    _extract_domain_mapping,
    _graph_nodes_to_dicts,
    _pages_from_state,
    run_langgraph_pipeline,
)


def _make_graph_node(name: str, uid: str, **extra_props) -> GraphNode:
    props: dict = {"name": name, "annotations": ["@Service"], "methods_count": 5, "start_line": 0, "end_line": 100}
    props.update(extra_props)
    return GraphNode(label=NodeLabel.MODULE, properties=props, uid=uid)


# ── Unit: _graph_nodes_to_dicts ──────────────────────────────────────────────

class TestGraphNodesToDicts:
    def test_converts_single_repo(self):
        node = _make_graph_node("Foo", "Module::Foo:0")
        result = _graph_nodes_to_dicts({"repo-a": [node]})
        assert "repo-a" in result
        assert len(result["repo-a"]) == 1
        d = result["repo-a"][0]
        assert d["uid"] == "Module::Foo:0"
        assert d["label"] == "Module"
        assert d["properties"]["name"] == "Foo"

    def test_multiple_repos(self):
        a = _make_graph_node("A", "Module::A:0")
        b = _make_graph_node("B", "Module::B:0")
        result = _graph_nodes_to_dicts({"r1": [a], "r2": [b]})
        assert len(result) == 2

    def test_empty_modules(self):
        assert _graph_nodes_to_dicts({}) == {}


# ── Unit: _dicts_to_domain_tree ──────────────────────────────────────────────

class TestDictsToDomainTree:
    def test_flat_tree(self):
        raw = [{"name": "payment", "description": "desc", "modules": ["Svc1"], "children": []}]
        tree = _dicts_to_domain_tree(raw)
        assert tree is not None
        assert len(tree) == 1
        assert isinstance(tree[0], DomainNode)
        assert tree[0].name == "payment"
        assert tree[0].modules == ["Svc1"]

    def test_nested_tree(self):
        raw = [
            {
                "name": "root",
                "description": "",
                "modules": [],
                "children": [
                    {"name": "child", "description": "c", "modules": ["X"], "children": []},
                ],
            }
        ]
        tree = _dicts_to_domain_tree(raw)
        assert tree is not None
        assert len(tree[0].children) == 1
        assert tree[0].children[0].name == "child"

    def test_none_returns_none(self):
        assert _dicts_to_domain_tree(None) is None

    def test_empty_returns_none(self):
        assert _dicts_to_domain_tree([]) is None


# ── Unit: _extract_domain_mapping ────────────────────────────────────────────

class TestExtractDomainMapping:
    def test_uses_raw_mapping_if_present(self):
        state = {"domain_mapping": {"pay": [("repo", "Svc")]}}
        result = _extract_domain_mapping(state, {})
        assert result == {"pay": [("repo", "Svc")]}

    def test_falls_back_to_domain_tree(self):
        modules_dict = {"repo-a": [{"uid": "u1", "label": "Module", "properties": {"name": "Svc"}}]}
        state = {
            "domain_mapping": {},
            "domain_tree": [{"name": "pay", "modules": ["Svc"], "children": []}],
        }
        result = _extract_domain_mapping(state, modules_dict)
        assert "pay" in result
        assert ("repo-a", "Svc") in result["pay"]

    def test_empty_state(self):
        assert _extract_domain_mapping({"domain_mapping": {}}, {}) == {}


# ── Unit: _pages_from_state ──────────────────────────────────────────────────

class TestPagesFromState:
    def test_converts_valid_pages(self):
        page_dict = {
            "path": "wiki/payment",
            "title": "Payment",
            "page_type": "topic",
            "content": "# Payment",
            "diagrams": [],
            "source_locations": [],
            "metadata": {"node_count": 0, "edge_count": 0},
        }
        pages = _pages_from_state({"pages": [page_dict]})
        assert len(pages) == 1
        assert isinstance(pages[0], WikiPage)
        assert pages[0].page_type == PageType.TOPIC

    def test_skips_invalid_pages(self):
        state: dict = {"pages": [{"bad": "data"}], "errors": []}
        pages = _pages_from_state(state)
        assert len(pages) == 0
        assert len(state["errors"]) == 1
        assert state["errors"][0].startswith("page_conversion_failed:")


# ── Integration: run_langgraph_pipeline ──────────────────────────────────────

def _mock_llm_generate(prompt: str, system: str = "", **kwargs) -> str:
    lower = prompt.lower()

    if "organize them into a hierarchical" in lower:
        return json.dumps({
            "domains": [
                {"name": "payment", "description": "Payment processing", "modules": ["PaymentService"], "children": []},
            ],
        })

    if "group these" in lower and "sub-groups" in lower:
        return json.dumps([{"name": "core-payment", "entities": ["PaymentService"]}])

    if "generate a system overview" in lower:
        return (
            "# System Overview\n\n"
            "## 系统概览\nPayment system.\n\n"
            "## 架构图\n```mermaid\ngraph TD\nPayment\n```\n\n"
            "## 域列表\n- [[payment]]"
        )

    if "generate a domain overview" in lower or "域概览" in lower:
        return "# Domain Overview\n## 域概览\nPayment domain."

    if "classify the following modules" in lower:
        return json.dumps({"payment": [["test-repo", "PaymentService"]]})

    if "unify the following per-repository" in lower:
        return json.dumps({"payment": {"test-repo": "payment"}})

    return (
        "# Payment Topic\n\n"
        "## 业务概述\nPayment processing.\n\n"
        "## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: pay\n```\n\n"
        "## 核心服务详情\n### PaymentService\nHandles payments.\n\n"
        "## 关联主题\n- [[user-management]]"
    )


@pytest.mark.asyncio
async def test_run_langgraph_pipeline_returns_pipeline_result():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=_mock_llm_generate)

    all_modules = {
        "test-repo": [
            _make_graph_node(
                "PaymentService",
                "Module::PaymentService:0",
                business_summary="Handles payment processing",
                methods=["processPayment"],
                calls=["UserService"],
                semantic_roles=["service"],
            ),
        ],
    }

    result = await run_langgraph_pipeline(
        business_id="test-orch",
        repositories=["test-repo"],
        all_modules=all_modules,
        llm=mock_llm,
    )

    assert isinstance(result, PipelineResult)
    assert isinstance(result.domain_mapping, dict)
    assert isinstance(result.pages, list)
    assert isinstance(result.entity_roles, dict)
    assert result.domain_tree is None or isinstance(result.domain_tree, list)


@pytest.mark.asyncio
async def test_run_langgraph_pipeline_entity_classification():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=_mock_llm_generate)

    all_modules = {
        "test-repo": [
            _make_graph_node(
                "PaymentService",
                "Module::PaymentService:0",
                business_summary="Handles payment",
                methods=["pay"],
                calls=[],
                semantic_roles=["service"],
            ),
            _make_graph_node(
                "PaymentDTO",
                "Module::PaymentDTO:0",
                annotations=["@Data"],
                methods_count=0,
                fields=["id", "amount"],
            ),
        ],
    }

    result = await run_langgraph_pipeline(
        business_id="test-roles",
        repositories=["test-repo"],
        all_modules=all_modules,
        llm=mock_llm,
    )

    assert result.entity_roles.get("Module::PaymentService:0") == "has_business_logic"
    assert result.entity_roles.get("Module::PaymentDTO:0") == "data_model"


@pytest.mark.asyncio
async def test_run_langgraph_pipeline_incremental_no_change():
    """Incremental run with no affected domains should produce no pages."""
    all_modules = {
        "repo-1": [_make_graph_node("Svc", "Module::Svc:0")],
    }

    result = await run_langgraph_pipeline(
        business_id="incr-test",
        repositories=["repo-1"],
        all_modules=all_modules,
        llm=None,
        existing_domain_tree=[DomainNode(name="svc-domain", modules=["Svc"], children=[])],
        is_incremental=True,
        affected_domains=[],
    )

    assert isinstance(result, PipelineResult)
    assert len(result.pages) == 0
