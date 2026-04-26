"""Tests for request timing and ID middleware."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.middleware.request_logging import RequestLoggingMiddleware


@pytest.fixture
def logging_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "1"}

    return app


def test_adds_request_id_header(logging_app: FastAPI) -> None:
    client = TestClient(logging_app)
    rid = "client-req-99"
    r = client.get("/api/v1/ping", headers={"X-Request-ID": rid})
    assert r.status_code == 200
    assert r.headers["X-Request-Id"] == rid


def test_adds_response_time_header(logging_app: FastAPI) -> None:
    client = TestClient(logging_app)
    r = client.get("/api/v1/ping")
    assert r.status_code == 200
    assert "X-Response-Time" in r.headers
    assert r.headers["X-Response-Time"].endswith("ms")


def test_skips_health_check_logging(logging_app: FastAPI) -> None:
    client = TestClient(logging_app)
    with patch("api.middleware.request_logging.log") as mock_log:
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        mock_log.info.assert_not_called()

    with patch("api.middleware.request_logging.log") as mock_log:
        client.get("/api/v1/ping")
        mock_log.info.assert_called_once()
        args, kwargs = mock_log.info.call_args
        assert args[0] == "request_completed"
