from __future__ import annotations

from fastapi import FastAPI

from api.routes.webhook_routes import init_webhook_state
from core.config import get_settings
from core.container import AppContainer
from core.log import get_logger
from wiki.bootstrap import bootstrap_wiki

log = get_logger(__name__)


async def init_wiki_and_lint(container: AppContainer, app: FastAPI) -> None:
    """Initialize wiki subsystem and lint scheduler."""
    init_webhook_state(app)

    from wiki.cache import WikiCache
    from wiki.lint import WikiLintService

    if getattr(app.state, "wiki_cache", None) is None:
        app.state.wiki_cache = WikiCache()

    async def wiki_lint_service_factory() -> WikiLintService:
        kb = await container.registry.get_service("default")
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
                    {"title": title, "content": content[:3000], "section": "", "heading_context": ""},
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
            repo_registry=container.repo_registry,
            wiki_config=settings.wiki,
            contradiction_detector=det,
            wiki_changelog_store=getattr(app.state, "wiki_changelog_store", None),
        )

    app.state.wiki_lint_service_factory = wiki_lint_service_factory

    await bootstrap_wiki(app, container.settings)

    app.state.wiki_lint_scheduler = None
    if container.settings.wiki.lint_scheduler_enabled:
        from wiki.lint_scheduler import LintScheduler

        def _list_repos() -> list[str]:
            reg = container.repo_registry
            if reg is None:
                return []
            return [str(e["repository"]) for e in reg.list_all() if e.get("repository")]

        interval = float(max(1, container.settings.wiki.lint_scheduler_interval_hours) * 3600)
        lint_sched = LintScheduler(
            app.state.wiki_lint_service_factory,
            repositories=_list_repos,
            interval_seconds=interval,
            supervisor=container.task_supervisor,
        )
        lint_sched.start()
        app.state.wiki_lint_scheduler = lint_sched
        log.info(
            "wiki_lint_scheduler_started",
            interval_hours=container.settings.wiki.lint_scheduler_interval_hours,
        )
