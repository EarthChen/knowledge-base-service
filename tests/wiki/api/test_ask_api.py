"""HTTP tests for POST /api/v1/wiki/ask — P1.5 SSE."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.routes.wiki_routes import (
    WikiTaskRegistry,
    get_task_registry_dep,
    get_wiki_ask_dep,
    get_wiki_service_dep,
    wiki_router,
)


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def _make_ask_app(mock_ask: Any | None = None) -> tuple[FastAPI, TestClient, Any]:
    app = FastAPI()
    app.state.wiki_tasks = WikiTaskRegistry()

    svc = mock_ask if mock_ask is not None else MagicMock()

    async def override_wiki() -> Any:
        return MagicMock()

    async def override_ask() -> Any:
        return svc

    app.include_router(wiki_router)
    app.dependency_overrides[get_wiki_service_dep] = override_wiki
    app.dependency_overrides[get_wiki_ask_dep] = override_ask

    def override_registry() -> WikiTaskRegistry:
        return app.state.wiki_tasks

    app.dependency_overrides[get_task_registry_dep] = override_registry

    return app, TestClient(app), svc


async def _fake_ask_stream(**kwargs: Any):
    yield {"event": "wiki-answer", "data": {"content": "Hello ", "delta": "Hello "}}
    yield {"event": "wiki-answer", "data": {"content": "Hello world", "delta": "world"}}
    yield {
        "event": "wiki-sources",
        "data": {
            "sources": [
                {
                    "entity": "UserService",
                    "file_path": "src/User.java",
                    "start_line": 10,
                    "wiki_page": "classes/UserService.md",
                    "relevance_score": 0.9,
                }
            ]
        },
    }
    yield {
        "event": "wiki-answer-complete",
        "data": {"conversation_id": kwargs.get("conversation_id") or "new-id", "tokens_used": 42},
    }


class TestWikiAsk:
    def test_ask_streaming(self) -> None:
        mock_ask = MagicMock()
        mock_ask.ask_stream = _fake_ask_stream
        _, client, _ = _make_ask_app(mock_ask)

        r = client.post(
            "/api/v1/wiki/ask",
            json={
                "repository": "my-repo",
                "question": "How does auth work?",
            },
        )
        assert r.status_code == 200
        text = r.text
        assert "event: wiki-answer" in text
        assert "event: wiki-sources" in text
        assert "event: wiki-answer-complete" in text

    def test_ask_with_conversation_id(self) -> None:
        async def stream_with_conv(*, repository: str, question: str, **kwargs: Any):
            cid = kwargs.get("conversation_id")
            assert cid == "conv-xxx"
            yield {"event": "wiki-answer", "data": {"content": "x", "delta": "x"}}
            yield {"event": "wiki-sources", "data": {"sources": []}}
            yield {
                "event": "wiki-answer-complete",
                "data": {"conversation_id": cid, "tokens_used": 1},
            }

        mock_ask = MagicMock()
        mock_ask.ask_stream = stream_with_conv
        _, client, _ = _make_ask_app(mock_ask)

        r = client.post(
            "/api/v1/wiki/ask",
            json={
                "repository": "my-repo",
                "question": "Q?",
                "conversation_id": "conv-xxx",
            },
        )
        assert r.status_code == 200
        assert "conv-xxx" in r.text

    def test_ask_empty_question_400(self) -> None:
        _, client, mock_ask = _make_ask_app(MagicMock())
        r = client.post(
            "/api/v1/wiki/ask",
            json={
                "repository": "my-repo",
                "question": "",
            },
        )
        assert r.status_code == 422
        mock_ask.ask_stream.assert_not_called()

    def test_ask_source_references(self) -> None:
        mock_ask = MagicMock()
        mock_ask.ask_stream = _fake_ask_stream
        _, client, _ = _make_ask_app(mock_ask)

        r = client.post(
            "/api/v1/wiki/ask",
            json={
                "repository": "my-repo",
                "question": "Where is UserService?",
            },
        )
        assert r.status_code == 200
        assert "src/User.java" in r.text
        assert '"start_line": 10' in r.text or '"start_line":10' in r.text.replace(" ", "")

    def test_ask_service_unavailable(self) -> None:
        app = FastAPI()
        app.state.wiki_tasks = WikiTaskRegistry()

        async def override_wiki() -> Any:
            return MagicMock()

        app.include_router(wiki_router)
        app.dependency_overrides[get_wiki_service_dep] = override_wiki

        def override_registry() -> WikiTaskRegistry:
            return app.state.wiki_tasks

        app.dependency_overrides[get_task_registry_dep] = override_registry

        client = TestClient(app)
        r = client.post(
            "/api/v1/wiki/ask",
            json={"repository": "my-repo", "question": "x"},
        )
        assert r.status_code == 503
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("error") == "service_unavailable"
