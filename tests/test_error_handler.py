"""Tests for unified API error responses (B7)."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.error_handler import ErrorResponse, register_exception_handlers


def _make_test_app(route_exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise route_exc

    return app


class TestUnifiedErrorFormat:
    def test_internal_details_not_exposed(self) -> None:
        secret = "SECRET_DB_PASSWORD_leak_path_/internal/module.py:999"
        app = _make_test_app(RuntimeError(secret))
        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 500
        body = r.json()
        assert secret not in r.text
        assert secret not in str(body)
        assert body["error"]["message"] != secret
        assert body["error"]["code"] == "internal_error"

    def test_error_response_matches_schema(self) -> None:
        app = _make_test_app(RuntimeError("x"))
        client = TestClient(app)
        r = client.get("/boom")
        parsed = ErrorResponse.model_validate(r.json())
        assert parsed.error.code
        assert parsed.error.message
        assert parsed.error.request_id is None or isinstance(parsed.error.request_id, str)

    def test_request_id_from_header(self) -> None:
        app = _make_test_app(RuntimeError("x"))
        client = TestClient(app)
        rid = "req-test-abc-123"
        r = client.get("/boom", headers={"X-Request-ID": rid})
        body = r.json()
        assert body["error"]["request_id"] == rid


class TestExceptionStatusMapping:
    def test_value_error_is_400(self) -> None:
        app = _make_test_app(ValueError("anything"))
        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 400
        body = r.json()
        assert body["error"]["code"] == "bad_request"

    def test_key_error_is_404(self) -> None:
        app = _make_test_app(KeyError("missing"))
        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 404
        body = r.json()
        assert body["error"]["code"] == "not_found"

    def test_file_not_found_is_404(self) -> None:
        app = _make_test_app(FileNotFoundError("/secret/path"))
        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 404
        assert "/secret" not in r.text
        assert "/secret" not in r.json()["error"]["message"]

    def test_wiki_repo_not_found_is_404(self) -> None:
        from wiki.service import WikiRepoNotFoundError

        app = _make_test_app(WikiRepoNotFoundError("ghost"))
        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 404
        body = r.json()
        assert "ghost" not in body["error"]["message"]

    def test_unknown_exception_is_500(self) -> None:
        app = _make_test_app(ZeroDivisionError())
        client = TestClient(app)
        r = client.get("/boom")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "internal_error"


class TestLoggingHook:
    def test_logs_error_with_exc_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr("api.error_handler.log", mock_log)
        app = _make_test_app(RuntimeError("logged internally"))
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/boom")
        mock_log.error.assert_called_once()
        kwargs = mock_log.error.call_args.kwargs
        assert kwargs.get("exc_info") is True
