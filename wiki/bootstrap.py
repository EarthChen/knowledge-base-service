"""Wiki HTTP + MCP: attach services to ``app.state`` and release resources on shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from config import Settings
from log import get_logger
from store.graph_queries import GraphQueryRepository

log = get_logger(__name__)


def _get_wiki_generation_sem(state: Any) -> asyncio.Semaphore:
    """Match ``api.routes.wiki_shared.get_wiki_generation_sem`` (one semaphore per app)."""
    try:
        return state["wiki_generation_sem"]
    except (KeyError, TypeError):
        sem = asyncio.Semaphore(5)
        state["wiki_generation_sem"] = sem
        return sem


def _wiki_scope_for_page(path: str | None, page_type: str | None) -> str:
    """Map persisted WikiPage fields to ``parse_scope`` string for ``WikiService.generate``."""
    if not path:
        return "repo"
    pt = (page_type or "").strip().lower()
    if pt == "repo_overview":
        return "repo"
    if pt == "class_detail":
        return f"class:{path}"
    return f"module:{path}"


async def _run_feedback_wiki_regen(
    app_state: Any,
    page_uid: str,
    priority: str,
    token_multiplier: float,
) -> None:
    from wiki.service import WikiRepoNotFoundError, WikiService
    from wiki.structure_planner import WikiScopeError

    factory = getattr(app_state, "wiki_service_factory", None)
    if not callable(factory):
        log.warning("feedback_regen_no_service", page_uid=page_uid)
        return

    store = getattr(app_state, "wiki_store", None)
    if store is None or not hasattr(store, "execute_query"):
        log.warning("feedback_regen_no_store", page_uid=page_uid)
        return

    q = (
        "MATCH (wp:WikiPage) WHERE wp.uid = $uid "
        "RETURN wp.repository AS repository, wp.path AS path, wp.page_type AS page_type "
        "LIMIT 1"
    )
    r = await store.execute_query(q, {"uid": page_uid})
    rows = getattr(r, "data", []) or []
    repository: str | None = None
    path: str | None = None
    page_type: str | None = None
    if rows and isinstance(rows[0], dict):
        repository = rows[0].get("repository")
        path = rows[0].get("path")
        page_type = rows[0].get("page_type")
    if not repository and page_uid.startswith("WikiPage:"):
        rest = page_uid[len("WikiPage:") :]
        parts = rest.split(":", 1)
        if len(parts) == 2:
            repository, path = parts[0], parts[1] or path

    if not repository:
        log.warning("feedback_regen_no_repository", page_uid=page_uid)
        return

    scope = _wiki_scope_for_page(
        str(path) if path is not None else None,
        str(page_type) if page_type is not None else None,
    )
    out = factory()
    service: WikiService = await out if asyncio.iscoroutine(out) else out
    sem = _get_wiki_generation_sem(app_state)

    log.info(
        "feedback_regen_start",
        page_uid=page_uid,
        repository=repository,
        scope=scope,
        priority=priority,
        token_multiplier=token_multiplier,
    )
    try:
        async with sem:
            await service.generate(
                repository,
                scope,
                "structure",
                "json",
                language="en",
                token_budget_multiplier=token_multiplier,
            )
    except WikiScopeError:
        log.info(
            "feedback_regen_scope_fallback_repo",
            page_uid=page_uid,
            original_scope=scope,
        )
        async with sem:
            await service.generate(
                repository,
                "repo",
                "structure",
                "json",
                language="en",
                token_budget_multiplier=token_multiplier,
            )
    except WikiRepoNotFoundError as exc:
        log.warning(
            "feedback_regen_repo_missing",
            page_uid=page_uid,
            repository=exc.repository,
        )


def _make_enqueue_regenerate(
    app_state: Any,
) -> Callable[[str, str, float], Awaitable[None]]:
    async def enqueue_regenerate(
        page_uid: str, priority: str, token_multiplier: float
    ) -> None:
        async def _task() -> None:
            try:
                await _run_feedback_wiki_regen(
                    app_state, page_uid, priority, token_multiplier
                )
            except Exception:  # noqa: BLE001 — background: never let task die silently
                log.warning("feedback_regen_background_failed", page_uid=page_uid, exc_info=True)

        asyncio.create_task(_task())

    return enqueue_regenerate


async def bootstrap_wiki(app: FastAPI, settings: Settings) -> None:
    """Initialize all wiki services and attach to app.state (HTTP wiki + MCP)."""
    registry = getattr(app.state, "registry", None)
    if registry is None:
        raise RuntimeError("bootstrap_wiki requires app.state.registry to be set first")

    from llm.base_provider import GatewayLLMProviderAdapter, LLMPortBridge
    from store.conversation_store import SqliteConversationStore
    from store.wiki_store import WikiStore as _WikiStoreForMemory
    from wiki.ask import WikiAskService
    from wiki.memory_loop import MemoryLoop
    from wiki.search import WikiSearchService
    from wiki.service import WikiService

    conv_dir = Path(settings.git.clone_base_path).resolve().parent
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_store_path = str(conv_dir / "conversations.db")
    conv_store = SqliteConversationStore(db_path=conv_store_path)
    await conv_store.initialize()
    app.state.conversation_store = conv_store

    kb = await registry.get_service("default")
    app.state.wiki_store = kb.store

    from store.wiki_feedback_store import WikiFeedbackStore

    app.state.wiki_feedback_store = WikiFeedbackStore(kb.store)

    from wiki.event_bus import WikiEventBus

    app.state.wiki_event_bus = WikiEventBus()

    from wiki.task_store import WikiTaskStore

    wiki_task_store: WikiTaskStore | None = None
    try:
        redis_conn = getattr(kb.store, "_redis", None) or getattr(kb.store, "redis", None)
        if redis_conn is None and hasattr(kb.store, "_graph"):
            redis_conn = getattr(kb.store._graph, "_redis", None)
        if redis_conn is None and hasattr(kb.store, "_db"):
            sync_conn = getattr(kb.store._db, "connection", None)
            if sync_conn is not None:
                import redis.asyncio as aioredis

                conn_kwargs = sync_conn.connection_pool.connection_kwargs.copy()
                host = conn_kwargs.get("host", "localhost")
                port = conn_kwargs.get("port", 6379)
                password = conn_kwargs.get("password")
                db_num = conn_kwargs.get("db", 0)
                redis_conn = aioredis.Redis(
                    host=host, port=port, password=password, db=db_num,
                    decode_responses=False,
                )
                log.info("wiki_task_store_redis_from_sync", host=host, port=port)
        if redis_conn is not None:
            wiki_task_store = WikiTaskStore(redis_conn)
            log.info("wiki_task_store_initialized", backend="redis")
        else:
            log.warning("wiki_task_store_no_redis", fallback="in-memory")
    except Exception:
        log.warning("wiki_task_store_init_failed", exc_info=True)
    app.state.wiki_task_store = wiki_task_store

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

    wiki_mem: MemoryLoop | None = None
    if getattr(kb, "_embedding", None) is not None:

        async def _embed_wiki_mem(text: str) -> list[float]:
            out = await kb._embedding.generate([text], is_query=False)  # type: ignore[union-attr]
            return out[0] if out else []

        wiki_mem = MemoryLoop(
            _WikiStoreForMemory(kb.store),
            _embed_wiki_mem,
            business_id="default",
            memory_tiers_enabled=settings.wiki.memory_tiers_enabled,
        )
    app.state.wiki_memory_loop = wiki_mem

    async def wiki_service_factory() -> WikiService:
        kb_svc = await registry.get_service("default")
        from store.wiki_store import WikiStore as _WikiStore

        community_service = None
        if settings.wiki.community_context_enabled:
            try:
                from query.community_detection import CommunityDetector
                from wiki.community_context import CachedCommunityService

                community_service = CachedCommunityService(
                    kb_svc.store,
                    CommunityDetector(kb_svc.store),
                )
            except Exception:  # noqa: BLE001 — optional wiring
                log.warning("community_context_service_unavailable", exc_info=True)

        return WikiService(
            graph=kb_svc.store,
            llm=_wrap_llm(kb_svc.llm_provider),
            repository_exists=repository_exists,
            store=kb_svc.store,
            deferred_enrichment=kb_svc.wiki_deferred_enrichment,
            flow_inferencer=kb_svc.wiki_flow_inferencer,
            wiki_store=_WikiStore(kb_svc.store),
            memory_loop=wiki_mem,
            community_service=community_service,
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

    from wiki.deep_research import DeepResearchService

    app.state.wiki_deep_research_service = DeepResearchService(
        ask_service=app.state.wiki_ask_service,
        llm=_wrap_llm(kb.llm_provider) if kb.llm_provider else None,
    )

    app.state.graph_query_service = kb.graph_query

    _get_wiki_generation_sem(app.state)
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    app.state.wiki_feedback_regen = FeedbackDrivenRegeneration(
        graph=kb.store,
        wiki_config=settings.wiki,
        enqueue_regenerate=_make_enqueue_regenerate(app.state),
    )

    if settings.wiki.mcp_server_enabled:
        from api.mcp_wiki_server import MCPWikiServer

        mcp_server = MCPWikiServer(
            search_service=wiki_search,
            wiki_store=app.state.wiki_store,
            ask_service=app.state.wiki_ask_service,
            change_detector=getattr(app.state, "change_detector", None),
        )
        app.state.mcp_wiki_server = mcp_server


async def teardown_wiki(app: FastAPI) -> None:
    """Graceful cleanup of wiki resources (e.g. conversation store)."""
    bus = getattr(app.state, "wiki_event_bus", None)
    if bus:
        await bus.shutdown()
    conv_store = getattr(app.state, "conversation_store", None)
    if conv_store is not None:
        await conv_store.close()
        app.state.conversation_store = None
