"""Regression tests for context assembler, FQN, MCP rag_query, and reranker fixes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from indexer.code_graph_builder import compute_fqn
from query.context_assembler import ContextAssembler
from query.reranker import Reranker


@pytest.mark.asyncio
async def test_context_assembler_passes_repository_and_language_to_search():
    mock_store = AsyncMock()
    mock_hybrid = AsyncMock()
    mock_graph = AsyncMock()

    matches = [
        {
            "name": "foo",
            "type": "Function",
            "uid": "fn-1",
            "file": "f.py",
            "line": 1,
            "repository": "repo-a",
            "score": 1.0,
            "confidence": 1.0,
            "match_source": "keyword",
        },
    ]
    mock_hybrid.search_with_context = AsyncMock(
        return_value={
            "results": matches,
            "semantic_matches": matches,
            "total": 1,
            "offset": 0,
            "limit": 500,
            "graph_context": [],
            "query_text": "",
            "confidence": 0.9,
            "no_results_reason": "",
        },
    )

    async def dispatch(q, _params=None):
        qs = q or ""
        if "WikiPage" in qs:
            return MagicMock(data=[])
        return MagicMock(
            data=[
                {
                    "uid": "fn-1",
                    "name": "foo",
                    "type": "Function",
                    "file": "f.py",
                    "start_line": 1,
                    "end_line": 5,
                    "code_snippet": "def foo(): pass",
                    "docstring": "doc",
                    "signature": "foo()",
                    "repository": "repo-a",
                },
            ],
        )

    mock_store.execute_query = AsyncMock(side_effect=dispatch)
    mock_graph.find_call_chain = AsyncMock(return_value=MagicMock(data=[]))
    mock_graph.find_inheritance_tree = AsyncMock(return_value=MagicMock(data=[]))
    mock_graph.find_flows_for_function = AsyncMock(return_value=MagicMock(data=[]))

    asm = ContextAssembler(mock_store, mock_hybrid, mock_graph)
    await asm.assemble("foo", repository="repo-a", language="python", max_tokens=8000)

    mock_hybrid.search_with_context.assert_awaited_once()
    call_kw = mock_hybrid.search_with_context.await_args
    assert call_kw.kwargs.get("repository") == "repo-a"
    assert call_kw.kwargs.get("language") == "python"


def test_compute_fqn_python_class_and_methods():
    assert compute_fqn("src/pkg/mod.py", "MyClass", "Class") == "src.pkg.mod.MyClass"
    assert (
        compute_fqn("src/pkg/mod.py", "meth", "Function", parent_class="MyClass")
        == "src.pkg.mod.MyClass.meth"
    )
    assert compute_fqn("top.py", "func", "Function", parent_class="") == "top.func"


def test_compute_fqn_go():
    assert compute_fqn("internal/api/handler.go", "GetUser", "Function", parent_class="") == "api.GetUser"
    assert (
        compute_fqn("internal/api/handler.go", "GetUser", "Function", parent_class="Server")
        == "api.Server.GetUser"
    )


def test_compute_fqn_javascript_typescript():
    assert compute_fqn("src/components/Button.tsx", "Button", "Class") == "src/components/Button.Button"
    assert (
        compute_fqn("src/components/Button.tsx", "onClick", "Function", parent_class="Button")
        == "src/components/Button.Button.onClick"
    )


def test_reranker_candidate_text_includes_code_snippet_or_content():
    long_body = "x" * 600
    text = Reranker._candidate_text(
        {
            "name": "f",
            "signature": "()",
            "code_snippet": long_body,
        }
    )
    assert "x" * 200 in text
    assert len(text) < len(long_body) + 200

    text2 = Reranker._candidate_text(
        {"name": "g", "content": "def g(): return 1" * 50},
    )
    assert "def g()" in text2


def test_mcp_rag_query_schema_includes_hybrid_controls():
    from api.mcp_server import MCP_TOOLS_MANIFEST

    tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_query")
    props = tool["inputSchema"]["properties"]
    for key in (
        "use_child_chunks",
        "use_query_router",
        "use_query_expansion",
        "per_file_cap",
        "offset",
    ):
        assert key in props, f"missing {key}"


@pytest.mark.asyncio
async def test_handle_rag_query_passes_through_hybrid_controls():
    from api.mcp_server import KnowledgeBaseMCPHandler

    hybrid = AsyncMock()
    hybrid.search_with_context = AsyncMock(
        return_value={
            "results": [],
            "semantic_matches": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
            "graph_context": [],
            "query_text": "auth",
            "confidence": 0.0,
            "no_results_reason": "",
        },
    )
    graph = AsyncMock()
    indexer = MagicMock()

    srv = KnowledgeBaseMCPHandler(
        hybrid_svc=hybrid,
        graph_svc=graph,
        indexer=indexer,
    )

    await srv.handle_rag_query(
        {
            "query": "auth",
            "k": 3,
            "expand_depth": 1,
            "use_child_chunks": True,
            "use_query_router": False,
            "use_query_expansion": False,
            "per_file_cap": 5,
            "repository": "r1",
            "language": "python",
        },
    )

    hybrid.search_with_context.assert_awaited_once()
    kw = hybrid.search_with_context.await_args.kwargs
    assert kw["use_child_chunks"] is True
    assert kw["use_query_router"] is False
    assert kw["use_query_expansion"] is False
    assert kw["per_file_cap"] == 5
    assert kw["repository"] == "r1"
    assert kw["language"] == "python"
