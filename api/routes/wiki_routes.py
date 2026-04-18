"""FastAPI routes for wiki generation (sync, SSE streaming, async tasks)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import Role, require_role
from log import get_logger
from query.graph_query import GraphQueryService
from git_manager import normalize_repo_name
from wiki.ask import WikiAskService
from wiki.cache import WikiCache
from wiki.exporter import WikiExporter
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
    parse_scope,
)
from wiki.search import SearchResponse, WikiSearchService
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.structure_planner import WikiScopeError

log = get_logger(__name__)


class WikiTaskRegistry:
    """In-memory wiki generation tasks."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}


class WikiGenerateBody(BaseModel):
    repository: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    mode: str = Field(default="structure", pattern="^(full|structure)$")
    format: str = Field(default="json", pattern="^(markdown|json)$")
    language: str = Field(default="en", pattern="^(en|zh)$")
    llm_provider: str | None = None


class WikiQuickBody(BaseModel):
    git_url: str = Field(..., min_length=1)
    branch: str | None = None
    token: str | None = None
    mode: str = Field(default="structure", pattern="^(full|structure)$")
    language: str = Field(default="en", pattern="^(en|zh)$")
    llm_provider: str | None = None


class WikiSearchBody(BaseModel):
    repository: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scope: str | None = None


class WikiAskBody(BaseModel):
    repository: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    scope: str | None = None
    conversation_id: str | None = None
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")


class AnalyzeImpactFile(BaseModel):
    path: str
    status: str = Field(pattern="^(added|modified|removed|renamed)$")


class AnalyzeImpactBody(BaseModel):
    changed_files: list[AnalyzeImpactFile]


_QUICK_SCOPE = "repo"
_QUICK_FORMAT = "json"


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


async def get_wiki_search_dep(request: Request) -> WikiSearchService:
    svc = getattr(request.app.state, "wiki_search_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "detail": "Wiki search is not configured",
            },
        )
    return svc


async def get_wiki_ask_dep(request: Request) -> WikiAskService:
    svc = getattr(request.app.state, "wiki_ask_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "detail": "Wiki ask is not configured",
            },
        )
    return svc


def get_graph_query_dep(request: Request) -> GraphQueryService:
    """Resolve graph query service; use with ``Depends`` when the graph is required for every request."""
    gq = getattr(request.app.state, "graph_query_service", None)
    if gq is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "detail": "Graph query is not configured",
            },
        )
    return gq


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


def get_wiki_cache_dep(request: Request) -> WikiCache:
    cache = getattr(request.app.state, "wiki_cache", None)
    if cache is None:
        cache = WikiCache()
        request.app.state.wiki_cache = cache
    return cache


def _looks_like_git_url(value: str) -> bool:
    if value.startswith(("http://", "https://", "git@", "ssh://")):
        return True
    return value.endswith(".git")


async def _maybe_call(fn: Callable[..., Any], *args: Any) -> Any:
    out = fn(*args)
    if asyncio.iscoroutine(out):
        return await out
    return out


def _wiki_page_from_export_dict(data: dict[str, Any], repository: str) -> WikiPage:
    diagrams: list[WikiDiagram] = []
    for d in data.get("diagrams") or []:
        dtype = d.get("type") or d.get("diagram_type")
        diagrams.append(
            WikiDiagram(
                diagram_type=DiagramType(dtype),
                content=str(d.get("content", "")),
                title=str(d.get("title", "")),
            )
        )
    src: list[SourceLocation] = []
    for loc in data.get("source_locations") or []:
        src.append(
            SourceLocation(
                file_path=str(loc["file_path"]),
                start_line=int(loc["start_line"]),
                end_line=int(loc["end_line"]),
                fqn=str(loc["fqn"]),
                repository=repository,
            )
        )
    methods: list[SourceLocation] = []
    for loc in data.get("method_locations") or []:
        methods.append(
            SourceLocation(
                file_path=str(loc["file_path"]),
                start_line=int(loc["start_line"]),
                end_line=int(loc["end_line"]),
                fqn=str(loc["fqn"]),
                repository=repository,
            )
        )
    meta_raw = data.get("metadata") or {}
    metadata = WikiPageMetadata(
        node_count=int(meta_raw.get("node_count", 0)),
        edge_count=int(meta_raw.get("edge_count", 0)),
        generation_mode=str(meta_raw.get("generation_mode", "structure")),
        fallback_tier=meta_raw.get("fallback_tier"),
    )
    return WikiPage(
        path=str(data["path"]),
        title=str(data["title"]),
        page_type=PageType(data["page_type"]),
        content=str(data.get("content", "")),
        diagrams=diagrams,
        source_locations=src,
        metadata=metadata,
        method_locations=methods,
    )


