"""FastAPI wiki router: aggregates sub-routers; re-exports for tests and callers."""

from __future__ import annotations

import time

from core.config import get_settings
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from store.graph_queries import GraphQueryRepository  # re-export: tests patch this on wiki_routes
from core.auth import Role, require_role
from api.routes.wiki_ask_routes import router as wiki_ask_router
from api.routes.wiki_contradiction_routes import router as wiki_contradiction_router
from api.routes.wiki_feedback_routes import router as wiki_feedback_router
from api.routes.wiki_mcp_routes import router as wiki_mcp_tools_router
from api.routes.wiki_page_routes import router as wiki_page_router
from api.routes.wiki_task_routes import router as wiki_task_router
from api.routes import wiki_shared
from query.semantic_wiki_query import SemanticWikiQuery, semantic_search_result_to_dict
from store.wiki_store import WikiStore
from wiki.quality_score import WikiQualityScorer
from wiki.task_registry import WIKI_TASK_TTL_SEC, WikiTaskRegistry
from api.models.wiki_entity import RelatedEntity, WikiPageEntitiesResponse
from api.models.wiki_models import (
    IngestRequest,
    WikiGenerateBody,
    WikiIncrementalGenerateBody,
    WikiQuickBody,
)

wiki_router = APIRouter(
    prefix="/api/v1/wiki",
    tags=["wiki"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)


class WikiSemanticSearchBody(BaseModel):
    """Body for ``POST /api/v1/wiki/semantic-search``."""

    query: str = Field(..., min_length=1)
    repository: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


@wiki_router.post("/semantic-search", response_model=None)
@wiki_router.post("/search/semantic", response_model=None, include_in_schema=False)
async def wiki_semantic_search(
    body: WikiSemanticSearchBody,
    raw_store: object = Depends(wiki_shared.get_wiki_store_dep),
) -> dict[str, object]:
    """Combine wiki fulltext/graph search with code entities and call chains."""
    wiki = WikiStore(raw_store)
    svc = SemanticWikiQuery(wiki, graph_store=wiki)
    result = await svc.search(body.query, body.repository, limit=body.limit)
    return semantic_search_result_to_dict(result)


wiki_router.include_router(wiki_task_router)
wiki_router.include_router(wiki_contradiction_router)
wiki_router.include_router(wiki_page_router)
wiki_router.include_router(wiki_ask_router)
wiki_router.include_router(wiki_feedback_router)

mcp_wiki_http_router = APIRouter(
    prefix="/api/v1/mcp",
    tags=["mcp", "wiki"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
mcp_wiki_http_router.include_router(wiki_mcp_tools_router)

# Re-exports (tests patch api.routes.wiki_routes, e.g. GraphQueryRepository, get_settings, time)
get_task_registry_dep = wiki_shared.get_task_registry_dep
get_wiki_service_dep = wiki_shared.get_wiki_service_dep
get_wiki_store_dep = wiki_shared.get_wiki_store_dep
get_wiki_search_dep = wiki_shared.get_wiki_search_dep
get_wiki_ask_dep = wiki_shared.get_wiki_ask_dep
get_wiki_cache_dep = wiki_shared.get_wiki_cache_dep
get_wiki_docs_exporter_dep = wiki_shared.get_wiki_docs_exporter_dep
get_wiki_lint_service_dep = wiki_shared.get_wiki_lint_service_dep
get_wiki_feedback_store_dep = wiki_shared.get_wiki_feedback_store_dep
get_wiki_generation_sem = wiki_shared.get_wiki_generation_sem
get_wiki_deep_research_dep = wiki_shared.get_wiki_deep_research_dep
get_wiki_memory_loop_dep = wiki_shared.get_wiki_memory_loop_dep
get_graph_query_dep = wiki_shared.get_graph_query_dep
_GLOBAL_SEARCH_CONCURRENCY = wiki_shared._GLOBAL_SEARCH_CONCURRENCY
_GLOBAL_SEARCH_MAX_REPOS = wiki_shared._GLOBAL_SEARCH_MAX_REPOS

__all__ = [
    "wiki_router",
    "mcp_wiki_http_router",
    "WIKI_TASK_TTL_SEC",
    "WikiTaskRegistry",
    "WikiQualityScorer",
    "GraphQueryRepository",
    "get_settings",
    "get_task_registry_dep",
    "get_wiki_service_dep",
    "get_wiki_store_dep",
    "get_wiki_search_dep",
    "get_wiki_ask_dep",
    "get_wiki_cache_dep",
    "get_wiki_docs_exporter_dep",
    "get_wiki_lint_service_dep",
    "get_wiki_feedback_store_dep",
    "get_wiki_generation_sem",
    "get_wiki_deep_research_dep",
    "get_wiki_memory_loop_dep",
    "get_graph_query_dep",
    "_GLOBAL_SEARCH_CONCURRENCY",
    "_GLOBAL_SEARCH_MAX_REPOS",
    "time",
    "WikiGenerateBody",
    "WikiIncrementalGenerateBody",
    "WikiQuickBody",
    "IngestRequest",
    "RelatedEntity",
    "WikiPageEntitiesResponse",
]
