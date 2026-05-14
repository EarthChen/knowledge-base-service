"""HTTP tests for wiki edit session REST routes."""

from __future__ import annotations

import asyncio
import json
from itertools import chain, repeat
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import TokenInfo
from wiki.agents.edit_agent import EditEventQueue
from wiki.agents.events import (
    ContentEvent,
    DoneEvent,
    ThinkingEvent,
    ToolCallEvent,
)


@pytest.fixture(autouse=True)
def _wiki_edit_test_isolation(monkeypatch):
    """Open auth registry (no Bearer required) unless a test overrides `_get_registry`."""
    import api.routes.wiki_edit_routes as edit_routes
    import core.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_get_registry", lambda: {})
    edit_routes._clear_edit_session_burst_counters()
    yield
    edit_routes._clear_edit_session_burst_counters()


@pytest.fixture
def app():
    from api.routes.wiki_edit_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/wiki")

    mock_svc = AsyncMock()
    mock_svc.create_session = AsyncMock(return_value="sess-abc123")
    mock_svc.get_session = AsyncMock(return_value=None)
    mock_svc.delete_session = AsyncMock()
    mock_svc.apply_edit = AsyncMock(
        return_value={
            "page_uid": "p1",
            "content": "# New",
            "original_content": "# Old",
        },
    )

    app.state.wiki_edit_service = mock_svc

    queue_mock = MagicMock()
    mock_svc.send_message = AsyncMock(return_value=queue_mock)
    mock_svc.get_event_queue = MagicMock(return_value=None)

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.mark.asyncio
async def test_iter_edit_session_sse_serializes_sse():
    from api.routes.wiki_edit_routes import _iter_edit_session_sse

    q = EditEventQueue()
    await q.put(ContentEvent(text="hello"))
    await q.put(DoneEvent(result="hello"))

    chunks: list[bytes] = []
    async for chunk in _iter_edit_session_sse(q):
        chunks.append(chunk)
    merged = b"".join(chunks).decode()

    payloads = []
    for line in merged.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            payloads.append(json.loads(line.removeprefix("data: ")))

    assert any(p.get("type") == "content" for p in payloads)
    assert any(p.get("type") == "done" for p in payloads)


@pytest.mark.asyncio
async def test_iter_edit_session_sse_includes_event_type_line_before_data():
    from api.routes.wiki_edit_routes import _iter_edit_session_sse

    q = EditEventQueue()
    await q.put(ThinkingEvent(round_num=1, text="planning"))
    await q.put(ToolCallEvent(tool="lookup", args={"q": "x"}))
    await q.put(ContentEvent(text="hello"))
    await q.put(DoneEvent(result="hello"))

    chunks: list[bytes] = []
    async for chunk in _iter_edit_session_sse(q):
        chunks.append(chunk)
    merged = b"".join(chunks).decode()

    blocks = [b for b in merged.split("\n\n") if b.strip() and not b.lstrip().startswith(":")]
    assert len(blocks) == 4

    expected = [
        ("thinking", {"type": "thinking", "round_num": 1, "text": "planning"}),
        ("tool_call", {"type": "tool_call", "tool": "lookup", "args": {"q": "x"}}),
        ("content", {"type": "content", "text": "hello"}),
        ("done", {"type": "done", "result": "hello"}),
    ]
    for block, (want_event, want_payload) in zip(blocks, expected, strict=True):
        lines = block.split("\n")
        event_lines = [ln for ln in lines if ln.startswith("event:")]
        data_lines = [ln for ln in lines if ln.startswith("data:")]
        assert event_lines == [f"event: {want_event}"]
        assert len(data_lines) == 1
        assert json.loads(data_lines[0].split(":", 1)[1].strip()) == want_payload


def test_create_edit_session(client, app):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"prompt": "Fix the description", "current_content": "# Page\n\nOld text"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    svc = app.state.wiki_edit_service
    svc.create_session.assert_called_once_with(
        "page-1",
        "# Page\n\nOld text",
    )
    svc.send_message.assert_called_once_with("sess-abc123", "Fix the description")


def test_create_edit_session_missing_prompt(client):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"current_content": "# Page"},
    )
    assert resp.status_code == 422


def test_create_edit_session_empty_prompt(client):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"prompt": "", "current_content": "# Page"},
    )
    assert resp.status_code == 422


def test_create_edit_session_prompt_too_long(client):
    long_prompt = "x" * 2001
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session",
        json={"prompt": long_prompt, "current_content": "# Page"},
    )
    assert resp.status_code == 422


def test_send_message_prompt_too_long(client):
    long_prompt = "y" * 2001
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session/sess-abc123/message",
        json={"prompt": long_prompt},
    )
    assert resp.status_code == 422


def test_delete_edit_session(client, app):
    resp = client.delete("/api/v1/wiki/pages/page-1/edit-session/sess-abc123")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    app.state.wiki_edit_service.delete_session.assert_called_once_with(
        "sess-abc123",
    )


def test_apply_edit(client, app):
    resp = client.post("/api/v1/wiki/pages/page-1/edit-session/sess-abc123/apply")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page_uid"] == "p1"
    assert data["content"] == "# New"
    app.state.wiki_edit_service.apply_edit.assert_called_once_with("sess-abc123")


