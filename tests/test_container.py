"""Tests for core.container — AppContainer dataclass."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from core.container import AppContainer


class TestAppContainer:
    def test_creation_settings_only_core_optional(self):
        container = AppContainer(settings=MagicMock())
        assert container.registry is None
        assert container.task_manager is None
        assert container.wiki_store is None

    def test_creation_with_core_services_populated(self):
        container = AppContainer(
            settings=MagicMock(),
            registry=MagicMock(),
            task_manager=MagicMock(),
            repo_registry=MagicMock(),
            scheduler=MagicMock(),
            settings_store=MagicMock(),
            reindex_sem=asyncio.Semaphore(1),
            index_sem=asyncio.Semaphore(2),
        )
        assert container.registry is not None
        assert container.wiki_store is None

    def test_wiki_fields_default_to_none(self):
        container = AppContainer(
            settings=MagicMock(),
            registry=MagicMock(),
            task_manager=MagicMock(),
            repo_registry=MagicMock(),
            scheduler=MagicMock(),
            settings_store=MagicMock(),
        )
        wiki_fields = [
            "wiki_store", "wiki_service_factory", "wiki_search_service",
            "wiki_ask_service", "wiki_event_bus", "wiki_task_store",
            "wiki_feedback_store", "wiki_feedback_regen", "wiki_cache",
            "graph_query_service", "conversation_store",
        ]
        for f in wiki_fields:
            assert getattr(container, f) is None, f"{f} should default to None"

    def test_create_test_factory(self):
        container = AppContainer.create_test()
        assert container.settings is not None
        assert container.registry is not None
        assert container.wiki_store is None

    def test_create_test_with_overrides(self):
        custom = MagicMock()
        container = AppContainer.create_test(wiki_store=custom)
        assert container.wiki_store is custom
