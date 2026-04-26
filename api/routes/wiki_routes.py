"""FastAPI routes for wiki generation (sync, SSE streaming, async tasks)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth import Role, require_role
from config import get_settings
from log import get_logger
from query.graph_query import GraphQueryService
from store.graph_queries import GraphQueryRepository
from store.wiki_store import WikiStore
from git_manager import normalize_repo_name
from utils.git_utils import looks_like_git_url
from wiki.ask import WikiAskService
from wiki.memory_loop import MemoryLoop
from wiki.quality_score import WikiQualityScorer
from wiki.coverage_analyzer import WikiCoverageAnalyzer
from wiki.cache import WikiCache
from wiki.exporter import WikiExporter
from wiki.wiki_docs_exporter import WikiDocsExporter, export_result_to_dict
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
from wiki.lint import WikiLintService
from wiki.search import SearchResponse, WikiSearchService
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.suggested_questions import PageContext, SuggestedQuestionsGenerator
from wiki.structure_planner import WikiScopeError

log = get_logger(__name__)

WIKI_TASK_TTL_SEC = 30 * 60

_GLOBAL_SEARCH_MAX_REPOS = 50
_GLOBAL_SEARCH_CONCURRENCY = 10


class WikiTaskRegistry:
    """In-memory wiki generation tasks. Entries expire after WIKI_TASK_TTL_SEC for bounded memory use."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self._created: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        removed = [tid for tid, ts in self._created.items() if now - ts > WIKI_TASK_TTL_SEC]
        for tid in removed:
            self.tasks.pop(tid, None)
            self._created.pop(tid, None)

    def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        self._prune()
        self.tasks[task_id] = record
        self._created[task_id] = time.monotonic()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self._prune()
        return self.tasks.get(task_id)


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


class WikiGlobalSearchBody(BaseModel):
    """Cross-repository wiki search (all indexed repos unless ``repositories`` is set)."""

    query: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")
    limit: int = Field(default=30, ge=1, le=200)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    repositories: list[str] | None = Field(
        default=None,
        description="Optional allow-list of repository names (must be indexed).",
    )


class BusinessWikiGenerateBody(BaseModel):
    business_id: str = Field(default="default", min_length=1)
    language: str = Field(default="en", pattern="^(en|zh)$")
    llm_provider: str | None = None


class WikiAskBody(BaseModel):
    repository: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    scope: str | None = None
    conversation_id: str | None = None
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")
    record_memory: bool = False
    business_id: str | None = Field(
        default=None,
        description="When set with record_memory, persists Q&A under this business id",
    )


class WikiQaRecordBody(BaseModel):
    business_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    source_pages: list[str] = Field(default_factory=list)


class WikiLintBody(BaseModel):
    scope: str = Field(default="all", description="Lint filter: 'all' or wiki scope (repo, module:..., class:...).")


class WikiExportPreviewBody(BaseModel):
    target_dir: str = Field(..., min_length=1, description="Directory under which wiki markdown files are written.")
    include_auto_generated_marker: bool = True


class WikiExportExecuteBody(BaseModel):
    target_dir: str = Field(..., min_length=1)
    selected_files: list[str] | None = Field(
        default=None,
        description="If set, only these wiki paths are written (create/update). If null, all pending create/update from preview.",
    )


class AnalyzeImpactFile(BaseModel):
    path: str
    status: str = Field(pattern="^(added|modified|removed|renamed)$")


class AnalyzeImpactBody(BaseModel):
    changed_files: list[AnalyzeImpactFile]


class ChunkIndexBody(BaseModel):
    repository: str = Field(..., min_length=1)


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


def get_wiki_store_dep(request: Request) -> Any:
    """Get FalkorDB store for reading persisted WikiPage nodes."""
    store = getattr(request.app.state, "wiki_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )
    return store


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


def get_wiki_memory_loop_dep(request: Request) -> MemoryLoop | None:
    return getattr(request.app.state, "wiki_memory_loop", None)


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


def get_wiki_docs_exporter_dep(cache: WikiCache = Depends(get_wiki_cache_dep)) -> WikiDocsExporter:
    return WikiDocsExporter(wiki_cache=cache)


async def get_wiki_lint_service_dep(request: Request) -> WikiLintService:
    factory = getattr(request.app.state, "wiki_lint_service_factory", None)
    if not callable(factory):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "detail": "Wiki lint is not configured",
            },
        )
    out = factory()
    if asyncio.iscoroutine(out):
        return await out
    return out  # type: ignore[no-any-return]


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
        generated_at=meta_raw.get("generated_at"),
        enrichment_level=meta_raw.get("enrichment_level"),
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


