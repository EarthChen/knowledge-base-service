"""Tests for raw_cypher security helpers and execution guards."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.mcp_server import KnowledgeBaseMCPHandler
from core.auth import Role, TokenInfo
from query.raw_cypher import (
    RAW_CYPHER_DEFAULT_LIMIT,
    check_raw_cypher_admin,
    ensure_raw_cypher_limit,
    validate_raw_cypher_read_only,
)
from query.raw_cypher import RawCypherValidationError


def test_ensure_raw_cypher_limit_appends_when_missing() -> None:
    assert ensure_raw_cypher_limit("MATCH (n) RETURN n") == (
        f"MATCH (n) RETURN n LIMIT {RAW_CYPHER_DEFAULT_LIMIT}"
    )


def test_ensure_raw_cypher_limit_preserves_existing() -> None:
    q = "MATCH (n) RETURN n LIMIT 5"
    assert ensure_raw_cypher_limit(q) == q


def test_validate_raw_cypher_read_only_rejects_create() -> None:
    with pytest.raises(RawCypherValidationError):
        validate_raw_cypher_read_only("CREATE (n:Node)")


def test_check_raw_cypher_admin_denies_viewer_when_tokens_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.auth as auth

    monkeypatch.setattr(
        auth,
        "_token_registry",
        {"v": TokenInfo(role=Role.VIEWER), "a": TokenInfo(role=Role.ADMIN)},
    )
    assert check_raw_cypher_admin(TokenInfo(role=Role.VIEWER)) is not None
    assert check_raw_cypher_admin(TokenInfo(role=Role.ADMIN)) is None


def test_check_raw_cypher_admin_denies_missing_token_when_tokens_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.auth as auth

    monkeypatch.setattr(
        auth,
        "_token_registry",
        {"a": TokenInfo(role=Role.ADMIN)},
    )
    assert check_raw_cypher_admin(None) is not None


def test_check_raw_cypher_admin_allows_open_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.auth as auth

    monkeypatch.setattr(auth, "_token_registry", {})
    assert check_raw_cypher_admin(None) is None


@pytest.mark.asyncio
async def test_handle_tool_call_raw_cypher_requires_admin_when_authed() -> None:
    h = KnowledgeBaseMCPHandler(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        doc_indexer=None,
        store=MagicMock(),
        embedding_gen=None,
        wiki_handler=None,
    )
    fake_settings = MagicMock()
    fake_settings.require_auth = True
    viewer = TokenInfo(role=Role.VIEWER)
    with patch("api.mcp_server.get_settings", return_value=fake_settings):
        out = await h.handle_tool_call(
            "rag_graph",
            {"query_type": "raw_cypher", "cypher": "MATCH (n) RETURN n"},
            token_info=viewer,
        )
    assert out["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_execute_raw_applies_limit_before_query() -> None:
    from query.graph_query import GraphQueryService

    from store.falkordb_common import QueryResultWrapper

    store = MagicMock()
    store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    svc = GraphQueryService(store)
    await svc.execute_raw("MATCH (n) RETURN n")
    called_cypher = store.execute_query.await_args.args[0]
    assert called_cypher.endswith(f"LIMIT {RAW_CYPHER_DEFAULT_LIMIT}")
