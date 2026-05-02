"""Tests for wiki-related ``app.state`` wiring (HTTP wiki routes)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from config import get_settings
from wiki.bootstrap import bootstrap_wiki
from wiki.service import WikiService


@pytest.mark.asyncio
async def test_wire_wiki_app_state_sets_factory_and_services() -> None:
    app = FastAPI()
    mock_store = MagicMock()
    mock_semantic = MagicMock()
    mock_llm = MagicMock()
    mock_graph_query = MagicMock()

    kb = MagicMock()
    kb.store = mock_store
    kb.store._redis = None
    kb.store.redis = None
    kb.store._graph = None
    kb.store._db = None
    kb.semantic_query = mock_semantic
    kb._embedding = MagicMock()
    kb.llm_provider = mock_llm
    kb.graph_query = mock_graph_query

    registry = MagicMock()
    registry.get_service = AsyncMock(return_value=kb)
    app.state.registry = registry

    await bootstrap_wiki(app, get_settings())

    assert callable(app.state.wiki_service_factory)
    assert app.state.wiki_search_service is not None
    assert app.state.wiki_ask_service is not None
    assert app.state.graph_query_service is mock_graph_query
    assert app.state.wiki_store is mock_store

    wiki_svc = await app.state.wiki_service_factory()
    assert isinstance(wiki_svc, WikiService)


@pytest.mark.asyncio
async def test_wire_wiki_app_state_no_llm_skips_ask_service() -> None:
    app = FastAPI()
    kb = MagicMock()
    kb.store = MagicMock()
    kb.store._redis = None
    kb.store.redis = None
    kb.store._graph = None
    kb.store._db = None
    kb.semantic_query = MagicMock()
    kb._embedding = MagicMock()
    kb.llm_provider = None
    kb.graph_query = MagicMock()

    registry = MagicMock()
    registry.get_service = AsyncMock(return_value=kb)
    app.state.registry = registry

    await bootstrap_wiki(app, get_settings())

    assert app.state.wiki_ask_service is None
    assert app.state.wiki_search_service is not None
