"""Route group: search_routes (extracted from main)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

import api.kb_state as kb_state
from api.exceptions import KbError
from api.routes import kb_routers
from api.routes.kb_dependencies import get_effective_business_id, get_service
from api.routes.kb_schemas import (
    ARCHITECTURE_LAYERS,
    DeepSearchRequest,
    GraphQueryRequest,
    HybridSearchRequest,
)
from services.kb_service import KnowledgeBaseService
from store.graph_queries import GraphQueryRepository, validate_architecture_class_search
from utils.git_utils import looks_like_git_url
from log import get_logger

log = get_logger(__name__)
viewer_router = kb_routers.viewer_router
editor_router = kb_routers.editor_router
admin_router = kb_routers.admin_router
public_router = kb_routers.public_router
@viewer_router.get("/search/architecture")
async def search_architecture(
    layer: str,
    repository: str | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = Query(
        default=None,
        description="Case-insensitive substring match on class name",
    ),
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    if layer not in ARCHITECTURE_LAYERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid layer; expected one of: {', '.join(sorted(ARCHITECTURE_LAYERS))}",
        )
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")
    try:
        search_param = validate_architecture_class_search(search)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    lim = max(1, min(limit, 500))
    off = offset
    try:
        queries = GraphQueryRepository(svc.store)
        total_count = await queries.count_classes_by_architecture_layer(
            layer, repository, search=search_param
        )
        classes = await queries.search_classes_by_architecture_layer(
            layer, repository, lim, search=search_param, offset=off
        )
        return {
            "layer": layer,
            "repository": repository,
            "limit": lim,
            "offset": off,
            "search": search_param,
            "classes": classes,
            "total_count": total_count,
        }
    except Exception as exc:
        log.error("search_architecture_failed", layer=layer, error=str(exc))
        raise KbError(str(exc)) from exc


@viewer_router.get("/quality/{entity_uid:path}")
async def get_code_quality(
    entity_uid: str,
    entity_type: str | None = Query(
        default=None,
        description="Optional: restrict to 'function' or 'class' (default: match either)",
    ),
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    from query.agent_workflow import AgentWorkflowService

    et = (entity_type or "").strip().lower()
    if et and et not in ("function", "class"):
        raise HTTPException(
            status_code=422,
            detail="entity_type must be 'function' or 'class' when provided",
        )
    try:
        workflow = AgentWorkflowService(svc.store)
        return await workflow.compute_quality_score(entity_uid, et)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("code_quality_failed", entity_uid=entity_uid, error=str(exc))
        raise KbError(str(exc)) from exc


@viewer_router.post("/graph")
async def graph_query(
    req: GraphQueryRequest,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    return await svc.mcp_handler.handle_rag_graph(req.model_dump())


@viewer_router.post("/hybrid")
async def hybrid_search(
    req: HybridSearchRequest,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    if req.repositories is not None:
        if len(req.repositories) == 0:
            result = await svc.hybrid_query.search_with_context(
                req.query,
                k=req.k,
                expand_depth=req.expand_depth,
                repository=None,
                language=req.language,
                offset=req.offset,
                limit=req.limit,
                sort_by=req.sort_by,
                entity_type=req.entity_type,
            )
        elif len(req.repositories) == 1:
            result = await svc.hybrid_query.search_with_context(
                req.query,
                k=req.k,
                expand_depth=req.expand_depth,
                repository=req.repositories[0],
                language=req.language,
                offset=req.offset,
                limit=req.limit,
                sort_by=req.sort_by,
                entity_type=req.entity_type,
            )
        else:
            result = await svc.hybrid_query.search_multi_repo(
                req.query,
                req.repositories,
                k=req.k,
                expand_depth=req.expand_depth,
                language=req.language,
                offset=req.offset,
                limit=req.limit,
                sort_by=req.sort_by,
                entity_type=req.entity_type,
            )
    else:
        result = await svc.hybrid_query.search_with_context(
            req.query,
            k=req.k,
            expand_depth=req.expand_depth,
            repository=req.repository,
            language=req.language,
            offset=req.offset,
            limit=req.limit,
            sort_by=req.sort_by,
            entity_type=req.entity_type,
        )
    return {
        "semantic_matches": result["results"],
        "graph_context": result["graph_context"],
        "total": result["total"],
        "offset": result["offset"],
        "limit": result["limit"],
        "query": result["query_text"],
        "confidence": result["confidence"],
        "no_results_reason": result["no_results_reason"],
    }


@viewer_router.post("/deep-search")
async def deep_search(
    req: DeepSearchRequest,
    svc: KnowledgeBaseService = Depends(get_service),
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    if not svc.deep_search:
        raise HTTPException(
            status_code=501,
            detail="LLM not configured, deep search unavailable",
        )
    return await svc.deep_search.search(
        req.query,
        max_iterations=req.max_iterations,
        _include_code=req.include_code,
        tenant_id=business_id,
    )


@viewer_router.post("/deep-search/stream")
async def deep_search_stream(
    req: DeepSearchRequest,
    svc: KnowledgeBaseService = Depends(get_service),
    business_id: str = Depends(get_effective_business_id),
) -> StreamingResponse:
    """SSE streaming version of deep search with real-time stage updates."""
    engine = svc.deep_search
    if engine is None:
        raise HTTPException(
            status_code=501,
            detail="LLM not configured, deep search unavailable",
        )

    async def event_generator():
        async for event in engine.search_stream(
            req.query,
            max_iterations=req.max_iterations,
            tenant_id=business_id,
        ):
            event_type = event.get("type", "message")
            data = json.dumps(event.get("data", {}), ensure_ascii=False, default=str)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
