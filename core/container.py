"""Application service container — replaces module-level globals in api/kb_state.py."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from core.config import Settings
from core.task_supervisor import TaskSupervisor
from indexer.task_manager import IndexTaskManager
from services.repo_registry import RepoRegistry
from services.scheduler import SyncScheduler
from services.service_registry import ServiceRegistry
from store.settings_store import SettingsStore


@dataclass
class AppContainer:
    """Holds every long-lived service instance for the application."""

    # Core (populated by _init_core_services)
    settings: Settings
    registry: ServiceRegistry | None = None
    task_manager: IndexTaskManager | None = None
    repo_registry: RepoRegistry | None = None
    scheduler: SyncScheduler | None = None
    settings_store: SettingsStore | None = None
    reindex_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    index_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    task_supervisor: TaskSupervisor = field(default_factory=TaskSupervisor)

    # Wiki subsystem (populated by bootstrap_wiki)
    wiki_store: Any = None
    wiki_service_factory: Any = None
    wiki_search_service: Any = None
    wiki_ask_service: Any = None
    wiki_event_bus: Any = None
    wiki_task_store: Any = None
    wiki_feedback_store: Any = None
    wiki_feedback_regen: Any = None
    wiki_cache: Any = None
    wiki_lint_service_factory: Any = None
    wiki_lint_scheduler: Any = None
    graph_query_service: Any = None
    conversation_store: Any = None
    change_detector: Any = None
    wiki_changelog_store: Any = None
    wiki_memory_loop: Any = None
    wiki_deep_research_service: Any = None
    mcp_wiki_server: Any = None

    @classmethod
    def create_test(cls, **overrides: Any) -> AppContainer:
        """Factory for tests — all fields mocked unless overridden."""
        from unittest.mock import MagicMock

        defaults: dict[str, Any] = {
            "settings": MagicMock(spec=Settings),
            "registry": MagicMock(spec=ServiceRegistry),
            "task_manager": MagicMock(spec=IndexTaskManager),
            "repo_registry": MagicMock(spec=RepoRegistry),
            "scheduler": MagicMock(spec=SyncScheduler),
            "settings_store": MagicMock(spec=SettingsStore),
            "reindex_sem": asyncio.Semaphore(1),
            "index_sem": asyncio.Semaphore(2),
            "task_supervisor": TaskSupervisor(),
        }
        defaults.update(overrides)
        return cls(**defaults)
