"""MCP Wiki tools — T2.6 registration and handler behavior (mocked pipeline)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler, MCP_TOOLS_MANIFEST
from store.falkordb_store import QueryResultWrapper
from wiki.cache import WikiCache
from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST, WikiMCPHandler
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
)


def _sample_page() -> WikiPage:
    loc = SourceLocation(
        file_path="src/App.java",
        start_line=1,
        end_line=50,
        fqn="com.example.App",
        repository="demo-repo",
    )
    meta = WikiPageMetadata(node_count=3, edge_count=2, generation_mode="structure")
    return WikiPage(
        path="overview.md",
        title="App",
        page_type=PageType.MODULE_OVERVIEW,
        content="# App\n",
        diagrams=[
            WikiDiagram(diagram_type=DiagramType.CLASS_DIAGRAM, content="classDiagram", title="Classes"),
        ],
        source_locations=[loc],
        metadata=meta,
    )


@pytest.fixture
def wiki_pipeline() -> AsyncMock:
    p = AsyncMock()
    p.generate_wiki = AsyncMock(return_value=[_sample_page()])
    p.get_wiki_page = AsyncMock(return_value=_sample_page())
    p.list_wiki_pages = AsyncMock(
        return_value={
            "repository": "demo-repo",
            "tree": {"path": "/", "title": "root", "children": [], "metadata": {"pages": 1}},
            "total_pages": 1,
        },
    )
    p.search_wiki = AsyncMock(
        return_value={
            "results": [
                {
                    "page_path": "overview.md",
                    "title": "App",
                    "score": 0.9,
                    "snippet": "App overview",
                    "source_locations": [],
                    "context": {},
                },
            ],
            "query_expansion": {"original": "test", "expanded": []},
            "total": 1,
        },
    )
    p.ask_about_code = AsyncMock(
        return_value={
            "content": "The App class handles...",
            "sources": [
                {
                    "entity": "App",
                    "file_path": "src/App.java",
                    "start_line": 1,
                    "wiki_page": "overview.md",
                    "relevance_score": 0.9,
                },
            ],
            "conversation_id": "conv-123",
            "tokens_used": 100,
        },
    )
    return p


@pytest.fixture
def kb_handler(wiki_pipeline: AsyncMock) -> KnowledgeBaseMCPHandler:
    wiki = WikiMCPHandler(pipeline=wiki_pipeline)
    return KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        wiki_handler=wiki,
    )


class TestWikiToolsRegistered:
    def test_generate_wiki_tool_registered(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "generate_wiki" in names
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "generate_wiki")
        assert "inputSchema" in tool
        req = tool["inputSchema"].get("required", [])
        assert "repository" in req
        assert "scope" in req

    def test_get_wiki_page_tool_registered(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "get_wiki_page" in names

    def test_list_wiki_pages_tool_registered(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "list_wiki_pages" in names

    def test_wiki_manifest_matches_mcp_extension(self):
        """Wiki entries are appended to the main manifest (same definitions as WIKI slice)."""
        wiki_names = {t["name"] for t in WIKI_MCP_TOOLS_MANIFEST}
        assert wiki_names == {
            "generate_wiki",
            "get_wiki_page",
            "list_wiki_pages",
            "search_wiki",
            "ask_about_code",
            "traverse_call_chain",
            "find_impact_scope",
            "analyze_pr_impact",
            "wiki_lint",
            "wiki_export_preview",
            "wiki_export_execute",
        }

    def test_search_wiki_tool_registered(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "search_wiki" in names
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "search_wiki")
        assert "inputSchema" in tool
        req = tool["inputSchema"].get("required", [])
        assert "repository" in req
        assert "query" in req

    def test_ask_about_code_tool_registered(self):
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "ask_about_code" in names
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "ask_about_code")
        assert "inputSchema" in tool
        req = tool["inputSchema"].get("required", [])
        assert "repository" in req
        assert "question" in req

    def test_wiki_manifest_has_11_tools(self):
        assert len(WIKI_MCP_TOOLS_MANIFEST) == 11

    @pytest.mark.asyncio
    async def test_wiki_export_preview_without_cache_returns_error(self) -> None:
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=WikiMCPHandler(pipeline=None, wiki_cache=None),
        )
        r = await h.handle_tool_call("wiki_export_preview", {"repository": "r1", "target_dir": "/tmp"})
        assert r.get("error", {}).get("code") == "service_unavailable"

    @pytest.mark.asyncio
    async def test_wiki_export_preview_and_execute_dispatch(self, tmp_path) -> None:
        cache = WikiCache()
        cache.put(
            "r1",
            "repo",
            "structure",
            1,
            [
                WikiPage(
                    path="mcp.md",
                    title="M",
                    page_type=PageType.MODULE_OVERVIEW,
                    content="Hi",
                    diagrams=[],
                    source_locations=[],
                    metadata=WikiPageMetadata(node_count=1, edge_count=0),
                )
            ],
        )
        wiki = WikiMCPHandler(pipeline=None, wiki_cache=cache)
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=wiki,
        )
        out = tmp_path / "wiki_md"
        out.mkdir()
        prev = await h.handle_tool_call(
            "wiki_export_preview",
            {"repository": "r1", "target_dir": str(out)},
        )
        assert prev.get("status") == "success"
        assert prev["total_files"] == 1
        assert prev["diffs"][0]["action"] == "create"

        ex = await h.handle_tool_call(
            "wiki_export_execute",
            {"repository": "r1", "target_dir": str(out), "selected_files": ["mcp.md"]},
        )
        assert ex.get("status") == "success"
        assert (out / "mcp.md").exists()

    @pytest.mark.asyncio
    async def test_wiki_lint_without_store_returns_service_error(self, kb_handler: KnowledgeBaseMCPHandler) -> None:
        result = await kb_handler.handle_tool_call("wiki_lint", {"repository": "demo-repo"})
        assert result.get("error", {}).get("code") == "service_unavailable"

    @pytest.mark.asyncio
    async def test_wiki_lint_with_store_returns_success(self, wiki_pipeline: AsyncMock) -> None:
        store = MagicMock()

        async def _eq(_cypher: str, _params: dict | None = None) -> QueryResultWrapper:
            return QueryResultWrapper(data=[], raw=[])

        store.execute_query = _eq
        wiki = WikiMCPHandler(pipeline=wiki_pipeline, store=store)
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            store=store,
            wiki_handler=wiki,
        )
        result = await h.handle_tool_call("wiki_lint", {"repository": "demo-repo", "scope": "all"})
        assert result.get("status") == "success"
        assert "issues" in result


class TestGenerateWiki:
    @pytest.mark.asyncio
    async def test_generate_wiki_valid(self, kb_handler: KnowledgeBaseMCPHandler, wiki_pipeline: AsyncMock):
        result = await kb_handler.handle_tool_call(
            "generate_wiki",
            {"repository": "demo-repo", "scope": "module:src/App.java", "mode": "structure"},
        )
        assert "error" not in result
        assert result.get("status") == "success"
        pages = result["pages"]
        assert len(pages) == 1
        assert pages[0]["title"] == "App"
        assert pages[0]["source_locations"]
        assert pages[0]["source_locations"][0]["fqn"] == "com.example.App"
        wiki_pipeline.generate_wiki.assert_awaited_once_with(
            "demo-repo", "module:src/App.java", "structure",
        )

    @pytest.mark.asyncio
    async def test_generate_wiki_invalid_scope(self, kb_handler: KnowledgeBaseMCPHandler):
        result = await kb_handler.handle_tool_call(
            "generate_wiki",
            {"repository": "demo-repo", "scope": "not-a-valid-scope", "mode": "structure"},
        )
        assert "error" in result
        err = result["error"]
        assert err["code"] == "invalid_scope"


class TestGetWikiPage:
    @pytest.mark.asyncio
    async def test_get_wiki_page_exists(self, kb_handler: KnowledgeBaseMCPHandler, wiki_pipeline: AsyncMock):
        result = await kb_handler.handle_tool_call(
            "get_wiki_page",
            {"repository": "demo-repo", "scope": "class:com.example.App"},
        )
        assert "error" not in result
        assert result["page"]["title"] == "App"
        assert result["diagrams"]
        assert result["source_locations"]
        wiki_pipeline.get_wiki_page.assert_awaited_once_with("demo-repo", "class:com.example.App")

    @pytest.mark.asyncio
    async def test_get_wiki_page_not_found(self, wiki_pipeline: AsyncMock):
        wiki_pipeline.get_wiki_page = AsyncMock(return_value=None)
        wiki = WikiMCPHandler(pipeline=wiki_pipeline)
        kb = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=wiki,
        )
        result = await kb.handle_tool_call(
            "get_wiki_page",
            {"repository": "demo-repo", "scope": "class:missing.Class"},
        )
        assert "error" in result
        err = result["error"]
        assert err["code"] == "not_found"
        assert "not found" in err["message"].lower()


class TestListWikiPages:
    @pytest.mark.asyncio
    async def test_list_wiki_pages(self, kb_handler: KnowledgeBaseMCPHandler, wiki_pipeline: AsyncMock):
        result = await kb_handler.handle_tool_call(
            "list_wiki_pages",
            {"repository": "demo-repo"},
        )
        assert "error" not in result
        assert result["repository"] == "demo-repo"
        assert "tree" in result
        wiki_pipeline.list_wiki_pages.assert_awaited_once_with("demo-repo", None)


class TestErrorPropagation:
    @pytest.mark.asyncio
    async def test_tool_error_propagation(self, wiki_pipeline: AsyncMock):
        wiki_pipeline.generate_wiki = AsyncMock(side_effect=RuntimeError("graph offline"))
        wiki = WikiMCPHandler(pipeline=wiki_pipeline)
        kb = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=wiki,
        )
        result = await kb.handle_tool_call(
            "generate_wiki",
            {"repository": "r", "scope": "repo", "mode": "full"},
        )
        assert result == {"error": "graph offline"}


class TestSearchWiki:
    @pytest.mark.asyncio
    async def test_search_wiki_valid(self, kb_handler: KnowledgeBaseMCPHandler, wiki_pipeline: AsyncMock):
        result = await kb_handler.handle_tool_call(
            "search_wiki",
            {"repository": "demo-repo", "query": "App class", "mode": "hybrid", "limit": 10, "min_score": 0.0},
        )
        assert "error" not in result
        assert result["total"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["score"] == 0.9
        assert result["results"][0]["snippet"] == "App overview"
        wiki_pipeline.search_wiki.assert_awaited_once_with(
            "demo-repo", "App class", "hybrid", 10, 0.0, None,
        )

    @pytest.mark.asyncio
    async def test_search_wiki_empty_query(self, kb_handler: KnowledgeBaseMCPHandler):
        result = await kb_handler.handle_tool_call(
            "search_wiki",
            {"repository": "demo-repo", "query": "   "},
        )
        assert "error" in result
        assert result["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_search_wiki_not_configured(self):
        kb = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=WikiMCPHandler(None),
        )
        result = await kb.handle_tool_call(
            "search_wiki",
            {"repository": "demo-repo", "query": "x"},
        )
        assert "error" in result
        assert result["error"]["code"] == "service_unavailable"


class TestAskAboutCode:
    @pytest.mark.asyncio
    async def test_ask_about_code_valid(self, kb_handler: KnowledgeBaseMCPHandler, wiki_pipeline: AsyncMock):
        result = await kb_handler.handle_tool_call(
            "ask_about_code",
            {
                "repository": "demo-repo",
                "question": "What does App do?",
                "scope": "module:src",
                "conversation_id": "cid-1",
            },
        )
        assert "error" not in result
        assert result["content"] == "The App class handles..."
        assert len(result["sources"]) == 1
        assert result["sources"][0]["entity"] == "App"
        wiki_pipeline.ask_about_code.assert_awaited_once_with(
            "demo-repo", "What does App do?", "module:src", "cid-1",
        )

    @pytest.mark.asyncio
    async def test_ask_about_code_empty_question(self, kb_handler: KnowledgeBaseMCPHandler):
        result = await kb_handler.handle_tool_call(
            "ask_about_code",
            {"repository": "demo-repo", "question": ""},
        )
        assert "error" in result
        assert result["error"]["code"] == "invalid_params"

    @pytest.mark.asyncio
    async def test_ask_about_code_not_configured(self):
        kb = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            wiki_handler=WikiMCPHandler(None),
        )
        result = await kb.handle_tool_call(
            "ask_about_code",
            {"repository": "demo-repo", "question": "Why?"},
        )
        assert "error" in result
        assert result["error"]["code"] == "service_unavailable"