def _search_response_to_json(resp: SearchResponse) -> dict[str, Any]:
    """Serialize ``SearchResponse`` dataclass to JSON-compatible dict."""
    return {
        "results": [asdict(r) for r in resp.results],
        "query_expansion": resp.query_expansion,
        "total": resp.total,
    }


def _scopes_flat_from_structure_root(root: dict[str, Any]) -> list[str]:
    """Mirror ``WikiService._compose_all_pages`` walk order for scope labels."""
    out: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        pt = node.get("page_type")
        path = str(node.get("path", ""))
        children = node.get("children") or []
        if pt == "repo_overview":
            out.append("repo")
            for ch in children:
                walk(ch)
        elif pt == "module_overview":
            out.append(f"module:{path}")
            for ch in children:
                walk(ch)
        else:
            out.append(f"class:{path}")

    walk(root)
    return out


def _wiki_page_detail_context(repository: str, page: dict[str, Any]) -> dict[str, str]:
    ctx: dict[str, str] = {
        "repository": repository,
        "module": "",
        "page": str(page.get("path", "")),
    }
    srcs = page.get("source_locations") or []
    if srcs:
        fp = str(srcs[0].get("file_path", "") or "")
        if fp:
            ctx["module"] = fp.rsplit("/", 1)[0] if "/" in fp else fp
    return ctx


def _wiki_structure_from_pages(repository: str, pages: list[WikiPage]) -> WikiStructure:
    overview = [p for p in pages if p.page_type == PageType.REPO_OVERVIEW]
    root_src = overview[0] if overview else None
    others = [p for p in pages if p.page_type != PageType.REPO_OVERVIEW]
    if root_src is not None:
        root = WikiStructureNode(
            path=root_src.path,
            title=root_src.title,
            page_type=root_src.page_type,
            children=[
                WikiStructureNode(path=p.path, title=p.title, page_type=p.page_type, children=[])
                for p in others
            ],
        )
    else:
        root = WikiStructureNode(
            path="README.md",
            title=repository,
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(path=p.path, title=p.title, page_type=p.page_type, children=[])
                for p in pages
            ],
        )
    return WikiStructure(repository=repository, root=root, total_pages=len(pages))


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
                body.language,
                llm_provider=body.llm_provider,
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


async def _run_wiki_quick_task(
    task_id: str,
    git_url: str,
    branch: str | None,
    token: str | None,
    mode: str,
    language: str,
    registry: WikiTaskRegistry,
    sem: asyncio.Semaphore,
    background_fn: Callable[..., Any] | None,
    llm_provider: str | None,
) -> None:
    rec = registry.tasks[task_id]
    try:
        rec["status"] = "queued"
        async with sem:
            rec["status"] = "running"
            if background_fn is None:
                raise RuntimeError("wiki_quick_background is not configured")
            bg_out = background_fn(
                git_url=git_url,
                branch=branch,
                token=token,
                mode=mode,
                language=language,
                llm_provider=llm_provider,
            )
            if asyncio.iscoroutine(bg_out):
                result = await bg_out
            else:
                result = bg_out
            rec["result"] = result
            rec["status"] = "completed"
    except WikiRepoNotFoundError as exc:
        rec["status"] = "failed"
        rec["error"] = {"error": "repo_not_found", "detail": str(exc)}
    except WikiScopeError as exc:
        rec["status"] = "failed"
        rec["error"] = {"error": "scope_not_found", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
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
                    body.language,
                    llm_provider=body.llm_provider,
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
                body.language,
                llm_provider=body.llm_provider,
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


@wiki_router.post("/quick", response_model=None)
async def wiki_quick(
    body: WikiQuickBody,
    request: Request,
    svc: WikiService = Depends(get_wiki_service_dep),
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
    sem: asyncio.Semaphore = Depends(get_wiki_generation_sem),
    cache: WikiCache = Depends(get_wiki_cache_dep),
) -> JSONResponse | dict[str, Any]:
    git_url = body.git_url.strip()
    if not _looks_like_git_url(git_url):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_git_url",
                "detail": "git_url must look like an https, ssh, git@, or .git remote URL",
            },
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
        registry.tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "git_url": git_url,
            "branch": body.branch,
            "mode": body.mode,
        }
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
        raise HTTPException(
            status_code=404,
            detail={
                "error": "repo_not_found",
                "detail": (
                    f"Repository '{exc.repository}' not indexed. "
                    "Use indexing API or wait for quick background indexing."
                ),
            },
        ) from exc
    except WikiScopeError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "scope_not_found", "detail": str(exc)},
        ) from exc

    pages_models = [_wiki_page_from_export_dict(p, repo) for p in result["pages"]]
    cache.put(repo, _QUICK_SCOPE, body.mode, gv, pages_models)
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


