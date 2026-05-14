from __future__ import annotations

from fastapi import FastAPI

from core.container import AppContainer
from core.startup.security import init_security
from core.startup.core_services import init_core_services
from core.startup.wiki import init_wiki_and_lint
from wiki.bootstrap import teardown_wiki

__all__ = ["init_security", "init_core_services", "init_wiki_and_lint", "shutdown_all"]


async def shutdown_all(container: AppContainer, app: FastAPI) -> None:
    """Reverse-order teardown."""
    await container.task_supervisor.shutdown(timeout=30.0)

    ls = getattr(app.state, "wiki_lint_scheduler", None)
    if ls is not None:
        await ls.stop()
        app.state.wiki_lint_scheduler = None
    await teardown_wiki(app)
    if container.scheduler:
        await container.scheduler.stop()
    if container.registry:
        await container.registry.stop()

    if container.sqlite_task_store is not None:
        await container.sqlite_task_store.close()
        container.sqlite_task_store = None

    event_bus = getattr(app.state, "wiki_event_bus", None)
    if event_bus is not None:
        await event_bus.shutdown()

    from store.falkordb_store import _graph_executor

    _graph_executor.shutdown(wait=True, cancel_futures=False)
