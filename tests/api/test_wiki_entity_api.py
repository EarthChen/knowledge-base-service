"""Tests for wiki page related code entities (SOURCE_ENTITY) API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import core.auth as auth_module

from api.models.wiki_entity import RelatedEntity, WikiPageEntitiesResponse


def test_related_entity_model():
    entity = RelatedEntity(
        uid="Function::PaymentService::processPayment:45",
        name="processPayment",
        entity_type="Function",
        repository="payment-service",
        file_path="src/main/java/PaymentService.java",
        start_line=45,
        signature="public void processPayment(Order order, PaymentMethod method)",
        business_summary="Process payment for an order",
    )
    assert entity.name == "processPayment"
    assert entity.entity_type == "Function"


def test_wiki_page_entities_response():
    resp = WikiPageEntitiesResponse(
        page_path="wiki/meeting",
        entities=[
            RelatedEntity(
                uid="u1",
                name="MeetingSvc",
                entity_type="Module",
                repository="r",
                file_path="f.java",
            ),
        ],
    )
    assert len(resp.entities) == 1


@pytest.mark.asyncio
async def test_get_related_entities_delegates_to_store():
    from store.wiki_page_store import WikiPageStoreMixin

    class _T(WikiPageStoreMixin):
        def __init__(self) -> None:
            self._store = MagicMock()

    t = _T()
    t._store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "uid": "e1",
                    "name": "foo",
                    "labels": ["Function"],
                    "file_path": "a.py",
                    "start_line": 1,
                    "signature": "def foo()",
                    "business_summary": "does foo",
                    "repository": "repo",
                },
            ]
        )
    )
    rows = await t.get_related_entities("wp1")
    assert len(rows) == 1
    assert rows[0]["name"] == "foo"
    t._store.execute_query.assert_awaited_once()
    call_kws = t._store.execute_query.await_args
    assert call_kws.args[1] == {"uid": "wp1"}


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def test_wiki_page_entities_endpoint(client: TestClient) -> None:
    """GET /api/v1/wiki/pages/{path}/entities resolves page and returns entity rows."""
    from main import app

    raw = MagicMock()

    async def execute_query(q: str, params: object = None) -> MagicMock:
        _ = params
        if "labels(e) AS labels" in q:
            return MagicMock(
                data=[
                    {
                        "uid": "mod-1",
                        "name": "MeetingSvc",
                        "labels": ["Module"],
                        "file_path": "svc/Meeting.java",
                        "start_line": 0,
                        "signature": "",
                        "business_summary": "Meetings",
                        "repository": "r",
                    },
                ]
            )
        return MagicMock(
            data=[
                {
                    "path": "wiki/meeting",
                    "title": "Meeting",
                    "content": "",
                    "page_type": "",
                    "importance_tier": "",
                    "repository": "r",
                    "uid": "page-uid-1",
                    "generated_at": "",
                    "confidence_score": None,
                    "quality_overall": None,
                    "sources": [],
                },
            ]
        )

    raw.execute_query = AsyncMock(side_effect=execute_query)
    app.state.wiki_store = raw

    r = client.get(
        "/api/v1/wiki/pages/wiki/meeting/entities",
        params={"business_id": "default"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["page_path"] == "wiki/meeting"
    assert len(body["entities"]) == 1
    assert body["entities"][0]["name"] == "MeetingSvc"
    assert body["entities"][0]["entity_type"] == "Module"
