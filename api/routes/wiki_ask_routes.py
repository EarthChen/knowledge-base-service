"""Wiki Q&A (streaming) and deep research."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.exceptions import KbNotFound
from store.wiki_store import WikiStore
from wiki.ask import WikiAskService
from wiki.suggested_questions import PageContext, SuggestedQuestionsGenerator
from api.models.wiki_models import WikiAskBody, WikiResearchBody
from api.routes.wiki_shared import get_route_settings, get_wiki_ask_dep, get_wiki_deep_research_dep, get_wiki_store_dep, log
from wiki.deep_research import DeepResearchService

router = APIRouter(tags=["wiki", "ask"])


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


@router.post("/ask", response_model=None)
async def wiki_ask(
    body: WikiAskBody,
    ask_svc: WikiAskService = Depends(get_wiki_ask_dep),
) -> StreamingResponse:
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
