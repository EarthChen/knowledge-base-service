"""Wiki Q&A (streaming) and deep research."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.exceptions import KbNotFound
from api.models.wiki_models import (
    WikiAskBody,
    WikiCrystallizeBody,
    WikiCrystallizeResponse,
    WikiResearchBody,
)
from api.routes.wiki_shared import (
    get_route_settings,
    get_wiki_ask_dep,
    get_wiki_deep_research_dep,
    get_wiki_store_dep,
    log,
)
from core.auth import Role, require_role
from store.wiki_store import WikiStore
from wiki.ask import WikiAskService
from wiki.deep_research import DeepResearchService
from wiki.suggested_questions import PageContext, SuggestedQuestionsGenerator

router = APIRouter(tags=["wiki", "ask"])


async def _wiki_ask_stream_sse_v2(
    ask_svc: WikiAskService,
    *,
    repository: str,
    question: str,
    scope: str | None = None,
    conversation_id: str | None = None,
    mode: str = "hybrid",
    record_memory: bool = False,
    business_id: str | None = None,
) -> AsyncIterator[bytes]:
    """Canonical wiki-ask SSE format (use ``POST/GET /ask/stream``).

    Each frame is ``data: {json}\\n\\n`` with no ``event:`` line. Payload ``type`` values:
    ``token``, ``sources``, ``done``, ``rag_progress``, or ``error``.
    """
    try:
        async for ev in ask_svc.ask_stream(
            repository=repository,
            question=question,
            scope=scope,
            conversation_id=conversation_id,
            mode=mode,
            record_memory=record_memory,
            business_id=business_id,
        ):
            event_name = str(ev.get("event", "message"))
            data = ev.get("data") or {}
            if event_name == "wiki-answer":
                delta = data.get("delta", "")
                if not delta and not (data.get("content") or ""):
                    continue
                payload: dict[str, object] = {
                    "type": "token",
                    "content": str(delta) if delta else str(data.get("content", "")),
                }
                if payload["content"] == "":
                    continue
            elif event_name == "wiki-sources":
                payload = {"type": "sources", "sources": data.get("sources", []) or []}
            elif event_name == "wiki-answer-complete":
                payload = {
                    "type": "done",
                    "conversation_id": data.get("conversation_id", ""),
                    "tokens_used": data.get("tokens_used", 0),
                    "reasoning_path": data.get("reasoning_path"),
                }
            elif event_name == "rag-progress":
                inner = data if isinstance(data, dict) else {}
                # Nest under "rag" so envelope type rag_progress is not overwritten by stage "type".
                payload = {"type": "rag_progress", "rag": inner}
            else:
                continue
            yield f"data: {json.dumps(payload, default=str)}\n\n".encode()
    except Exception:
        log.exception("wiki ask stream (v2) failed")
        err = json.dumps(
            {
                "type": "error",
                "error": "ask_failed",
                "detail": "The question could not be answered. Please try again.",
            }
        )
        yield f"data: {err}\n\n".encode()


@router.get("/pages/{page_uid:path}/questions", response_model=None)
async def get_page_suggested_questions(
    page_uid: str,
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    """Graph-aware exploration questions for a wiki page (SOURCE_ENTITY + CALLS)."""
    decoded = unquote(page_uid)
    ws = WikiStore(store)
    raw = await ws.get_suggested_questions_context(decoded)
    if raw is None:
        raise KbNotFound(f"No wiki page for uid {decoded!r}")
    ctx = PageContext(
        entity_name=raw["entity_name"],
        domain=raw["domain"],
        callers=raw["callers"],
        callees=raw["callees"],
        cross_domain_callers=raw["cross_domain_callers"],
    )
    gen = SuggestedQuestionsGenerator()
    questions = gen.generate(ctx)
    return {"questions": questions, "page_uid": raw["page_uid"]}


@router.post(
    "/ask/crystallize",
    response_model=WikiCrystallizeResponse,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_ask_crystallize(
    body: WikiCrystallizeBody,
    ask_svc: WikiAskService = Depends(get_wiki_ask_dep),
) -> WikiCrystallizeResponse:
    """Save the current Q&A as a new wiki page with backlinks to source pages."""
    try:
        out = await ask_svc.crystallize(
            repository=body.repository,
            question=body.question,
            answer=body.answer,
            sources=list(body.sources),
            business_id=body.business_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return WikiCrystallizeResponse(
        page_uid=out["page_uid"],
        title=out["title"],
        path=out["path"],
        conversation_id=body.conversation_id,
    )


@router.post("/ask", response_model=None)
async def wiki_ask(
    body: WikiAskBody,
    ask_svc: WikiAskService = Depends(get_wiki_ask_dep),
) -> StreamingResponse:
    """Legacy SSE: named ``event:`` lines (``wiki-answer``, ``wiki-sources``, …).

    Deprecated — migrate to ``POST /ask/stream`` (JSON ``data: {"type":...}`` frames).
    """
    log.warning(
        "wiki_ask_legacy_sse_endpoint",
        endpoint="POST /ask",
        canonical="POST /ask/stream",
        detail="Named event: lines are deprecated; use data-only JSON type frames.",
    )

    async def sse() -> Any:
        try:
            async for ev in ask_svc.ask_stream(
                repository=body.repository,
                question=body.question,
                scope=body.scope,
                conversation_id=body.conversation_id,
                mode=body.mode,
                record_memory=body.record_memory,
                business_id=body.business_id,
            ):
                event = str(ev.get("event", "message"))
                payload = json.dumps(ev.get("data") or {})
                yield f"event: {event}\ndata: {payload}\n\n"
        except Exception:
            log.exception("wiki ask stream failed")
            err = json.dumps(
                {"error": "ask_failed", "detail": "The question could not be answered. Please try again."}
            )
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@router.post("/ask/stream", response_model=None)
async def wiki_ask_stream_post(
    body: WikiAskBody,
    ask_svc: WikiAskService = Depends(get_wiki_ask_dep),
) -> StreamingResponse:
    """SSE with `data: {"type":"token"|"sources"|"done", ...}` (no named `event:` lines)."""
    return StreamingResponse(
        _wiki_ask_stream_sse_v2(
            ask_svc,
            repository=body.repository,
            question=body.question,
            scope=body.scope,
            conversation_id=body.conversation_id,
            mode=body.mode,
            record_memory=body.record_memory,
            business_id=body.business_id,
        ),
        media_type="text/event-stream",
    )


@router.get("/ask/stream", response_model=None)
async def wiki_ask_stream_get(
    ask_svc: WikiAskService = Depends(get_wiki_ask_dep),
    repository: str = Query(..., min_length=1),
    question: str = Query(..., min_length=1),
    page_context: str | None = None,
    scope: str | None = None,
    conversation_id: str | None = None,
    mode: str = Query(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$"),
    record_memory: bool = False,
    business_id: str | None = None,
) -> StreamingResponse:
    """Same SSE format as ``POST /ask/stream``; for clients limited to GET (e.g. EventSource)."""
    q = question
    if page_context:
        q = f"{page_context}\n\n---\n\n{question}"
    return StreamingResponse(
        _wiki_ask_stream_sse_v2(
            ask_svc,
            repository=repository,
            question=q,
            scope=scope,
            conversation_id=conversation_id,
            mode=mode,
            record_memory=record_memory,
            business_id=business_id,
        ),
        media_type="text/event-stream",
    )


@router.post("/research", response_model=None)
async def wiki_research(
    body: WikiResearchBody,
    research_svc: DeepResearchService = Depends(get_wiki_deep_research_dep),
) -> dict[str, Any]:
    """Multi-step deep research over the wiki (sub-questions + synthesis)."""
    settings = get_route_settings()
    if not settings.wiki.deep_research_enabled:
        raise KbNotFound("Deep research is disabled")
    return await research_svc.research(
        question=body.question,
        repository=body.repository,
        business_id=body.business_id,
    )
