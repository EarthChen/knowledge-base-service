from unittest.mock import MagicMock, patch

import pytest

from api.exceptions import KbError, KbNotFound
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
    err = r["error"]
    assert err["code"] == "kb_error"
    assert err["message"] == "bad request"
    assert err["http_status"] == 500


@pytest.mark.asyncio
async def test_mcp_tool_call_sanitizes_unexpected_exception():
    server = MCPWikiServer()
    with patch.object(
        server, "_handle_wiki_search", side_effect=RuntimeError("do not leak"),
    ):
        r = await server.handle_tool_call("wiki_search", {"query": "x", "repository": "r"})
    err = r["error"]
    assert err["code"] == "internal_error"
    assert err["message"] == "Internal tool error"
    assert err["http_status"] == 500


@pytest.mark.asyncio
async def test_mcp_handle_tool_call_maps_kb_not_found():
    class ErrAsk:
        async def ask_stream(self, **kwargs):
            raise KbNotFound("nope")
            if False:  # pragma: no cover
                yield {}

    mcp = MCPWikiServer(ask_service=ErrAsk(), search_service=None, wiki_store=None, change_detector=None)
    out = await mcp.handle_tool_call("wiki_qa", {"question": "q", "repository": "r", "business_id": "b"})
    assert "error" in out
    err = out["error"]
    assert err["code"] == "kb_not_found"
    assert err["message"] == "nope"
    assert err["http_status"] == 404


@pytest.mark.asyncio
async def test_mcp_handle_tool_call_unknown_tool():
    server = MCPWikiServer()
    r = await server.handle_tool_call("not_a_real_tool", {})
    err = r["error"]
    assert err["code"] == "mcp_unknown_tool"
    assert err["http_status"] == 400
    assert "not_a_real_tool" in err["message"]