def test_send_message(client, app):
    resp = client.post(
        "/api/v1/wiki/pages/page-1/edit-session/sess-abc123/message",
        json={"prompt": "More detail please"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"
    app.state.wiki_edit_service.send_message.assert_called_once_with(
        "sess-abc123",
        "More detail please",
    )


@pytest.mark.asyncio
async def test_stream_edit_session_yield_events(client, app):
    q = EditEventQueue()
    await _preload(q)
    app.state.wiki_edit_service.get_event_queue = MagicMock(return_value=q)

    with client.stream(
        "GET",
        "/api/v1/wiki/pages/page-1/edit-session/sess-abc123/stream",
    ) as resp:
        assert resp.status_code == 200
        body = resp.read().decode()

    assert '"type"' in body
    assert '"content"' in body or "content" in body


async def _preload(q: EditEventQueue) -> None:
    await q.put(ContentEvent(text="x"))
    await q.put(DoneEvent(result="x"))


def test_stream_edit_session_missing_queue_404(client, app):
    app.state.wiki_edit_service.get_event_queue = MagicMock(return_value=None)

    resp = client.get("/api/v1/wiki/pages/page-1/edit-session/sess-xyz/stream")

    assert resp.status_code == 404


class TestSSETimeout:
    """Issue #4: idle timeout is sliding from the last received event."""

    @pytest.mark.asyncio
    async def test_yield_keepalive_while_waiting_for_slow_queue_event(self, monkeypatch):
        import api.routes.wiki_edit_routes as wr

        monkeypatch.setattr(wr, "_SSE_WAIT_CAP_SEC", 0.03)
        monkeypatch.setattr(wr, "_SSE_IDLE_TIMEOUT_SEC", 2.0)

        q = EditEventQueue()

        async def late_done() -> None:
            await asyncio.sleep(0.12)
            await q.put(DoneEvent(result="ok"))

        bg = asyncio.create_task(late_done())
        chunks: list[bytes] = []
        try:
            async for c in wr._iter_edit_session_sse(q):
                chunks.append(c)
        finally:
            await bg

        merged = b"".join(chunks)
        assert b": keepalive" in merged
        assert b"done" in merged

    @pytest.mark.asyncio
    async def test_sliding_idle_between_events_keeps_deadline_alive(self, monkeypatch):
        """Controlled monotonic sequences show long gaps vs last event remain under idle cap."""

        import api.routes.wiki_edit_routes as wr

        monkeypatch.setattr(wr, "_SSE_IDLE_TIMEOUT_SEC", 60.0)

        mono_vals = chain([50.0, 50.0, 115.0, 170.0], repeat(200.0))

        def mono() -> float:
            return next(mono_vals)

        async def immediate_wait_for(aw, timeout=None):  # type: ignore[no-untyped-def]
            del timeout
            return await aw

        monkeypatch.setattr(wr.time, "monotonic", mono)
        monkeypatch.setattr(wr.asyncio, "wait_for", immediate_wait_for)

        q = EditEventQueue()
        await q.put(ContentEvent(text="a"))
        await q.put(DoneEvent(result="a"))

        payloads: list[dict] = []
        async for chunk in wr._iter_edit_session_sse(q):
            for line in chunk.decode().splitlines():
                ln = line.strip()
                if ln.startswith("data: "):
                    payloads.append(json.loads(ln.removeprefix("data: ")))

        assert any(p.get("type") == "done" for p in payloads)


class TestEditRouteSecurityAndRateLimit:
    def test_viewer_token_receives_403_when_auth_enforced(self, app, monkeypatch):
        import core.auth as auth_mod

        registry = {"viewer-only": TokenInfo(role=auth_mod.Role.VIEWER)}
        monkeypatch.setattr(auth_mod, "_get_registry", lambda: registry)

        client = TestClient(app)
        resp = client.post(
            "/api/v1/wiki/pages/p1/edit-session",
            json={"prompt": "Fix", "current_content": "# X"},
            headers={"Authorization": "Bearer viewer-only"},
        )
        assert resp.status_code == 403

    def test_editor_token_allowed_when_auth_enforced(self, app, monkeypatch):
        import core.auth as auth_mod

        registry = {"ed": TokenInfo(role=auth_mod.Role.EDITOR)}
        monkeypatch.setattr(auth_mod, "_get_registry", lambda: registry)

        client = TestClient(app)
        resp = client.post(
            "/api/v1/wiki/pages/p1/edit-session",
            json={"prompt": "Fix", "current_content": "# X"},
            headers={"Authorization": "Bearer ed"},
        )
        assert resp.status_code == 200

    def test_create_edit_session_extra_rate_limit(self, client, monkeypatch):
        import api.routes.wiki_edit_routes as edit_routes

        monkeypatch.setattr(edit_routes, "_EDIT_SESSION_BURST_LIMIT", 2)
        ok = 0
        last_code = None
        for _ in range(5):
            r = client.post(
                "/api/v1/wiki/pages/page-1/edit-session",
                json={"prompt": "x", "current_content": "# P"},
            )
            last_code = r.status_code
            if r.status_code == 200:
                ok += 1
        assert ok == 2
        assert last_code == 429
