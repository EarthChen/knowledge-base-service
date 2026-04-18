"""FastAPI routes for wiki generation (sync, SSE streaming, async tasks)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import Role, require_role
from wiki.models import parse_scope
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.structure_planner import WikiScopeError


class WikiTaskRegistry:
    """In-memory wiki generation tasks."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}


class WikiGenerateBody(BaseModel):
    repository: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    mode: str = Field(default="structure", pattern="^(full|structure)$")
    format: str = Field(default="json", pattern="^(markdown|json)$")


wiki_router = APIRouter(
    prefix="/api/v1/wiki",
    tags=["wiki"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)


async def get_wiki_service_dep(request: Request) -> WikiService:
    factory = getattr(request.app.state, "wiki_service_factory", None)
    if callable(factory):
        out = factory()
        if asyncio.iscoroutine(out):
            return await out
        return out  # type: ignore[no-any-return]
    raise HTTPException(
        status_code=503,
        detail={
            "error": "service_unavailable",
            "detail": "Wiki generation is not configured",
        },
    )


def get_task_registry_dep(request: Request) -> WikiTaskRegistry:
    reg = getattr(request.app.state, "wiki_tasks", None)
    if reg is None:
        reg = WikiTaskRegistry()
        request.app.state.wiki_tasks = reg
    return reg


def get_wiki_generation_sem(request: Request) -> asyncio.Semaphore:
    """Spec 4.16 — max 5 concurrent generations; semaphore lives on app.state (event-loop safe)."""
    try:
        sem = request.app.state["wiki_generation_sem"]
    except KeyError:
        sem = asyncio.Semaphore(5)
        request.app.state["wiki_generation_sem"] = sem
    return sem


def _invalid_scope_detail(exc: ValueError) -> str:
    msg = str(exc)
    if "Invalid scope" in msg:
        return "Scope must be 'repo', 'module:<path>', or 'class:<fqn>'"
    return msg


async def _run_wiki_task(
    task_id: str,
    svc: WikiService,
    body: WikiGenerateBody,
    registry: WikiTaskRegistry,
    sem: asyncio.Semaphore,
) -> None:
    rec = registry.tasks[task_id]
    try:
        rec["status"] = "queued"
        async with sem:
            rec["status"] = "running"
            result = await svc.generate(
                body.repository,
                body.scope,
                body.mode,
                body.format,
            )
            rec["result"] = result
            rec["status"] = "completed"
    except WikiRepoNotFoundError as exc:
        rec["status"] = "failed"
        rec["error"] = {"error": "repo_not_found", "detail": str(exc)}
    except WikiScopeError as exc:
        rec["status"] = "failed"
        rec["error"] = {"error": "scope_not_found", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surface as failed task
        rec["status"] = "failed"
        rec["error"] = {"error": "generation_failed", "detail": str(exc)}


@wiki_router.post("/generate", response_model=None)
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
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_scope",
                "detail": _invalid_scope_detail(exc),
            },
        ) from exc

    wants_stream = accept is not None and "text/event-stream" in accept.lower()

    if wants_stream:

        async def sse() -> Any:
            try:

                async for ev in svc.generate_stream_events(
                    body.repository,
                    body.scope,
                    body.mode,
                    body.format,
                ):
                    if "page" in ev:
                        payload = json.dumps(ev["page"])
                        yield f"event: wiki-page\ndata: {payload}\n\n"
                    elif "complete" in ev:
                        payload = json.dumps(ev["complete"])
                        yield f"event: wiki-complete\ndata: {payload}\n\n"
            except WikiRepoNotFoundError as exc:
                err = json.dumps({"error": "repo_not_found", "detail": str(exc)})
                yield f"event: error\ndata: {err}\n\n"
            except WikiScopeError as exc:
                err = json.dumps({"error": "scope_not_found", "detail": str(exc)})
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
        registry.tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "repository": body.repository,
            "scope": body.scope,
        }
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
            )
    except WikiRepoNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "repo_not_found",
                "detail": (
                    f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
                ),
            },
        ) from exc
    except WikiScopeError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "scope_not_found", "detail": str(exc)},
        ) from exc

    return result


@wiki_router.get("/tasks/{task_id}")
async def wiki_task_status(
    task_id: str,
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> dict[str, Any]:
    rec = registry.tasks.get(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail={"error": "task_not_found"})
    return rec
