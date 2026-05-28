"""Tests for F5-R: enhanced GraphSemanticCorrector context + JSON Schema."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import get_settings
from wiki.graph_semantic_corrector import GraphSemanticCorrector
from wiki.nodes.graph_domain_decompose import (
    _build_cross_domain_edges_summary,
    _build_package_tree,
)


def _make_corrector_llm(*, return_value: dict | None = None) -> AsyncMock:
    llm = AsyncMock(spec=["complete_json"])
    llm.complete_json = AsyncMock(
        return_value=return_value or {"merges": [], "renames": [], "moves": [], "summary": ""},
    )
    return llm


def _user_prompt(llm: AsyncMock) -> str:
    messages = llm.complete_json.call_args[0][0]
    return next(m["content"] for m in messages if m["role"] == "user")


@pytest.mark.asyncio
async def test_corrector_receives_package_tree_context() -> None:
    llm = _make_corrector_llm()
    corrector = GraphSemanticCorrector(llm)
    package_tree = "  com.example.auth/ (2 modules)\n    - LoginService"

    await corrector.review_global_consistency(
        {"auth": [("r", "LoginService")], "billing": [("r", "InvoiceService")]},
        {"auth": "认证", "billing": "计费"},
        module_paths={"r|LoginService": "com/example/auth/LoginService.java"},
        module_summaries={},
        package_tree_str=package_tree,
    )

    prompt = _user_prompt(llm)
    assert "包层次结构" in prompt
    assert "com.example.auth" in prompt
    assert "LoginService" in prompt


@pytest.mark.asyncio
async def test_corrector_receives_cross_domain_edges() -> None:
    llm = _make_corrector_llm()
    corrector = GraphSemanticCorrector(llm)
    cross_edges = "  TypeConverter(auth) → DataMapper(billing) [12次]"

    await corrector.review_global_consistency(
        {"auth": [("r", "TypeConverter")], "billing": [("r", "DataMapper")]},
        {"auth": "认证", "billing": "计费"},
        module_paths={},
        module_summaries={},
        cross_domain_edges_str=cross_edges,
    )

    prompt = _user_prompt(llm)
    assert "高频跨域调用" in prompt
    assert "TypeConverter(auth)" in prompt
    assert "DataMapper(billing)" in prompt


@pytest.mark.asyncio
async def test_corrector_uses_complete_json() -> None:
    llm = _make_corrector_llm()
    corrector = GraphSemanticCorrector(llm)

    await corrector.review_global_consistency(
        {"auth": [("r", "LoginService")], "billing": [("r", "InvoiceService")]},
        {"auth": "认证", "billing": "计费"},
        module_paths={},
        module_summaries={},
    )

    llm.complete_json.assert_awaited_once()
    assert not hasattr(llm, "generate") or not getattr(llm, "generate", MagicMock()).called
    schema = llm.complete_json.call_args[0][1]
    assert "merges" in schema.get("properties", schema.get("$defs", {})) or "merges" in str(schema)


def test_build_package_tree_output() -> None:
    module_paths = {
        "repo|LoginService": "com/example/auth/LoginService.java",
        "repo|TokenValidator": "com/example/auth/token/TokenValidator.java",
        "repo|InvoiceService": "com/example/billing/InvoiceService.java",
    }
    result = _build_package_tree(module_paths)

    assert "com.example.auth" in result
    assert "LoginService" in result
    assert "com.example.billing" in result
    assert "InvoiceService" in result


def test_build_cross_domain_edges_summary() -> None:
    domain_mapping = {
        "auth": [("r", "LoginService")],
        "billing": [("r", "InvoiceService")],
    }
    edges = [
        (("r", "LoginService"), ("r", "InvoiceService"), 5),
        (("r", "LoginService"), ("r", "InvoiceService"), 3),
        (("r", "LoginService"), ("r", "LoginService"), 99),
    ]
    result = _build_cross_domain_edges_summary(edges, domain_mapping, top_n=5)

    assert "LoginService(auth)" in result
    assert "InvoiceService(billing)" in result
    assert "[8次]" in result
    assert "LoginService(auth) → LoginService(auth)" not in result


def test_infra_keywords_expanded() -> None:
    keywords = get_settings().wiki.infrastructure_slug_keywords
    expected = [
        "conversion",
        "mapping",
        "type-mapping",
        "type-handler",
        "type-conversion",
        "datasource",
        "data-source",
        "serializer",
        "deserializer",
        "mybatis",
    ]
    for kw in expected:
        assert kw in keywords, f"Missing infrastructure keyword: {kw}"
