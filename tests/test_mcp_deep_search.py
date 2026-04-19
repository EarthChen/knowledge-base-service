"""MCP handlers: list_documents, get_document, rag_index git_url (deep_search is HTTP-only)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler, MCP_TOOLS_MANIFEST


@pytest.fixture
def minimal_kb_handler() -> KnowledgeBaseMCPHandler:
    return KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
    )


@pytest.mark.asyncio
async def test_manifest_includes_new_tools() -> None:
    names = {t["name"] for t in MCP_TOOLS_MANIFEST}
    assert "list_documents" in names
    assert "get_document" in names


@pytest.mark.asyncio
async def test_list_documents_requires_store() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=None,
        wiki_handler=MagicMock(),
    )
    r = await h.handle_list_documents({})
    assert r["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_list_documents_formats_response() -> None:
    store = MagicMock()
    mock_qr = MagicMock()
    mock_qr.list_documents = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "uid": "d1",
                    "file": "/data/repos/myrepo/README.md",
                    "title": "Readme",
                    "name": "Readme",
                    "repository": "myrepo",
                    "content_hash": "abc",
                    "sec_uid": "s1",
                    "sec_name": "Intro",
                    "sec_title": None,
                    "sec_start_line": 1,
                },
            ],
        ),
    )
    with patch("store.graph_queries.GraphQueryRepository", return_value=mock_qr):
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            store=store,
            wiki_handler=MagicMock(),
        )
        r = await h.handle_list_documents({"repository": "myrepo"})
    assert "error" not in r
    assert r["total"] == 1
    assert r["documents"][0]["uid"] == "d1"
    assert r["documents"][0]["file"] == "README.md"
    assert len(r["documents"][0]["sections"]) == 1


@pytest.mark.asyncio
async def test_get_document_not_found() -> None:
    store = MagicMock()
    mock_qr = MagicMock()
    mock_qr.get_document = AsyncMock(return_value=MagicMock(data=[]))
    with patch("store.graph_queries.GraphQueryRepository", return_value=mock_qr):
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            store=store,
            wiki_handler=MagicMock(),
        )
        r = await h.handle_get_document({"doc_uid": "missing"})
    assert r["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_document_success() -> None:
    store = MagicMock()
    mock_qr = MagicMock()
    mock_qr.get_document = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "title": "T",
                    "file": "/data/repos/r/doc.md",
                    "repository": "r",
                    "section_uid": "s1",
                    "section_name": "Sec",
                    "section_title": None,
                    "content": "body",
                    "start_line": 1,
                    "level": 2,
                },
            ],
        ),
    )
    with patch("store.graph_queries.GraphQueryRepository", return_value=mock_qr):
        h = KnowledgeBaseMCPHandler(
            hybrid_svc=MagicMock(),
            graph_svc=MagicMock(),
            indexer=MagicMock(),
            store=store,
            wiki_handler=MagicMock(),
        )
        r = await h.handle_get_document({"doc_uid": "d1"})
    assert "error" not in r
    assert r["title"] == "T"
    assert r["file"] == "doc.md"
    assert r["sections"][0]["uid"] == "s1"


@pytest.mark.asyncio
async def test_rag_index_git_url_clones_and_indexes() -> None:
    indexer = MagicMock()
    indexer.index_full = AsyncMock(return_value={"nodes": 2, "edges": 1, "embeddings": 0})

    clone_result = {
        "directory": "/tmp/cloned/repo",
        "repository": "group/project",
        "status": "cloned",
        "detail": "",
    }
    git_instance = MagicMock()
    git_instance.ensure_repo = AsyncMock(return_value=clone_result)

    settings_mock = MagicMock()
    settings_mock.git = MagicMock()
    settings_mock.git.clone_base_path = "/tmp/cloned"

    with patch("git_manager.GitManager", return_value=git_instance):
        with patch("config.get_settings", return_value=settings_mock):
            h = KnowledgeBaseMCPHandler(
                hybrid_svc=MagicMock(),
                graph_svc=MagicMock(),
                indexer=indexer,
                doc_indexer=None,
                store=None,
                wiki_handler=MagicMock(),
            )
            r = await h.handle_rag_index(
                {
                    "directory": "",
                    "git_url": "https://git.example.com/group/project.git",
                    "branch": "main",
                    "mode": "incremental",
                },
            )

    assert "error" not in r
    assert r["mode"] == "full"
    assert r["directory"] == "/tmp/cloned/repo"
    git_instance.ensure_repo.assert_awaited_once_with(
        "https://git.example.com/group/project.git",
        branch="main",
    )
    indexer.index_full.assert_awaited_once()


@pytest.mark.asyncio
async def test_rag_index_git_clone_failure_structured() -> None:
    indexer = MagicMock()
    clone_result = {
        "directory": "",
        "repository": "x",
        "status": "clone_failed",
        "detail": "permission denied",
    }
    git_instance = MagicMock()
    git_instance.ensure_repo = AsyncMock(return_value=clone_result)

    with patch("git_manager.GitManager", return_value=git_instance):
        with patch("config.get_settings", return_value=MagicMock(git=MagicMock())):
            h = KnowledgeBaseMCPHandler(
                hybrid_svc=MagicMock(),
                graph_svc=MagicMock(),
                indexer=indexer,
                wiki_handler=MagicMock(),
            )
            r = await h.handle_rag_index({"git_url": "https://example.com/x.git"})
    assert r["error"]["code"] == "git_operation_failed"
    assert "permission" in r["error"]["message"]
    indexer.index_full.assert_not_called()


@pytest.mark.asyncio
async def test_rag_index_requires_directory_or_git_url() -> None:
    h = KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        wiki_handler=MagicMock(),
    )
    r = await h.handle_rag_index({"directory": "", "git_url": ""})
    assert r["error"]["code"] == "invalid_params"
