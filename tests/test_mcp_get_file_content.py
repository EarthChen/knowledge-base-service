"""Tests for MCP get_file_content tool."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler


def _handler_with_store(store: MagicMock) -> KnowledgeBaseMCPHandler:
    return KnowledgeBaseMCPHandler(
        hybrid_svc=MagicMock(),
        graph_svc=MagicMock(),
        indexer=MagicMock(),
        store=store,
        wiki_handler=MagicMock(),
    )


@pytest.mark.asyncio
async def test_get_file_content_full_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        test_file = repo_dir / "src" / "main.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "src/main.py",
            })

        assert "error" not in r
        assert r["content"] == "line1\nline2\nline3\nline4\nline5\n"
        assert r["file_path"] == "src/main.py"
        assert r["total_lines"] == 5
        assert r["repository"] == "my-repo"


@pytest.mark.asyncio
async def test_get_file_content_line_range() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        test_file = repo_dir / "app.py"
        test_file.write_text("\n".join(f"line{i}" for i in range(1, 101)) + "\n")

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "app.py",
                "start_line": 10,
                "end_line": 20,
            })

        assert "error" not in r
        lines = r["content"].strip().split("\n")
        assert lines[0] == "line10"
        assert r["start_line"] == 10
        assert r["end_line"] == 20
        assert r["total_lines"] == 100


@pytest.mark.asyncio
async def test_get_file_content_path_traversal_blocked() -> None:
    h = _handler_with_store(MagicMock())
    with patch("api.mcp_server._resolve_repo_base_path", return_value=Path("/tmp/repo")):
        for bad_path in ["../../../etc/passwd", "src/../../secret", "/etc/hosts"]:
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": bad_path,
            })
            assert r["error"]["code"] == "invalid_params", f"Should block: {bad_path}"


@pytest.mark.asyncio
async def test_get_file_content_repo_traversal_blocked() -> None:
    """Repository name with '..' segments must be rejected."""
    h = _handler_with_store(MagicMock())
    for bad_repo in ["../../../etc", "legit/../../escape"]:
        from api.mcp_server import _resolve_repo_base_path
        assert _resolve_repo_base_path(bad_repo) is None


@pytest.mark.asyncio
async def test_get_file_content_file_not_found() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "nonexistent.py",
            })

        assert r["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_file_content_missing_params() -> None:
    h = _handler_with_store(MagicMock())
    r = await h.handle_get_file_content({})
    assert r["error"]["code"] == "invalid_params"

    r = await h.handle_get_file_content({"repository": "x"})
    assert r["error"]["code"] == "invalid_params"


@pytest.mark.asyncio
async def test_get_file_content_negative_line_numbers() -> None:
    """Negative and zero line numbers must be rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        (repo_dir / "f.py").write_text("a\nb\nc\n")

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "f.py",
                "start_line": 0,
            })
            assert r["error"]["code"] == "invalid_params"

            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "f.py",
                "end_line": -1,
            })
            assert r["error"]["code"] == "invalid_params"


@pytest.mark.asyncio
async def test_get_file_content_max_size_limit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        big_file = repo_dir / "big.py"
        big_file.write_text("x" * (2 * 1024 * 1024))

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            with patch("api.mcp_server._MAX_FILE_READ_BYTES", 1024 * 100):
                r = await h.handle_get_file_content({
                    "repository": "my-repo",
                    "file_path": "big.py",
                })

        assert "error" not in r
        assert r["truncated"] is True


@pytest.mark.asyncio
async def test_get_file_content_binary_file_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        (repo_dir / "img.png").write_bytes(b"\x89PNG\r\n\x00\x1a\n" + b"\x00" * 100)

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "img.png",
            })

        assert r["error"]["code"] == "read_error"
        assert "binary" in r["error"]["message"].lower()


@pytest.mark.asyncio
async def test_get_file_content_empty_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        (repo_dir / "empty.py").write_text("")

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_get_file_content({
                "repository": "my-repo",
                "file_path": "empty.py",
            })

        assert "error" not in r
        assert r["total_lines"] == 0
        assert r["content"] == ""


@pytest.mark.asyncio
async def test_get_file_content_dispatched_via_handle_tool_call() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "my-repo"
        repo_dir.mkdir()
        test_file = repo_dir / "hello.py"
        test_file.write_text("print('hello')\n")

        h = _handler_with_store(MagicMock())
        with patch("api.mcp_server._resolve_repo_base_path", return_value=repo_dir):
            r = await h.handle_tool_call("get_file_content", {
                "repository": "my-repo",
                "file_path": "hello.py",
            })

        assert "error" not in r
        assert r["content"] == "print('hello')\n"
