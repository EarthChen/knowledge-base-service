from unittest.mock import MagicMock, patch

import pytest

from api.exceptions import KbError
from api.mcp_wiki_server import MCPWikiServer, TOOL_DEFINITIONS


def test_tool_definitions_exist():
    assert len(TOOL_DEFINITIONS) >= 5
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "wiki_search" in names
    assert "wiki_explain" in names
    assert "wiki_navigate" in names
    assert "wiki_qa" in names
    assert "wiki_impact" in names


def test_server_initialization():
    server = MCPWikiServer()
    assert server is not None
    assert hasattr(server, "handle_tool_call")


@pytest.mark.asyncio
async def test_wiki_qa_returns_answer():
    async def ask_stream(
        *, repository, question, scope=None, business_id=None, **kwargs
    ):  # noqa: ARG001
        assert repository == "r1"
        assert question == "q?"
        yield {"event": "wiki-answer", "data": {"content": "partial"}}
        yield {"event": "wiki-answer", "data": {"content": "full answer"}}
        yield {"event": "wiki-answer-complete", "data": {"conversation_id": "conv-1"}}

    ask = MagicMock()
    ask.ask_stream = ask_stream
    server = MCPWikiServer(ask_service=ask)
    out = await server.handle_tool_call("wiki_qa", {"question": "q?", "repository": "r1"})
    assert out == {"answer": "full answer", "conversation_id": "conv-1"}


@pytest.mark.asyncio
async def test_mcp_tool_call_returns_kb_error_message():
    server = MCPWikiServer()
    with patch.object(
        server, "_handle_wiki_search", side_effect=KbError("bad request", detail="internal"),
    ):
        r = await server.handle_tool_call(
            "wiki_search", {"query": "x", "repository": "r", "limit": 3},
        )
    assert r == {"error": "bad request"}


@pytest.mark.asyncio
async def test_mcp_tool_call_sanitizes_unexpected_exception():
    server = MCPWikiServer()
    with patch.object(
        server, "_handle_wiki_search", side_effect=RuntimeError("do not leak"),
    ):
        r = await server.handle_tool_call("wiki_search", {"query": "x", "repository": "r"})
    assert r == {"error": "Internal tool error"}
