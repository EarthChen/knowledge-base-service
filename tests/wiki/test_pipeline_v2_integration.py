"""Integration tests for the v2 pipeline (graph-decompose → compose_bottomup)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

_RICH_MARKDOWN = """# Test Module

## 概述

This is a generated integration-test wiki page with enough text to satisfy structural length checks,
and it describes the module responsibilities in plain language for reviewers.

## 核心业务流程

The main flow covers authentication, validation, and persistence steps with clear ordering.

```mermaid
flowchart TD
  A[Start] --> B[Process]
  B --> C[End]
```

## 关联主题

See also related modules in the same repository.
"""


def _extract_user_text_from_agenerate_messages(messages: object) -> str:
    if not messages:
        return ""
    chunk = messages[0] if isinstance(messages, list) else messages
    if isinstance(chunk, list):
        parts: list[str] = []
        for m in chunk:
            if isinstance(m, dict) and m.get("role") == "user":
                parts.append(str(m.get("content", "")))
        return "\n".join(parts)
    return str(chunk)


def _make_mock_llm():
    """Create a mock LLM that returns reasonable, quality-gate-friendly responses."""

    async def _generate(prompt="", system="", **kwargs):
        _ = system, kwargs
        p = str(prompt)
        if "标题" in p.lower() or "title" in p.lower():
            return '{"title": "Test Module", "description": "A test module"}'
        return _RICH_MARKDOWN

    async def _agenerate(messages, **kwargs):
        _ = kwargs
        user_txt = _extract_user_text_from_agenerate_messages(messages)
        if "输出JSON" in user_txt or "模块key:" in user_txt:
            return json.dumps(
                {"title": "集成测试模块", "description": "用于管道集成测试的模块描述"},
                ensure_ascii=False,
            )
        return _RICH_MARKDOWN

    async def _complete_json(messages, schema, **kwargs):
        _ = messages, schema, kwargs
        return {
            "summary_text": _RICH_MARKDOWN,
            "dependencies": [],
        }

    async def _complete_with_tools(messages, tools, **kwargs):
        _ = messages, tools, kwargs
        return {"content": _RICH_MARKDOWN, "tool_calls": None}

    mock = MagicMock()
    mock.generate = AsyncMock(side_effect=_generate)
    mock.agenerate = AsyncMock(side_effect=_agenerate)
    mock.complete_json = AsyncMock(side_effect=_complete_json)
    mock.complete_with_tools = AsyncMock(side_effect=_complete_with_tools)
    return mock


def _make_mock_graph_store():
    """Create a mock graph store that returns empty query results."""
    mock = MagicMock()
    mock.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    return mock


def _make_modules():
    """Create test module data (roles allow compose_leaf_modules to run)."""
    from store.schema import GraphNode, NodeLabel

    return {
        "repo1": [
            GraphNode(
                label=NodeLabel.MODULE,
                properties={
                    "name": "AuthService",
                    "file_path": "src/auth.py",
                    "code_length": 500,
                    "repository": "repo1",
                    "methods_count": 8,
                    "start_line": 1,
                    "end_line": 220,
                },
                uid="u1",
            ),
            GraphNode(
                label=NodeLabel.MODULE,
                properties={
                    "name": "PaymentService",
                    "file_path": "src/payment.py",
                    "code_length": 400,
                    "repository": "repo1",
                    "methods_count": 6,
                    "start_line": 1,
                    "end_line": 180,
                },
                uid="u2",
            ),
        ],
    }


@pytest.mark.asyncio
async def test_full_pipeline_produces_pages():
    """Smoke test: the pipeline runs end-to-end and produces pages."""
    from wiki.pipeline_orchestrator import run_langgraph_pipeline

    result = await run_langgraph_pipeline(
        business_id="integration-test",
        repositories=["repo1"],
        all_modules=_make_modules(),
        llm=_make_mock_llm(),
        graph_store=_make_mock_graph_store(),
    )

    assert len(result.pages) >= 1
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_full_pipeline_pages_have_canonical_keys():
    from wiki.pipeline_orchestrator import run_langgraph_pipeline

    kwargs = dict(
        business_id="integration-test",
        repositories=["repo1"],
        all_modules=_make_modules(),
        llm=_make_mock_llm(),
        graph_store=_make_mock_graph_store(),
    )
    first = await run_langgraph_pipeline(**kwargs)
    second = await run_langgraph_pipeline(**kwargs)

    for pages in (first.pages, second.pages):
        for p in pages:
            ck = getattr(p, "canonical_key", None)
            assert ck, f"expected canonical_key on page path={p.path!r}"

    keys_a = sorted({str(getattr(p, "canonical_key")) for p in first.pages})
    keys_b = sorted({str(getattr(p, "canonical_key")) for p in second.pages})
    assert keys_a == keys_b
