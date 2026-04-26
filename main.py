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
from store.graph_queries import GraphQueryRepository

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


async def wire_wiki_app_state(app: FastAPI, registry: ServiceRegistry) -> None:
    """Expose wiki HTTP route dependencies on ``app.state`` (default business graph)."""
    from llm.base_provider import GatewayLLMProviderAdapter, LLMPortBridge
    from store.conversation_store import SqliteConversationStore
    from store.wiki_store import WikiStore as _WikiStoreForMemory
    from wiki.ask import WikiAskService
    from wiki.memory_loop import MemoryLoop
    from wiki.search import WikiSearchService
    from wiki.service import WikiService

    settings = get_settings()
    conv_dir = Path(settings.git.clone_base_path).resolve().parent
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_store_path = str(conv_dir / "conversations.db")
    conv_store = SqliteConversationStore(db_path=conv_store_path)
    await conv_store.initialize()
    app.state.conversation_store = conv_store

    kb = await registry.get_service("default")
    app.state.wiki_store = kb.store

    async def repository_exists(repo: str) -> bool:
        kb_inner = await registry.get_service("default")
        queries = GraphQueryRepository(kb_inner.store)
        return await queries.get_repository_node_count(repo) > 0

    def _wrap_llm(raw_llm: object) -> object | None:
        if raw_llm is None:
            return None
        if hasattr(raw_llm, "generate"):
            return raw_llm
        return LLMPortBridge(GatewayLLMProviderAdapter(raw_llm))  # type: ignore[arg-type]

    async def wiki_service_factory() -> WikiService:
        kb_svc = await registry.get_service("default")
        from store.wiki_store import WikiStore as _WikiStore

        return WikiService(
            graph=kb_svc.store,
            llm=_wrap_llm(kb_svc.llm_provider),
            repository_exists=repository_exists,
            store=kb_svc.store,
            deferred_enrichment=kb_svc.wiki_deferred_enrichment,
            flow_inferencer=kb_svc.wiki_flow_inferencer,
            wiki_store=_WikiStore(kb_svc.store),
            wiki_config=settings.wiki,
            embedding_config=settings.embedding,
        )

    app.state.wiki_service_factory = wiki_service_factory

    from store.wiki_changelog import WikiChangeLogStore
    from wiki.change_detector import ChangeDetector

    app.state.change_detector = ChangeDetector(kb.store)
    app.state.wiki_changelog_store = WikiChangeLogStore(kb.store)

    wiki_search = WikiSearchService(
        graph=kb.store,
        vector=kb.semantic_query,
        fts=kb.store,
        embedding_gen=kb._embedding,
    )
    app.state.wiki_search_service = wiki_search

    wiki_mem: MemoryLoop | None = None
    if getattr(kb, "_embedding", None) is not None:

        async def _embed_wiki_mem(text: str) -> list[float]:
            out = await kb._embedding.generate([text], is_query=False)  # type: ignore[union-attr]
            return out[0] if out else []

        wiki_mem = MemoryLoop(
            _WikiStoreForMemory(kb.store), _embed_wiki_mem, business_id="default",
        )
    app.state.wiki_memory_loop = wiki_mem

    if kb.llm_provider is not None:
        app.state.wiki_ask_service = WikiAskService(
            search=wiki_search,
            llm=_wrap_llm(kb.llm_provider),
            graph=kb.store,
            memory_loop=wiki_mem,
            conversation_store=conv_store,
        )
    else:
        app.state.wiki_ask_service = None

    app.state.graph_query_service = kb.graph_query

    if settings.wiki.mcp_server_enabled:
        from api.mcp_wiki_server import MCPWikiServer

        mcp_server = MCPWikiServer(
            search_service=wiki_search,
            wiki_store=app.state.wiki_store,
            ask_service=app.state.wiki_ask_service,
            change_detector=getattr(app.state, "change_detector", None),
        )
        app.state.mcp_wiki_server = mcp_server


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
        return WikiLintService(
            kb.store,
            wiki_cache=getattr(app.state, "wiki_cache", None),
            repo_registry=kb_state.repo_registry,
        )

    app.state.wiki_lint_service_factory = wiki_lint_service_factory

    await wire_wiki_app_state(app, kb_state.registry)

    log.info("kb_service_started")
    yield

    log.info("kb_service_stopping")
    conv_store = getattr(app.state, "conversation_store", None)
    if conv_store is not None:
        await conv_store.close()
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
