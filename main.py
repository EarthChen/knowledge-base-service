"""Knowledge Base Service — standalone FastAPI application.

Provides HTTP endpoints for code/document indexing and querying,
backed by FalkorDB graph database and sentence-transformers embeddings.
Supports multi-business isolation via independent FalkorDB graphs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.container import AppContainer

import api.kb_state as kb_state
from api.error_handler import register_exception_handlers
from api.middleware.request_logging import RequestLoggingMiddleware
from api.rate_limiter import install_rate_limiter
# Import route modules for side effects (registers handlers on shared routers)
import api.routes.admin_graph_mcp_routes  # noqa: F401
import api.routes.business_sync_routes  # noqa: F401
from api.routes.business_routes import router as business_router
import api.routes.indexing_routes  # noqa: F401
import api.routes.public_health_routes  # noqa: F401
import api.routes.repository_routes  # noqa: F401
import api.routes.search_routes  # noqa: F401
from api.routes.kb_routers import admin_router, editor_router, public_router, viewer_router
from api.routes.kb_schemas import HybridSearchRequest
from api.routes.provider_routes import provider_router
from api.routes.repository_path_utils import _build_file_tree
from api.routes.settings_routes import settings_router
from api.routes.webhook_routes import webhook_router
from api.routes.wiki_routes import mcp_wiki_http_router, wiki_router
from core.config import get_settings
from core.log import get_logger, setup_logging
from core.startup import init_security, init_core_services, init_wiki_and_lint, shutdown_all

# Backward-compatible names for tests and external imports
from api.routes.kb_dependencies import get_service as _get_service

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(level=settings.log_level)
    log.info("kb_service_starting", host=settings.host, port=settings.port)

    init_security(settings)

    container = AppContainer(
        settings=settings,
        registry=None,
        task_manager=None,
        repo_registry=None,
        scheduler=None,
        settings_store=None,
    )

    await init_core_services(container, app)
    kb_state._bind(container)
    app.state.container = container

    await init_wiki_and_lint(container, app)

    log.info("kb_service_started")
    yield

    log.info("kb_service_stopping")
    await shutdown_all(container, app)
    log.info("kb_service_stopped")


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR_RESOLVED = _STATIC_DIR.resolve()
_INDEX_HTML = _STATIC_DIR / "index.html"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Knowledge Base Service",
        description="Code knowledge base with graph + vector search",
        version="0.1.0",
        lifespan=lifespan,
    )
    if settings.cors_origins:
        from starlette.middleware.cors import CORSMiddleware

        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    install_rate_limiter(app)
    app.include_router(public_router)
    app.include_router(webhook_router)
    app.include_router(provider_router)
    app.include_router(wiki_router)
    app.include_router(mcp_wiki_http_router)
    app.include_router(viewer_router)
    app.include_router(editor_router)
    app.include_router(admin_router)
    app.include_router(settings_router)
    app.include_router(business_router)

    if _STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="static-assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:
            file_path = (_STATIC_DIR / full_path).resolve()
            if (
                full_path
                and file_path.is_file()
                and file_path.is_relative_to(_STATIC_DIR_RESOLVED)
            ):
                return FileResponse(file_path)
            return FileResponse(_INDEX_HTML)

    return app


app = create_app()
