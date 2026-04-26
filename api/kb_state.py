"""Process-wide service instances for the Knowledge Base HTTP API (set from ``main`` lifespan)."""

from __future__ import annotations

import asyncio

from indexer.task_manager import IndexTaskManager
from services.repo_registry import RepoRegistry
from services.scheduler import SyncScheduler
from services.service_registry import ServiceRegistry

# Populated in main.lifespan; read by API dependencies and background tasks.
MAX_CONCURRENT_REINDEX = 1
reindex_sem = asyncio.Semaphore(MAX_CONCURRENT_REINDEX)
MAX_CONCURRENT_INDEX = 2
index_sem = asyncio.Semaphore(MAX_CONCURRENT_INDEX)

registry: ServiceRegistry | None = None
task_manager: IndexTaskManager | None = None
repo_registry: RepoRegistry | None = None
scheduler: SyncScheduler | None = None
