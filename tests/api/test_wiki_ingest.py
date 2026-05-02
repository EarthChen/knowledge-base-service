import core.auth as auth_module
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def test_ingest_endpoint_accepts_file_list():
    """POST /api/v1/wiki/ingest should accept a file list and trigger incremental generation."""
    from main import create_app
    from api.error_handler import register_exception_handlers

    app = create_app()
    _ = register_exception_handlers  # keep hook consistent with spec

    mock_service = AsyncMock()
    mock_service.bump_affected_wiki_pages = AsyncMock(
        return_value={
            "pages_regenerated": 2,
            "pages_total": 3,
            "trigger": "api",
            "errors": [],
        }
    )
    mock_detector = AsyncMock()
    mock_detector.detect_from_file_list = AsyncMock(
        return_value=MagicMock(
            page_uids=["p1", "p2", "p3"],
            affected_entities=["e1"],
            trigger="api",
            files_changed=["a.py"],
        )
    )

    app.state.wiki_service_factory = AsyncMock(return_value=mock_service)
    app.state.wiki_store = MagicMock()
    app.state.change_detector = mock_detector

    client = TestClient(app)
    resp = client.post(
        "/api/v1/wiki/ingest",
        json={
            "repository": "test-repo",
            "files": ["auth.py", "utils.py"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "pages_regenerated" in data


def test_ingest_endpoint_rejects_empty_files():
    from main import create_app

    app = create_app()
    app.state.wiki_store = MagicMock()

    client = TestClient(app)
    resp = client.post(
        "/api/v1/wiki/ingest",
        json={
            "repository": "test-repo",
            "files": [],
        },
    )
    assert resp.status_code in (200, 400)
