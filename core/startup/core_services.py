from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from core.container import AppContainer
from indexer.task_manager import IndexTaskManager
from services.repo_registry import RepoRegistry
from services.scheduler import SyncScheduler
from services.service_registry import ServiceRegistry
from store.falkordb_store import FalkorDBStore, QueryResultWrapper
from store.settings_store import SettingsStore
from store.task_store import SqliteTaskStore


class _AppGraphQuery:
    """Expose ``FalkorDBStore.execute_query`` as ``async graph.query`` for business routes."""

    __slots__ = ("_store",)

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResultWrapper:
        return await self._store.execute_query(cypher, params or {})


async def init_core_services(container: AppContainer, app: FastAPI) -> None:
    """Create and start registry, scheduler, task manager."""
    data_dir = Path(container.settings.git.clone_base_path).resolve().parent
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_task_store = SqliteTaskStore(db_path=str(data_dir / "wiki_tasks.db"))
    await sqlite_task_store.initialize()
    container.sqlite_task_store = sqlite_task_store
    container.task_manager = IndexTaskManager(task_store=sqlite_task_store)

    def _index_task_status_for_mcp(task_id: str) -> dict[str, Any] | None:
        if container.task_manager is None:
            return None
        task = container.task_manager.get_task(task_id)
        return task.to_dict() if task else None

    container.repo_registry = RepoRegistry(str(data_dir))
    container.settings_store = SettingsStore()
    app.state.settings_store = container.settings_store
    container.registry = ServiceRegistry(
        container.settings,
        index_task_status_lookup=_index_task_status_for_mcp,
        repo_registry=container.repo_registry,
        settings_store=container.settings_store,
    )
    await container.registry.start()

    _default_kb = await container.registry.get_service("default")
    app.state.graph = _AppGraphQuery(_default_kb.store)

    container.scheduler = SyncScheduler(
        container.registry,
        container.settings,
        repo_registry=container.repo_registry,
        schedule_store_path=data_dir / "sync_schedules.json",
        supervisor=container.task_supervisor,
    )
    await container.scheduler.start()

    # Mirror to app.state for route dependencies
    app.state.registry = container.registry
    app.state.scheduler = container.scheduler