@wiki_router.post("/search", response_model=None)
async def wiki_search(
    body: WikiSearchBody,
    search_svc: WikiSearchService = Depends(get_wiki_search_dep),
) -> dict[str, Any]:
    result = await search_svc.search(
        repository=body.repository,
        query=body.query,
        mode=body.mode,
        limit=body.limit,
        min_score=body.min_score,
        scope=body.scope,
    )
    return _search_response_to_json(result)


@wiki_router.post("/ask", response_model=None)
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
            ):
                event = str(ev.get("event", "message"))
                payload = json.dumps(ev.get("data") or {})
                yield f"event: {event}\ndata: {payload}\n\n"
        except Exception as exc:
            err = json.dumps({"error": "ask_failed", "detail": str(exc)})
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@wiki_router.post("/{repository}/analyze-impact", response_model=None)
async def analyze_pr_impact(
    repository: str,
    body: AnalyzeImpactBody,
    request: Request,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Analyze the impact of changed files on Wiki pages.

    Pure data API — returns affected Wiki pages and impact levels.
    External PR Bot services call this API and compose their own comments.
    """
    if not body.changed_files:
        return {
            "affected_pages": [],
            "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
        }

    graph_svc = get_graph_query_dep(request)

    try:
        await wiki_svc.ensure_repository(repository)
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

    changed_payload = [{"path": f.path, "status": f.status} for f in body.changed_files]
    try:
        return await graph_svc.analyze_pr_impact(
            repository=repository,
            changed_files=changed_payload,
        )
    except Exception as exc:
        log.exception(
            "analyze_pr_impact graph query failed",
            repository=repository,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "graph_query_failed",
                "detail": "graph_query_failed",
            },
        ) from exc


@wiki_router.get("/{repository}/pages", response_model=None)
async def wiki_list_pages(
    repository: str,
    scope: str | None = None,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    scope_raw = scope.strip() if scope else "repo"
    try:
        parse_scope(scope_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_scope", "detail": _invalid_scope_detail(exc)},
        ) from exc
    try:
        bundle = await svc.generate(repository, scope_raw, "structure", "json")
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

    structure = bundle.get("structure") or {}
    root = structure.get("root") or {}
    scopes = _scopes_flat_from_structure_root(root)
    pages_raw: list[dict[str, Any]] = list(bundle.get("pages") or [])
    out: list[dict[str, str]] = []
    for i, p in enumerate(pages_raw):
        sc = scopes[i] if i < len(scopes) else "repo"
        out.append(
            {
                "path": str(p.get("path", "")),
                "title": str(p.get("title", "")),
                "scope": sc,
            }
        )
    return {"pages": out, "total": len(out)}


@wiki_router.get("/{repository}/pages/{wiki_page_path:path}", response_model=None)
async def wiki_get_page_detail(
    repository: str,
    wiki_page_path: str,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    decoded_path = unquote(wiki_page_path).lstrip("/")
    try:
        bundle = await svc.generate(repository, "repo", "structure", "json")
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

    for p in bundle.get("pages") or []:
        if str(p.get("path", "")) != decoded_path:
            continue
        ctx = _wiki_page_detail_context(repository, p)
        return {
            "path": str(p.get("path", "")),
            "title": str(p.get("title", "")),
            "content": str(p.get("content", "")),
            "diagrams": p.get("diagrams") or [],
            "source_locations": p.get("source_locations") or [],
            "method_locations": p.get("method_locations") or [],
            "context": ctx,
        }

    raise HTTPException(
        status_code=404,
        detail={"error": "page_not_found", "detail": f"No wiki page at path {decoded_path!r}"},
    )
