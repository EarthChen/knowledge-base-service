"""Tests for File Explorer helpers and routes (Sprint 2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import auth as auth_module
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.error_handler import register_exception_handlers
from main import _build_file_tree, _get_service, viewer_router


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Viewer routes use require_role; empty token registry matches other API tests."""
    monkeypatch.setattr(auth_module, "_token_registry", {})


def test_build_file_tree_basic_paths() -> None:
    rows = [
        {"file": "src/a.py", "name": "a", "repository": "repo1"},
        {"file": "src/b.py", "name": "b", "repository": "repo1"},
    ]
    tree = _build_file_tree(rows, "")
    src = tree["children"][0]
    assert src["name"] == "src"
    names = sorted(c["name"] for c in src["children"])
    assert names == ["a.py", "b.py"]
    leaves = sorted(c["path"] for c in src["children"] if c["type"] == "file")
    assert leaves == ["src/a.py", "src/b.py"]


def test_build_file_tree_windows_separator() -> None:
    rows = [{"file": r"pkg\module\run.py", "repository": "r"}]
    tree = _build_file_tree(rows, "")
    pkg = tree["children"][0]
    assert pkg["name"] == "pkg"
    mod = pkg["children"][0]
    assert mod["name"] == "module"
    f = mod["children"][0]
    assert f["type"] == "file"
    assert f["path"].replace("\\", "/") == "pkg/module/run.py"


def test_build_file_tree_skips_empty_file() -> None:
    tree = _build_file_tree([{"file": "", "repository": "x"}], "")
    assert tree["children"] == []


def test_build_file_tree_directories_first_sorted() -> None:
    rows = [
        {"file": "zdir/z.py", "repository": "r"},
        {"file": "adir/a.py", "repository": "r"},
        {"file": "root.py", "repository": "r"},
    ]
    tree = _build_file_tree(rows, "")
    top = [c["name"] for c in tree["children"]]
    assert top == ["adir", "zdir", "root.py"]
    adir_children = [c["name"] for c in tree["children"][0]["children"]]
    assert adir_children == ["a.py"]


def test_build_file_tree_repository_param_on_files() -> None:
    rows = [{"file": "x.py", "repository": None}]
    tree = _build_file_tree(rows, "myrepo")
    f = tree["children"][0]
    assert f["type"] == "file"
    assert f["repository"] == "myrepo"


@pytest.fixture()
def viewer_client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(viewer_router)
    mock_svc = MagicMock()
    mock_svc.store = MagicMock()
    mock_svc.mcp_handler = MagicMock()
    mock_svc.graph_query = MagicMock()

    async def mock_get_service() -> MagicMock:
        return mock_svc

    app.dependency_overrides[_get_service] = mock_get_service
    app.state.test_svc = mock_svc  # shared instance for assertions
    return TestClient(app)


def test_files_tree_repository_filter_passes_repo_param(viewer_client: TestClient) -> None:
    svc = viewer_client.app.state.test_svc
    svc.store.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"file": "a.py", "name": "a", "repository": "r1"}]),
    )

    r = viewer_client.get("/api/v1/files/tree?repository=r1")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "directory"
    call = svc.store.execute_query.await_args_list[0]
    assert "m.repository = $repo" in call[0][0]
    assert call[0][1]["repo"] == "r1"


def test_files_tree_requires_repository(viewer_client: TestClient) -> None:
    r = viewer_client.get("/api/v1/files/tree")
    assert r.status_code == 422


def test_files_content_not_found(viewer_client: TestClient) -> None:
    svc = viewer_client.app.state.test_svc
    svc.mcp_handler.handle_get_file_content = AsyncMock(
        return_value={"error": {"code": "not_found", "message": "missing"}},
    )

    r = viewer_client.get("/api/v1/files/content?repository=repo&file_path=x.py")
    assert r.status_code == 404


def test_files_content_invalid(viewer_client: TestClient) -> None:
    svc = viewer_client.app.state.test_svc
    svc.mcp_handler.handle_get_file_content = AsyncMock(
        return_value={"error": {"code": "invalid_params", "message": "bad"}},
    )

    r = viewer_client.get("/api/v1/files/content?repository=repo&file_path=x.py")
    assert r.status_code == 400


def test_files_entities_returns_data(viewer_client: TestClient) -> None:
    svc = viewer_client.app.state.test_svc
    svc.graph_query.find_file_entities = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "name": "f",
                    "type": "Function",
                    "line": 1,
                    "signature": "def f()",
                    "docstring": "",
                    "uid": "u1",
                    "end_line": 3,
                },
            ],
        ),
    )

    r = viewer_client.get("/api/v1/files/entities?file_path=/path/x.py")
    assert r.status_code == 200
    body = r.json()
    assert body["file"] == "/path/x.py"
    assert len(body["entities"]) == 1
    assert body["entities"][0]["name"] == "f"
    assert body["entities"][0]["start_line"] == 1