async def _indexed_repository_names(
    request: Request,
    restrict: list[str] | None,
) -> list[str]:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "detail": "Service registry is not configured",
            },
        )
    kb = await registry.get_service("default")
    queries = GraphQueryRepository(kb.store)
    rows = await queries.list_repositories()
    names: list[str] = []
    for row in rows:
        name = row.get("repository")
        if name:
            names.append(str(name))
    out = sorted(set(names))
    if restrict:
        filt = {s.strip() for s in restrict if isinstance(s, str) and s.strip()}
        out = [n for n in out if n in filt]
    return out


def _page_type_to_scope(page_type: str | None, path: str) -> str:
    pt = page_type or ""
    if pt == "repo_overview":
        return "repo"
    if pt == "module_overview":
        slug = path.replace("modules/", "").replace(".md", "")
        return f"module:{slug}"
    name = path.replace("classes/", "").replace(".md", "")
    return f"class:{name}"


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
    log.warning("wiki invalid scope", error=msg)
    return "Invalid scope"


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
        rec["error"] = {
            "error": "repo_not_found",
            "detail": f"Repository '{exc.repository}' is not indexed.",
        }
    except WikiScopeError as exc:
        log.warning("wiki task scope error", error=str(exc))
        rec["status"] = "failed"
        rec["error"] = {"error": "scope_not_found", "detail": "The requested wiki scope could not be found."}
    except Exception:  # noqa: BLE001 — surface as failed task
        log.exception("wiki generation task failed")
        rec["status"] = "failed"
        rec["error"] = {"error": "generation_failed", "detail": "Wiki generation failed."}


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
        rec["error"] = {
            "error": "repo_not_found",
            "detail": f"Repository '{exc.repository}' is not indexed.",
        }
    except WikiScopeError as exc:
        log.warning("wiki quick task scope error", error=str(exc))
        rec["status"] = "failed"
        rec["error"] = {"error": "scope_not_found", "detail": "The requested wiki scope could not be found."}
    except Exception:  # noqa: BLE001
        log.exception("wiki quick generation task failed")
        rec["status"] = "failed"
        rec["error"] = {"error": "generation_failed", "detail": "Wiki generation failed."}


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
        log.warning("wiki generate scope error", error=str(exc))
        raise HTTPException(
            status_code=404,
            detail={
                "error": "scope_not_found",
                "detail": "The requested wiki scope could not be found.",
            },
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
    if not looks_like_git_url(git_url):
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
        log.warning("wiki quick scope error", error=str(exc))
        raise HTTPException(
            status_code=404,
            detail={
                "error": "scope_not_found",
                "detail": "The requested wiki scope could not be found.",
            },
        ) from exc

    pages_models = [_wiki_page_from_export_dict(p, repo) for p in result["pages"]]
    cache.put(repo, _QUICK_SCOPE, body.mode, gv, pages_models)
    return result


@wiki_router.get("/tasks/{task_id}")
async def wiki_task_status(
    task_id: str,
    registry: WikiTaskRegistry = Depends(get_task_registry_dep),
) -> dict[str, Any]:
    rec = registry.get_task(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail={"error": "task_not_found"})
    return rec


@wiki_router.get(
    "/events",
    response_model=None,
)
async def wiki_events_stream(
    business_id: str = Query(..., min_length=1),
) -> StreamingResponse:
    """SSE of wiki events for a business. EventSource may pass the API token as ``token`` (no header)."""
    log.debug("wiki_events_subscribe", business_id=business_id)

    async def events() -> Any:
        yield ": stream-open\n\n"
        while True:
            await asyncio.sleep(60.0)
            yield ": keepalive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


@wiki_router.post("/search/global", response_model=None)
async def wiki_search_global(
    body: WikiGlobalSearchBody,
    request: Request,
    search_svc: WikiSearchService = Depends(get_wiki_search_dep),
) -> dict[str, Any]:
    """Search wiki pages across all indexed repositories (parallel per-repo search)."""
    repo_names = await _indexed_repository_names(request, body.repositories)
    if not repo_names:
        return {
            "by_repository": {},
            "results": [],
            "query_expansion": {
                "original": body.query,
                "expanded_queries": [body.query],
                "terms": [],
            },
            "total": 0,
            "repositories_searched": [],
            "partial_errors": [],
        }

    repo_names = repo_names[:_GLOBAL_SEARCH_MAX_REPOS]
    n = len(repo_names)
    per_repo_limit = max(5, min(40, (body.limit * 2 + n - 1) // n))
    sem = asyncio.Semaphore(_GLOBAL_SEARCH_CONCURRENCY)

    async def _search_repo(repo: str) -> tuple[str, SearchResponse | None, str | None]:
        async with sem:
            try:
                resp = await search_svc.search(
                    repository=repo,
                    query=body.query,
                    mode=body.mode,
                    limit=per_repo_limit,
                    min_score=body.min_score,
                    scope=None,
                )
                return repo, resp, None
            except Exception:  # noqa: BLE001 — aggregate per-repo failures
                log.warning("wiki_global_search_repo_failed", repository=repo, exc_info=True)
                return repo, None, "Search temporarily unavailable for this repository."

    raw = await asyncio.gather(*[_search_repo(r) for r in repo_names])

    partial_errors: list[dict[str, str]] = []
    merged_rows: list[dict[str, Any]] = []
    expansion: dict[str, Any] | None = None

    for repo, resp, err in raw:
        if err is not None:
            partial_errors.append({"repository": repo, "detail": err})
            continue
        if resp is None:
            continue
        if expansion is None:
            expansion = resp.query_expansion
        for hit in resp.results:
            row = asdict(hit)
            ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
            ctx = {**ctx, "repository": repo}
            row["context"] = ctx
            merged_rows.append(row)

    merged_rows.sort(key=lambda r: float(r.get("score", 0.0)), reverse=True)
    limited = merged_rows[: body.limit]

    by_repository: dict[str, list[dict[str, Any]]] = {}
    for row in limited:
        rname = str((row.get("context") or {}).get("repository") or "")
        by_repository.setdefault(rname, []).append(row)

    qexp: dict[str, Any] = (
        expansion
        if expansion is not None
        else {
            "original": body.query,
            "expanded_queries": [body.query],
            "terms": [],
        }
    )
    return {
        "by_repository": by_repository,
        "results": limited,
        "query_expansion": qexp,
        "total": len(limited),
        "repositories_searched": repo_names,
        "partial_errors": partial_errors,
    }


@wiki_router.get("/pages/by-path")
async def wiki_get_page_by_path(
    request: Request,
    business_id: str = Query(default="default"),
    path: str = Query(...),
) -> dict[str, Any]:
    """Fetch a wiki page by its path under a business space."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(status_code=503, detail="Wiki store unavailable")

    store = WikiStore(raw_store)
    result = await store.get_page_by_path(business_id, path)
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {path}")

    row = result.data[0]
    sources_raw = row.get("sources") or []
    source_locations: list[dict[str, Any]] = []
    for s in sources_raw:
        if isinstance(s, dict) and s.get("file_path"):
            source_locations.append(s)

    is_stale = "false"
    page_uid = str(row.get("uid") or "")
    settings = get_settings()
    if page_uid and settings.wiki.stale_detection_enabled:
        stale_count = await store.get_page_stale_source_count(page_uid)
        if stale_count > 0:
            is_stale = "true"

    return {
        "path": str(row.get("path") or ""),
        "title": str(row.get("title") or ""),
        "content": str(row.get("content") or ""),
        "diagrams": [],
        "source_locations": source_locations,
        "method_locations": [],
        "context": {
            "repository": str(row.get("repository") or ""),
            "page_type": str(row.get("page_type") or ""),
            "importance_tier": str(row.get("importance_tier") or ""),
            "uid": page_uid,
            "is_stale": is_stale,
        },
        "generated_at": str(row.get("generated_at") or "") or None,
    }


@wiki_router.get("/tree")
async def wiki_get_tree(
    request: Request,
    business_id: str = Query(default="default"),
    view: str = Query(default="business_domain"),
) -> dict[str, Any]:
    """Return the wiki tree structure for the given business and view type."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        return {"tree": [], "view_type": view, "business_id": business_id}

    store = WikiStore(raw_store)
    result = await store.get_wiki_tree(business_id, view)
    flat_nodes: list[dict[str, Any]] = []
    if result and result.result_set:
        for row in result.result_set:
            flat_nodes.append(
                {
                    "uid": row[0],
                    "title": row[1],
                    "label": row[2],
                    "depth": row[3],
                    "sort_order": row[4],
                    "path": row[5],
                    "page_type": row[6],
                    "parent_uid": row[7] if len(row) > 7 else None,
                    "children": [],
                }
            )

    node_map: dict[str, dict[str, Any]] = {n["uid"]: n for n in flat_nodes}
    roots: list[dict[str, Any]] = []
    for n in flat_nodes:
        parent_uid = n.pop("parent_uid", None)
        if parent_uid and parent_uid in node_map:
            node_map[parent_uid]["children"].append(n)
        else:
            roots.append(n)

    return {"tree": roots, "view_type": view, "business_id": business_id}


@wiki_router.post(
    "/business/generate",
    response_model=None,
    status_code=202,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def generate_business_wiki(
    body: BusinessWikiGenerateBody,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Trigger cross-repo business-level wiki generation."""
    try:
        result = await svc.generate_business_wiki(
            business_id=body.business_id,
            language=body.language,
            llm_provider=body.llm_provider,
        )
    except WikiScopeError as exc:
        log.warning("business wiki generate scope error", error=str(exc))
        raise HTTPException(
            status_code=400,
            detail={
                "error": "scope_error",
                "detail": "Invalid wiki scope or business configuration.",
            },
        ) from exc
    return result


class GitPushConfig(BaseModel):
    remote_url: str = Field(..., min_length=1)
    branch: str = Field(default="main")
    commit_message_prefix: str = Field(default="docs(wiki):")


class BusinessWikiExportBody(BaseModel):
    business_id: str = Field(default="default", min_length=1)
    format: str = Field(..., pattern="^(markdown|zip|git|obsidian|mkdocs)$")
    view_type: str = Field(default="business_domain", pattern="^(business_domain|code_structure|both)$")
    min_tier: str = Field(default="standard", pattern="^(core|standard|skeleton)$")
    git_config: GitPushConfig | None = None


@wiki_router.post(
    "/export",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def business_wiki_export(
    body: BusinessWikiExportBody,
    request: Request,
) -> Any:
    """Export business wiki in various formats (markdown, zip, git, obsidian, mkdocs)."""
    from wiki.business_wiki_exporter import BusinessWikiExporter
    from wiki.git_publisher import GitPublisher
    from wiki.mkdocs_exporter import MkDocsExporter
    from wiki.obsidian_exporter import ObsidianExporter

    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )

    wiki_store = WikiStore(raw_store)

    if body.format == "git" and body.git_config is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "git_config_required", "detail": "git_config is required for git format"},
        )

    if body.format == "obsidian":
        exporter: BusinessWikiExporter = ObsidianExporter(wiki_store)
    elif body.format == "mkdocs":
        exporter = MkDocsExporter(wiki_store)
    else:
        exporter = BusinessWikiExporter(wiki_store)

    plan = await exporter.build_export_plan(
        business_id=body.business_id,
        view=body.view_type,
        min_tier=body.min_tier,
    )

    if body.format == "git":
        cfg = body.git_config
        assert cfg is not None
        settings = get_settings()
        publisher = GitPublisher(
            remote_url=cfg.remote_url,
            branch=cfg.branch,
            commit_message_prefix=cfg.commit_message_prefix,
            author_name=settings.wiki.git_author_name,
            author_email=settings.wiki.git_author_email,
            git_token=settings.wiki.git_token,
        )
        file_map = {f.relative_path: f.content for f in plan.files}
        result = await publisher.publish(file_map, trigger_info=body.business_id)
        return {
            "format": "git",
            "business_id": body.business_id,
            "success": result.success,
            "files_added": result.files_added,
            "files_modified": result.files_modified,
            "files_deleted": result.files_deleted,
            "commit_sha": result.commit_sha,
            "annotations_found": result.annotations_found,
            "error": result.error,
        }

    if body.format == "zip":
        import io as _io
        import zipfile as _zipfile

        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
            for f in plan.files:
                zf.writestr(f.relative_path, f.content)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={body.business_id}-wiki.zip"},
        )

    return {
        "format": body.format,
        "business_id": body.business_id,
        "total_files": len(plan.files),
        "files": [{"path": f.relative_path, "is_index": f.is_index} for f in plan.files],
    }


@wiki_router.get("/pages/{page_uid:path}/references", response_model=None)
async def get_page_references(
    page_uid: str,
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    """Get outgoing and incoming references for a wiki page."""
    decoded = unquote(page_uid)
    ws = WikiStore(store)
    outgoing = await ws.get_wiki_page_references(decoded)
    incoming = await ws.get_wiki_page_back_references(decoded)
    return {
        "page_uid": decoded,
        "outgoing": outgoing.data if outgoing else [],
        "incoming": incoming.data if incoming else [],
    }


@wiki_router.get("/pages/{page_uid:path}/questions", response_model=None)
async def get_page_suggested_questions(
    page_uid: str,
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    """Graph-aware exploration questions for a wiki page (SOURCE_ENTITY + CALLS)."""
    decoded = unquote(page_uid)
    ws = WikiStore(store)
    raw = await ws.get_suggested_questions_context(decoded)
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "page_not_found", "detail": f"No wiki page for uid {decoded!r}"},
        )
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


@wiki_router.post("/chunks/index", response_model=None, dependencies=[Depends(require_role(Role.EDITOR))])
async def wiki_chunk_index(
    body: ChunkIndexBody,
    request: Request,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> JSONResponse:
    """Trigger batch embedding generation for Chunk nodes (RAG indexing)."""
    try:
        await svc.ensure_repository(body.repository)
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

    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )

    from store.wiki_store import WikiStore as _WikiStore
    from wiki.chunk_indexer import CodeChunkIndexer

    wiki_store_inst = _WikiStore(raw_store)
    indexer = CodeChunkIndexer(
        wiki_store_inst,
        raw_store,
        batch_size=get_settings().wiki.chunk_embedding_batch_size,
    )
    result = await indexer.index_all_chunks(body.repository)
    return JSONResponse(content=result)


@wiki_router.get("/coverage-report", response_model=None)
async def wiki_coverage_report(
    request: Request,
    business_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Return wiki documentation coverage analysis for a business."""
    settings = get_settings()
    if not settings.wiki.coverage_report_enabled:
        raise HTTPException(
            status_code=404,
            detail={"error": "feature_disabled", "detail": "Coverage report is disabled"},
        )

    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )

    wiki_store = WikiStore(raw_store)
    analyzer = WikiCoverageAnalyzer(wiki_store)
    report = await analyzer.analyze(
        business_id, include_stale=settings.wiki.stale_detection_enabled,
    )

    return report.to_dict()


@wiki_router.get("/quality-score", response_model=None)
async def wiki_quality_score(
    request: Request,
    business_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Aggregate quality score 0-100 (coverage, staleness, references, enrichment)."""
    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )
    ws = WikiStore(raw_store)
    scorer = WikiQualityScorer(ws)
    result = await scorer.compute_score(business_id)
    return result.to_dict()


@wiki_router.get("/references", response_model=None)
async def wiki_business_references(
    request: Request,
    business_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Wiki reference network for a business: pages and WIKI_REFERENCES edges (both ends in space)."""
    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )
    ws = WikiStore(raw_store)
    return await ws.get_business_wiki_references_graph(business_id)


@wiki_router.get("/qa", response_model=None)
async def wiki_list_qa(
    request: Request,
    business_id: str = Query(..., min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    """Paginated :WikiQA entries for a business."""
    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Graph store not configured"},
        )
    ws = WikiStore(raw_store)
    r = await ws.list_wiki_qa(business_id, skip, limit)
    return {"items": r.data or [], "skip": skip, "limit": limit, "total": await ws.count_wiki_qa(business_id)}


@wiki_router.post("/qa/record", response_model=None)
async def wiki_record_qa(
    body: WikiQaRecordBody,
    mem: MemoryLoop | None = Depends(get_wiki_memory_loop_dep),
) -> dict[str, Any]:
    """Store a Q&A pair (e.g. after wiki ask) as :WikiQA with embedding."""
    if mem is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "detail": "Wiki memory loop is not configured"},
        )
    uid = await mem.record(
        body.question, body.answer, list(body.source_pages), business_id=body.business_id,
    )
    return {"ok": True, "uid": uid}


@wiki_router.post("/{repository}/lint", response_model=None)
async def wiki_lint(
    repository: str,
    body: WikiLintBody | None = None,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
    lint_svc: WikiLintService = Depends(get_wiki_lint_service_dep),
) -> dict[str, Any]:
    """Run wiki health checks (staleness, orphans, broken links, coverage, outdated)."""
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
    scope = body.scope if body else "all"
    report = await lint_svc.lint(repository, scope=scope)
    return report.to_dict()


@wiki_router.post(
    "/{repository}/export/preview",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_export_preview(
    repository: str,
    body: WikiExportPreviewBody,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
    exporter: WikiDocsExporter = Depends(get_wiki_docs_exporter_dep),
) -> dict[str, Any]:
    """Preview wiki → markdown export for ``target_dir`` without writing files."""
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
    result = await exporter.preview_export(
        repository,
        body.target_dir,
        include_auto_generated_marker=body.include_auto_generated_marker,
    )
    return export_result_to_dict(result)


@wiki_router.post(
    "/{repository}/export/execute",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_export_execute(
    repository: str,
    body: WikiExportExecuteBody,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
    exporter: WikiDocsExporter = Depends(get_wiki_docs_exporter_dep),
) -> dict[str, Any]:
    """Write selected wiki pages as markdown under ``target_dir``."""
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
    result = await exporter.execute_export(repository, body.target_dir, selected_files=body.selected_files)
    return export_result_to_dict(result)


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


@wiki_router.get("/{repository}/enrichment-status", response_model=None)
async def wiki_enrichment_status(
    repository: str,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Return enrichment level counts for persisted wiki pages in the repository."""
    repo = normalize_repo_name(repository)
    try:
        return await wiki_svc.get_enrichment_status(repo)
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


@wiki_router.post(
    "/{repository}/enrich",
    response_model=None,
    status_code=202,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_enrich_trigger(
    repository: str,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Dry-run estimate: how many persisted wiki pages are at BASE and eligible for enrichment.

    Does not start async enrichment; enrichment runs during wiki generation when tiers exist.
    """
    repo = normalize_repo_name(repository)
    try:
        return await wiki_svc.trigger_enrichment(repo)
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


@wiki_router.get("/{repository}/pages", response_model=None)
async def wiki_list_pages(
    repository: str,
    scope: str | None = None,
    skip: int = Query(0, ge=0, description="Offset for paginated page listing"),
    limit: int = Query(50, ge=1, le=200, description="Max page rows per request"),
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    # ``scope`` is kept for OpenAPI/backward compatibility; listing reads all persisted pages.
    _ = scope
    result, total = await WikiStore(store).list_wiki_pages_paginated(
        repository, skip=skip, limit=limit,
    )
    pages = [
        {
            "path": r["path"],
            "title": r["title"],
            "scope": _page_type_to_scope(r.get("page_type"), str(r.get("path") or "")),
        }
        for r in result.data
    ]
    return {"pages": pages, "total": total}


@wiki_router.get("/{repository}/pages/{wiki_page_path:path}", response_model=None)
async def wiki_get_page_detail(
    repository: str,
    wiki_page_path: str,
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    decoded_path = unquote(wiki_page_path).lstrip("/")
    result = await WikiStore(store).get_wiki_page_detail(repository, decoded_path)
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "page_not_found",
                "detail": f"No wiki page at path {decoded_path!r}",
            },
        )
    row = result.data[0]
    wp = row.get("wp")
    props = dict(wp.properties) if hasattr(wp, "properties") else (wp if isinstance(wp, dict) else {})
    ctx = {"repository": repository, "module": "", "page": decoded_path}
    return {
        "path": props.get("path", ""),
        "title": props.get("title", ""),
        "content": props.get("content", ""),
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "context": ctx,
        "generated_at": props.get("generated_at"),
    }
