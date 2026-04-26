"""Knowledge Base Service — standalone FastAPI application.

Provides HTTP endpoints for code/document indexing and querying,
backed by FalkorDB graph database and sentence-transformers embeddings.
Supports multi-business isolation via independent FalkorDB graphs.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import api.kb_state as kb_state
from api.error_handler import register_exception_handlers
from api.middleware.request_logging import RequestLoggingMiddleware
from api.rate_limiter import install_rate_limiter
# Import route modules for side effects (registers handlers on shared routers)
import api.routes.admin_graph_mcp_routes  # noqa: F401
import api.routes.business_sync_routes  # noqa: F401
import api.routes.indexing_routes  # noqa: F401
import api.routes.public_health_routes  # noqa: F401
import api.routes.repository_routes  # noqa: F401
import api.routes.search_routes  # noqa: F401
from api.routes.kb_routers import admin_router, editor_router, public_router, viewer_router
from api.routes.kb_schemas import HybridSearchRequest
from api.routes.provider_routes import provider_router
from api.routes.repository_path_utils import _build_file_tree
from api.routes.settings_routes import settings_router
from api.routes.webhook_routes import init_webhook_state, webhook_router
from api.routes.wiki_routes import mcp_wiki_http_router, wiki_router
from auth import get_auth_mode
from config import Settings, get_settings
from indexer.task_manager import IndexTaskManager
from log import get_logger, setup_logging
from repo_registry import RepoRegistry
from scheduler import SyncScheduler
from service_registry import ServiceRegistry
from wiki.bootstrap import bootstrap_wiki, teardown_wiki

# Backward-compatible names for tests and external imports
from api.routes.kb_dependencies import get_service as _get_service

log = get_logger(__name__)


def _startup_auth_gate(settings: Settings) -> None:
    """Log when no tokens are configured; optionally fail startup if ``require_auth``."""
    if get_auth_mode() == "open":
        log.warning(
            "no_api_tokens_configured",
            detail=(
                "No API tokens configured — all endpoints are accessible without authentication. "
                "Set API_TOKEN, API_TOKENS, or TOKENS_FILE for production deployments."
            ),
        )
        if settings.require_auth:
            raise RuntimeError(
                "require_auth is enabled but no API tokens are configured. "
                "Set API_TOKEN, API_TOKENS, or TOKENS_FILE before starting the service.",
            )


def _enforce_production_security(settings: Settings) -> None:
    """Fail-closed in production: require authentication."""
    env = os.environ.get("KB_ENV", "development").lower()
    if env != "production":
        return
    if not settings.require_auth:
        log.critical(
            "production_require_auth_disabled",
            detail="KB_ENV=production but require_auth is false; refusing to start.",
        )
        raise RuntimeError(
            "KB_ENV=production requires require_auth=true. "
            "Set REQUIRE_AUTH=true and configure API tokens.",
        )
    if not settings.api_token and not settings.api_tokens and not Path(settings.tokens_file).exists():
        log.critical(
            "production_no_api_tokens",
            detail="KB_ENV=production but no API tokens configured; refusing to start.",
        )
        raise RuntimeError(
            "KB_ENV=production requires at least one API token. "
            "Set API_TOKEN, API_TOKENS, or create tokens.yaml.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(level=settings.log_level)
    log.info("kb_service_starting", host=settings.host, port=settings.port)

    _enforce_production_security(settings)
    _startup_auth_gate(settings)

    kb_state.task_manager = IndexTaskManager()

    def _index_task_status_for_mcp(task_id: str) -> dict[str, Any] | None:
        if kb_state.task_manager is None:
            return None
        task = kb_state.task_manager.get_task(task_id)
        return task.to_dict() if task else None

    data_dir = Path(settings.git.clone_base_path).resolve().parent
    kb_state.repo_registry = RepoRegistry(str(data_dir))
    kb_state.registry = ServiceRegistry(
        settings,
        index_task_status_lookup=_index_task_status_for_mcp,
        repo_registry=kb_state.repo_registry,
    )
    await kb_state.registry.start()

    kb_state.scheduler = SyncScheduler(
        kb_state.registry,
        settings,
        repo_registry=kb_state.repo_registry,
        schedule_store_path=data_dir / "sync_schedules.json",
    )
    await kb_state.scheduler.start()

    app.state.registry = kb_state.registry
    app.state.scheduler = kb_state.scheduler
    init_webhook_state(app)

    from wiki.cache import WikiCache
    from wiki.lint import WikiLintService

    if getattr(app.state, "wiki_cache", None) is None:
        app.state.wiki_cache = WikiCache()

    async def wiki_lint_service_factory() -> WikiLintService:
        kb = await kb_state.registry.get_service("default")
        settings = get_settings()
        det = None
        if settings.wiki.contradiction_detection_enabled and kb.llm_provider is not None:
            from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
            from llm.base_provider import GatewayLLMProviderAdapter, LLMPortBridge
            from wiki.contradiction_detector import ContradictionDetector

            emb = EmbeddingGenerator.shared(config=settings.embedding)
            sim_threshold = settings.wiki.contradiction_similarity_threshold

            async def _embed_wiki_text(title: str, content: str) -> list[float]:
                item = doc_dict_for_embedding(
                    {
                        "title": title,
                        "content": content[:3000],
                        "section": "",
                        "heading_context": "",
                    },
                )
                out = await emb.generate_for_docs([item])
                return out[0] if out else []

            raw_llm = kb.llm_provider
            llm = (
                raw_llm
                if hasattr(raw_llm, "generate")
                else LLMPortBridge(GatewayLLMProviderAdapter(raw_llm))  # type: ignore[arg-type]
            )
            det = ContradictionDetector(
                graph=kb.store,
                embedding_fn=_embed_wiki_text,
                llm=llm,  # type: ignore[arg-type]
                similarity_threshold=sim_threshold,
            )
        return WikiLintService(
            kb.store,
            wiki_cache=getattr(app.state, "wiki_cache", None),
            repo_registry=kb_state.repo_registry,
            wiki_config=settings.wiki,
            contradiction_detector=det,
        )

    app.state.wiki_lint_service_factory = wiki_lint_service_factory

    await bootstrap_wiki(app, settings)

    log.info("kb_service_started")
    yield

    log.info("kb_service_stopping")
    await teardown_wiki(app)
    if kb_state.scheduler:
        await kb_state.scheduler.stop()
    if kb_state.registry:
        await kb_state.registry.stop()
    log.info("kb_service_stopped")


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

_SPA_ROUTES = {
    "search",
    "deep-search",
    "graph",
    "explorer",
    "repositories",
    "indexing",
    "settings",
    "businesses",
    "documents",
    "sync",
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Knowledge Base Service",
        description="Code knowledge base with graph + vector search",
        version="0.1.0",
        lifespan=lifespan,
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

    if _STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="static-assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:
            file_path = _STATIC_DIR / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(_INDEX_HTML)

    return app


app = create_app()
