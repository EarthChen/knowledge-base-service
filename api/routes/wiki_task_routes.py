"""Wiki async generation, quick index, task status, and business-wiki generation."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.exceptions import KbClientError, KbNotFound
from auth import Role, require_role
from services.git_manager import normalize_repo_name
from utils.git_utils import looks_like_git_url
from wiki.models import parse_scope
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.structure_planner import WikiScopeError
from wiki.exporter import WikiExporter
from wiki.task_store import WikiTaskStore
from api.models.wiki_models import (
    BusinessWikiGenerateBody,
    WikiGenerateBody,
    WikiQuickBody,
)
from api.routes.wiki_shared import (
    _invalid_scope_detail,
    _maybe_call,
    _run_wiki_quick_task,
    _run_wiki_task,
    _wiki_page_from_export_dict,
    _wiki_structure_from_pages,
    get_task_registry_dep,
    get_wiki_cache_dep,
    get_wiki_generation_sem,
    get_wiki_service_dep,
    log,
)
from wiki.event_bus import WikiEvent, WikiEventBus
from wiki.task_registry import WikiTaskRegistry

router = APIRouter(tags=["wiki", "tasks"])


async def _check_business_lock(
    task_store: WikiTaskStore | None, business_id: str,
) -> bool:
    """Return True if lock acquired, False if already locked."""
    if task_store is None:
        return True
    return await task_store.try_lock(business_id)


async def _run_business_wiki_background(
    *,
    task_id: str,
    business_id: str,
    language: str,
    llm_provider: str | None,
    incremental: bool,
    svc: WikiService,
    task_store: WikiTaskStore | None,
    event_bus: WikiEventBus | None,
) -> None:
    """Background coroutine: run business wiki generation and update task state."""
    async def _progress(info: dict[str, Any]) -> None:
        if task_store:
            tr = int(info.get("total_repos", 0) or 0)
            cr = int(info.get("completed_repos", 0) or 0)
            denom = max(tr, 1)
            pct = int(cr / denom * 100)
            await task_store.update_status(
                task_id,
                "running",
                completed_repos=str(cr),
                total_repos=str(tr),
                current_repo=str(info.get("current_repo", "")),
                progress_pct=str(pct),
            )
        if event_bus:
            await event_bus.publish(
                WikiEvent(
                    event_type="business_gen_progress",
                    repository=business_id,
                    business_id=business_id,
                    data={"task_id": task_id, **info},
                )
            )

    try:
        if task_store:
            await task_store.update_status(task_id, "running")
        if event_bus:
            await event_bus.publish(
                WikiEvent(
                    event_type="wiki:generation_started",
                    repository=business_id,
                    business_id=business_id,
                    data={"task_id": task_id},
                )
            )
        result = await svc.generate_business_wiki(
            business_id=business_id,
            language=language,
            llm_provider=llm_provider,
            incremental=incremental,
            progress_callback=_progress,
        )
        if task_store:
            await task_store.update_status(
                task_id,
                "completed",
                result=result,
                partial_errors=result.get("partial_errors", []),
                skipped_repos=result.get("skipped_repos", []),
            )
        if event_bus:
            await event_bus.publish(
                WikiEvent(
                    event_type="wiki:generation_completed",
                    repository=business_id,
                    business_id=business_id,
                    data={"task_id": task_id, "pages_count": result.get("pages_count", 0)},
                )
            )
    except Exception:
        log.exception("business_wiki_background_failed", task_id=task_id)
        if task_store:
            await task_store.update_status(task_id, "failed", error="internal_error")
        if event_bus:
            await event_bus.publish(
                WikiEvent(
                    event_type="wiki:generation_failed",
                    repository=business_id,
                    business_id=business_id,
                    data={"task_id": task_id, "error": "internal_error"},
                )
            )
    finally:
        if task_store:
            await task_store.unlock(business_id)


def _wiki_event_to_sse_data(ev: WikiEvent) -> str:
    d: dict[str, Any] = {
        "type": ev.event_type,
        "business_id": ev.business_id,
        "timestamp": ev.timestamp,
    }
    if "page_path" in ev.data:
        d["page_path"] = ev.data["page_path"]
    rest = {k: v for k, v in ev.data.items() if k != "page_path"}
    if rest:
        d["payload"] = rest
    return json.dumps(d, default=str)


@router.post("/generate", response_model=None)
async def wiki_generate(
    body: WikiGenerateBody,
    accept: Annotated[str | None, Header()] = None,
    svc: WikiService = Depends(get_wiki_service_dep),
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
    sem: asyncio.Semaphore = Depends(get_wiki_generation_sem),
) -> StreamingResponse | JSONResponse | dict[str, Any]:
    try:
        scope_param = parse_scope(body.scope)
    except ValueError as exc:
        raise KbClientError(_invalid_scope_detail(exc)) from exc

    wants_stream = accept is not None and "text/event-stream" in accept.lower()

    if wants_stream:

        async def sse() -> Any:
            try:

                async for ev in svc.generate_stream_events(
                    body.repository,
                    body.scope,
                    body.mode,
                    body.format,
                    body.language,
                    llm_provider=body.llm_provider,
                ):
                    if "page" in ev:
                        payload = json.dumps(ev["page"])
                        yield f"event: wiki-page\ndata: {payload}\n\n"
                    elif "enrichment" in ev:
                        payload = json.dumps(ev["enrichment"])
                        yield f"event: wiki-enrichment\ndata: {payload}\n\n"
                    elif "complete" in ev:
                        payload = json.dumps(ev["complete"])
                        yield f"event: wiki-complete\ndata: {payload}\n\n"
            except WikiRepoNotFoundError as exc:
                err = json.dumps(
                    {
                        "error": "repo_not_found",
                        "detail": f"Repository '{exc.repository}' is not indexed.",
                    }
                )
                yield f"event: error\ndata: {err}\n\n"
            except WikiScopeError as exc:
                log.warning("wiki sse scope error", error=str(exc))
                err = json.dumps(
                    {
                        "error": "scope_not_found",
                        "detail": "The requested wiki scope could not be found.",
                    }
                )
                yield f"event: error\ndata: {err}\n\n"
            except ValueError as exc:
                err = json.dumps({"error": "invalid_scope", "detail": _invalid_scope_detail(exc)})
                yield f"event: error\ndata: {err}\n\n"

        # Streaming uses same concurrency gate as sync generation
        async def sse_wrapped() -> Any:
            async with sem:
                async for chunk in sse():
                    yield chunk

        return StreamingResponse(sse_wrapped(), media_type="text/event-stream")

    if scope_param.scope_type == "repo":
        task_id = f"wiki-{uuid.uuid4().hex}"
        registry.put_task(
            task_id,
            {
                "task_id": task_id,
                "status": "pending",
                "repository": body.repository,
                "scope": body.scope,
            },
        )
        asyncio.create_task(_run_wiki_task(task_id, svc, body, registry, sem))
        return JSONResponse(
            status_code=202,
            content={"task_id": task_id, "status": "pending"},
        )

    try:
        async with sem:
            result = await svc.generate(
                body.repository,
                body.scope,
                body.mode,
                body.format,
                body.language,
                llm_provider=body.llm_provider,
            )
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc
    except WikiScopeError as exc:
        log.warning("wiki generate scope error", error=str(exc))
        raise KbNotFound("The requested wiki scope could not be found.") from exc

    return result


@router.post("/quick", response_model=None)
async def wiki_quick(
    body: WikiQuickBody,
    request: Request,
    svc: WikiService = Depends(get_wiki_service_dep),
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
    sem: asyncio.Semaphore = Depends(get_wiki_generation_sem),
    cache: Any = Depends(get_wiki_cache_dep),
) -> JSONResponse | dict[str, Any]:
    from api.routes.wiki_shared import _QUICK_FORMAT, _QUICK_SCOPE

    git_url = body.git_url.strip()
    if not looks_like_git_url(git_url):
        raise KbClientError(
            "git_url must look like an https, ssh, git@, or .git remote URL",
        )

    status_fn = getattr(request.app.state, "wiki_quick_repo_status", None)
    if callable(status_fn):
        repo, indexed, gv = await _maybe_call(status_fn, git_url, body.branch, body.token)
    else:
        repo = normalize_repo_name(git_url)
        indexed = False
        gv = 0

    gv_fn = getattr(request.app.state, "wiki_graph_version", None)
    if indexed and callable(gv_fn):
        gv_out = gv_fn(repo)
        if asyncio.iscoroutine(gv_out):
            gv = await gv_out
        else:
            gv = int(gv_out)

    if not indexed:
        task_id = f"wiki-quick-{uuid.uuid4().hex}"
        registry.put_task(
            task_id,
            {
                "task_id": task_id,
                "status": "pending",
                "git_url": git_url,
                "branch": body.branch,
                "mode": body.mode,
            },
        )
        bg_fn = getattr(request.app.state, "wiki_quick_background", None)
        asyncio.create_task(
            _run_wiki_quick_task(
                task_id,
                git_url,
                body.branch,
                body.token,
                body.mode,
                body.language,
                registry,
                sem,
                bg_fn,
                body.llm_provider,
            )
        )
        return JSONResponse(
            status_code=202,
            content={"task_id": task_id, "status": "pending"},
        )

    cached_pages = cache.get(repo, _QUICK_SCOPE, body.mode, gv)
    if cached_pages is not None:
        structure = _wiki_structure_from_pages(repo, cached_pages)
        bundle = WikiExporter().export_json(cached_pages, structure)
        bundle["degraded"] = False
        return bundle

    try:
        async with sem:
            result = await svc.generate(
                repo,
                _QUICK_SCOPE,
                body.mode,
                _QUICK_FORMAT,
                body.language,
                llm_provider=body.llm_provider,
            )
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. "
            "Use indexing API or wait for quick background indexing."
        ) from exc
    except WikiScopeError as exc:
        log.warning("wiki quick scope error", error=str(exc))
        raise KbNotFound("The requested wiki scope could not be found.") from exc

    pages_models = [_wiki_page_from_export_dict(p, repo) for p in result["pages"]]
    cache.put(repo, _QUICK_SCOPE, body.mode, gv, pages_models)
    return result


@router.get("/tasks/{task_id}")
async def wiki_task_status(
    task_id: str,
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> dict[str, Any]:
    rec = registry.get_task(task_id)
    if rec is None:
        raise KbNotFound("task_not_found")
    return rec


@router.get(
    "/events",
    response_model=None,
)
async def wiki_events_stream(
    request: Request,
    business_id: str = Query(..., min_length=1),
) -> StreamingResponse:
    """SSE of wiki events for a business. EventSource may pass the API token as ``token`` (no header)."""
    log.debug("wiki_events_subscribe", business_id=business_id)

    async def events() -> AsyncIterator[str]:
        yield ": stream-open\n\n"
        bus = getattr(request.app.state, "wiki_event_bus", None)
        if bus is None:
            while True:
                await asyncio.sleep(60.0)
                yield ": keepalive\n\n"
        aiter = bus.stream(business_id).__aiter__()
        while True:
            try:
                event: WikiEvent = await asyncio.wait_for(aiter.__anext__(), 60.0)
            except StopAsyncIteration:
                break
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            body = _wiki_event_to_sse_data(event)
            yield f"data: {body}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/business/generate",
    response_model=None,
    status_code=202,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def generate_business_wiki(
    body: BusinessWikiGenerateBody,
    request: Request,
    svc: WikiService = Depends(get_wiki_service_dep),
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> JSONResponse:
    """Trigger cross-repo business-level wiki generation as a background task."""
    task_store: WikiTaskStore | None = getattr(
        request.app.state, "wiki_task_store", None
    )
    event_bus: WikiEventBus | None = getattr(
        request.app.state, "wiki_event_bus", None
    )

    if not await _check_business_lock(task_store, body.business_id):
        return JSONResponse(
            status_code=409,
            content={
                "error": "generation_in_progress",
                "detail": "Business wiki generation already running.",
            },
        )

    task_id = f"biz-wiki-{uuid.uuid4().hex[:12]}"
    try:
        initial = {
            "task_id": task_id,
            "status": "pending",
            "business_id": body.business_id,
            "incremental": str(body.incremental),
        }
        if task_store:
            await task_store.put_task(task_id, initial)
        registry.put_task(task_id, initial)
        asyncio.create_task(
            _run_business_wiki_background(
                task_id=task_id,
                business_id=body.business_id,
                language=body.language,
                llm_provider=body.llm_provider,
                incremental=body.incremental,
                svc=svc,
                task_store=task_store,
                event_bus=event_bus,
            )
        )
    except Exception:
        if task_store:
            await task_store.unlock(body.business_id)
        raise

    return JSONResponse(
        status_code=202, content={"task_id": task_id, "status": "pending"}
    )


@router.get(
    "/business/tasks/{task_id}",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def business_wiki_task_status(
    task_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get background business wiki task progress from Redis store."""
    task_store: WikiTaskStore | None = getattr(
        request.app.state, "wiki_task_store", None
    )
    if task_store:
        rec = await task_store.get_task(task_id)
        if rec is not None:
            return rec
    registry = getattr(request.app.state, "wiki_tasks", None)
    if registry:
        rec = registry.get_task(task_id)
        if rec is not None:
            return rec
    raise KbNotFound("task_not_found")

