"""Transition shim — delegates to AppContainer for backward compatibility.

During migration, background tasks and route handlers access services via this module.
After migration is complete, all call sites should use AppContainer directly.

Semaphore note: this module defines module-level ``reindex_sem`` and ``index_sem``,
while :class:`core.container.AppContainer` also owns its own instances of the same
limits. They are not the same objects, so concurrency can diverge from the container
config until call sites are migrated. New code should acquire semaphores from
``AppContainer`` (or a service that receives the container) rather than importing
these module-level semaphores.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.container import AppContainer
    from indexer.task_manager import IndexTaskManager
    from services.repo_registry import RepoRegistry
    from services.scheduler import SyncScheduler
    from services.service_registry import ServiceRegistry

MAX_CONCURRENT_REINDEX = 1
reindex_sem = asyncio.Semaphore(MAX_CONCURRENT_REINDEX)
MAX_CONCURRENT_INDEX = 2
index_sem = asyncio.Semaphore(MAX_CONCURRENT_INDEX)

_container: AppContainer | None = None

# Backward-compatible module-level attributes
registry: ServiceRegistry | None = None
task_manager: IndexTaskManager | None = None
repo_registry: RepoRegistry | None = None
scheduler: SyncScheduler | None = None


def _bind(container: AppContainer) -> None:
    """Called by main.lifespan to sync module globals with the container."""
    global _container, registry, task_manager, repo_registry, scheduler
    _container = container
    registry = container.registry
    task_manager = container.task_manager
    repo_registry = container.repo_registry
    scheduler = container.scheduler
