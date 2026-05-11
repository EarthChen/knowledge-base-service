"""Wiki async generation, quick index, task status, and business-wiki generation."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.exceptions import KbClientError, KbNotFound, KbServiceUnavailable
from api.models.wiki_models import (
    BusinessWikiGenerateBody,
    WikiQuickBody,
)
from api.routes.wiki_shared import (
    _maybe_call,
    _run_wiki_quick_task,
    _wiki_page_from_export_dict,
    _wiki_structure_from_pages,
    get_task_registry_dep,
    get_wiki_cache_dep,
    get_wiki_generation_sem,
    get_wiki_service_dep,
    log,
)
from core.auth import Role, require_role
from services.git_manager import normalize_repo_name
from utils.git_utils import looks_like_git_url
from wiki.event_bus import WikiEvent, WikiEventBus
from wiki.exporter import WikiExporter
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.structure_planner import WikiScopeError
from wiki.task_registry import WikiTaskRegistry
from wiki.task_store import WikiTaskStore

router = APIRouter(tags=["wiki", "tasks"])


async def _check_business_lock(
    task_store: WikiTaskStore | None, business_id: str,
) -> str | None:
    """Acquire per-business wiki generation lock.

    Returns a non-empty token when Redis accepted the lock, an empty string when there is no
    Redis-backed task store, or None when the lock is already held.
    """
    if task_store is None:
        return ""
    return await task_store.try_lock(business_id)


async def _run_business_wiki_background(
    *,
    task_id: str,
    business_id: str,
    language: str,
    llm_provider: str | None,
    incremental: bool,
    mode: str = "structure",
    svc: WikiService,
    task_store: WikiTaskStore | None,
    event_bus: WikiEventBus | None,
    registry: WikiTaskRegistry | None = None,
    lock_token: str = "",
) -> None:
    """Background coroutine: run business wiki generation and update task state."""
    async def _progress(info: dict[str, Any]) -> None:
        if task_store:
            tr = int(info.get("total_repos", 0) or 0)
            cr = int(info.get("completed_repos", 0) or 0)
            denom = max(tr, 1)
            raw_pct = info.get("progress_pct")
            if isinstance(raw_pct, (int, float)) and not isinstance(raw_pct, bool):
                pct = int(max(0.0, min(1.0, float(raw_pct))) * 100)
            else:
                pct = int(cr / denom * 100)
            extra: dict[str, Any] = {
                "completed_repos": str(cr),
                "total_repos": str(tr),
                "current_repo": str(info.get("current_repo", "")),
                "progress_pct": str(pct),
            }
            phase = info.get("phase")
            if phase:
                extra["phase"] = str(phase)
            detail = info.get("detail")
            if detail:
                extra["detail"] = str(detail)
            await task_store.update_status(task_id, "running", **extra)
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
            mode=mode,
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
        if registry:
            prev = registry.get_task(task_id) or {}
            registry.put_task(
                task_id,
                {**prev, "status": "completed"},
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
    except Exception as e:
        log.exception("business_wiki_background_failed", task_id=task_id)
        detail = str(e)[:500]
        if task_store:
            await task_store.update_status(
                task_id, "failed", error="internal_error", detail=detail
            )
        if registry:
            prev = registry.get_task(task_id) or {}
            registry.put_task(
                task_id,
                {
                    **prev,
                    "status": "failed",
                    "error": "internal_error",
                    "detail": detail,
                },
            )
        if event_bus:
            await event_bus.publish(
                WikiEvent(
                    event_type="wiki:generation_failed",
                    repository=business_id,
                    business_id=business_id,
                    data={
                        "task_id": task_id,
                        "error": "internal_error",
                        "detail": detail,
                    },
                )
            )
    finally:
        if task_store and lock_token:
            await task_store.unlock(business_id, lock_token)


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
        supervisor = getattr(
            getattr(request.app.state, "container", None),
            "task_supervisor",
            None,
        )
        if supervisor is not None:
            supervisor.spawn(
                lambda tid=task_id,
                gurl=git_url,
                br=body.branch,
                tok=body.token,
                m=body.mode,
                lng=body.language,
                reg=registry,
                semaphore=sem,
                bf=bg_fn,
                llp=body.llm_provider: _run_wiki_quick_task(
                    tid, gurl, br, tok, m, lng, reg, semaphore, bf, llp
                ),
                name="wiki:quick",
                max_retries=1,
            )
        else:
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
                ),
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


@router.get(
    "/tasks/active",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def list_active_wiki_tasks(
    request: Request,
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> dict[str, Any]:
    """List all active (pending/running) wiki tasks from both Redis and in-memory registry."""
    task_store: WikiTaskStore | None = getattr(
        request.app.state, "wiki_task_store", None
    )
    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if task_store:
        try:
            redis_tasks = await task_store.list_active()
            for t in redis_tasks:
                tid = t.get("task_id", "")
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    tasks.append(t)
        except Exception:
            log.warning("list_active_tasks_redis_error", exc_info=True)

    for tid, rec in registry.tasks.items():
        if tid not in seen_ids and rec.get("status") in ("pending", "running"):
            seen_ids.add(tid)
            tasks.append(rec)

    return {"tasks": tasks, "total": len(tasks)}


@router.post(
    "/tasks/{task_id}/cancel",
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def cancel_wiki_task(
    task_id: str,
    request: Request,
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> dict[str, Any]:
    """Cancel a running wiki generation task."""
    task_store: WikiTaskStore | None = getattr(
        request.app.state, "wiki_task_store", None
    )
    event_bus: WikiEventBus | None = getattr(
        request.app.state, "wiki_event_bus", None
    )

    rec = registry.get_task(task_id)
    if rec is None and task_store:
        rec = await task_store.get_task(task_id)
    if rec is None:
        raise KbNotFound("task_not_found")

    if rec.get("status") in ("completed", "failed", "cancelled"):
        return {"task_id": task_id, "status": rec["status"], "detail": "already_terminal"}

    if task_store:
        await task_store.update_status(task_id, "cancelled")
        business_id = rec.get("business_id", "")
        if business_id:
            await task_store.force_release_lock(business_id)

    registry.put_task(task_id, {**rec, "status": "cancelled"})

    if event_bus:
        business_id = rec.get("business_id", "")
        await event_bus.publish(
            WikiEvent(
                event_type="wiki:generation_failed",
                repository=business_id,
                business_id=business_id,
                data={"task_id": task_id, "error": "cancelled_by_user"},
            )
        )

    log.info("wiki_task_cancelled", task_id=task_id)
    return {"task_id": task_id, "status": "cancelled"}


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
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> JSONResponse:
    """Trigger cross-repo business-level wiki generation as a background task."""
    task_store: WikiTaskStore | None = getattr(
        request.app.state, "wiki_task_store", None
    )
    event_bus: WikiEventBus | None = getattr(
        request.app.state, "wiki_event_bus", None
    )

    lock_token = await _check_business_lock(task_store, body.business_id)
    if lock_token is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "generation_in_progress",
                "detail": "Business wiki generation already running.",
            },
        )

    factory = getattr(request.app.state, "wiki_service_factory", None)
    if not callable(factory):
        raise KbServiceUnavailable("Wiki generation is not configured")
    out = factory(business_id=body.business_id)
    svc = await out if asyncio.iscoroutine(out) else out

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
        supervisor = getattr(
            getattr(request.app.state, "container", None),
            "task_supervisor",
            None,
        )
        if supervisor is not None:
            supervisor.spawn(
                lambda ti=task_id,
                bid=body.business_id,
                lang=body.language,
                llp=body.llm_provider,
                inc=body.incremental,
                md=body.mode,
                wsvc=svc,
                ts=task_store,
                eb=event_bus,
                reg=registry,
                ltok=lock_token: _run_business_wiki_background(
                    task_id=ti,
                    business_id=bid,
                    language=lang,
                    llm_provider=llp,
                    incremental=inc,
                    mode=md,
                    svc=wsvc,
                    task_store=ts,
                    event_bus=eb,
                    registry=reg,
                    lock_token=ltok,
                ),
                name="wiki:business",
                max_retries=1,
            )
        else:
            asyncio.create_task(
                _run_business_wiki_background(
                    task_id=task_id,
                    business_id=body.business_id,
                    language=body.language,
                    llm_provider=body.llm_provider,
                    incremental=body.incremental,
                    mode=body.mode,
                    svc=svc,
                    task_store=task_store,
                    event_bus=event_bus,
                    registry=registry,
                    lock_token=lock_token,
                ),
            )
    except Exception:
        if task_store and lock_token:
            await task_store.unlock(body.business_id, lock_token)
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

