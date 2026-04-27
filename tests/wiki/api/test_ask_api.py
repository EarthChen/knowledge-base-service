"""HTTP tests for POST /api/v1/wiki/ask — P1.5 SSE."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import auth as auth_module
from api.error_handler import register_exception_handlers
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
    register_exception_handlers(app)
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
        register_exception_handlers(app)
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
        assert r.json()["error"]["code"] == "kb_service_unavailable"


class TestWikiAskStreamV2:
    """POST/GET /api/v1/wiki/ask/stream — data-only SSE with type: token|sources|done."""

    def test_ask_stream_post_format(self) -> None:
        mock_ask = MagicMock()

        async def stream_v2(**kwargs: Any):
            _ = kwargs
            yield {"event": "wiki-answer", "data": {"content": "Hi", "delta": "Hi"}}
            yield {
                "event": "wiki-sources",
                "data": {
                    "sources": [
                        {
                            "entity": "X",
                            "file_path": "a.py",
                            "start_line": 1,
                            "wiki_page": "b.md",
                            "relevance_score": 0.5,
                        }
                    ]
                },
            }
            yield {
                "event": "wiki-answer-complete",
                "data": {"conversation_id": "c1", "tokens_used": 3, "reasoning_path": None},
            }

        mock_ask.ask_stream = stream_v2
        _, client, _ = _make_ask_app(mock_ask)

        r = client.post(
            "/api/v1/wiki/ask/stream",
            json={"repository": "r", "question": "Q?"},
        )
        assert r.status_code == 200
        assert "text/event-stream" in (r.headers.get("content-type") or "")
        text = r.text
        assert '"type": "token"' in text
        assert '"type": "sources"' in text
        assert '"type": "done"' in text
        assert "c1" in text

    def test_ask_stream_get_format(self) -> None:
        mock_ask = MagicMock()

        async def track(**kwargs: Any):
            assert kwargs.get("repository") == "my-repo"
            async for x in _fake_ask_stream(**kwargs):
                yield x

        mock_ask.ask_stream = track
        _, client, _ = _make_ask_app(mock_ask)

        r = client.get(
            "/api/v1/wiki/ask/stream",
            params={"repository": "my-repo", "question": "How?"},
        )
        assert r.status_code == 200
        assert '"type": "token"' in r.text

    def test_ask_stream_distinguishable_from_legacy(self) -> None:
        """v2 has no `event:` line; legacy /ask has event: wiki-answer."""
        mock_ask = MagicMock()
        mock_ask.ask_stream = _fake_ask_stream
        _, client, _ = _make_ask_app(mock_ask)

        v2 = client.post(
            "/api/v1/wiki/ask/stream",
            json={"repository": "r", "question": "Q"},
        )
        assert v2.status_code == 200
        assert "event: " not in v2.text

        legacy = client.post(
            "/api/v1/wiki/ask",
            json={"repository": "r", "question": "Q"},
        )
        assert legacy.status_code == 200
        assert "event: wiki-answer" in legacy.text
