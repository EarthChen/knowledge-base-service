"""Wiki HTTP + MCP: attach services to ``app.state`` and release resources on shutdown."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from config import Settings
from store.graph_queries import GraphQueryRepository


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

        return WikiService(
            graph=kb_svc.store,
            llm=_wrap_llm(kb_svc.llm_provider),
            repository_exists=repository_exists,
            store=kb_svc.store,
            deferred_enrichment=kb_svc.wiki_deferred_enrichment,
            flow_inferencer=kb_svc.wiki_flow_inferencer,
            wiki_store=_WikiStore(kb_svc.store),
            memory_loop=wiki_mem,
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
    conv_store = getattr(app.state, "conversation_store", None)
    if conv_store is not None:
        await conv_store.close()
        app.state.conversation_store = None
