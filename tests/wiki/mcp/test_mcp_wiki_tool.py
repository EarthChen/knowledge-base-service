"""MCP Wiki tools — T2.6 registration and handler behavior (mocked pipeline)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler, MCP_TOOLS_MANIFEST
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
        assert wiki_names == {"generate_wiki", "get_wiki_page", "list_wiki_pages"}


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
