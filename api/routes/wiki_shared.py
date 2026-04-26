"""Shared wiki route dependencies, helpers, and side-effect-free utilities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import Depends, Request
from store.wiki_feedback_store import WikiFeedbackStore
from store.wiki_store import WikiStore
from wiki.ask import WikiAskService
from wiki.cache import WikiCache
from wiki.deep_research import DeepResearchService
from wiki.exporter import WikiExporter
from wiki.memory_loop import MemoryLoop
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
)
from wiki.search import SearchResponse, WikiSearchService
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.wiki_docs_exporter import WikiDocsExporter
from wiki.lint import WikiLintService
from query.graph_query import GraphQueryService
from api.exceptions import KbServiceUnavailable
from log import get_logger
from api.models.wiki_models import WikiGenerateBody
from wiki.task_registry import WIKI_TASK_TTL_SEC, WikiTaskRegistry
from wiki.structure_planner import WikiScopeError

# Re-export for test patches and compatibility
__all__ = [
    "WIKI_TASK_TTL_SEC",
    "WikiTaskRegistry",
    "get_wiki_service_dep",
    "get_wiki_store_dep",
    "get_wiki_search_dep",
    "get_wiki_ask_dep",
    "get_wiki_deep_research_dep",
    "get_wiki_memory_loop_dep",
    "get_graph_query_dep",
    "get_task_registry_dep",
    "get_wiki_generation_sem",
    "get_wiki_cache_dep",
    "get_wiki_docs_exporter_dep",
    "get_wiki_lint_service_dep",
    "get_wiki_feedback_store_dep",
    "_maybe_call",
    "_wiki_page_from_export_dict",
    "_search_response_to_json",
    "_indexed_repository_names",
    "_page_type_to_scope",
    "_wiki_structure_from_pages",
    "_invalid_scope_detail",
    "_run_wiki_task",
    "_run_wiki_quick_task",
    "_GLOBAL_SEARCH_MAX_REPOS",
    "_GLOBAL_SEARCH_CONCURRENCY",
    "_QUICK_SCOPE",
    "_QUICK_FORMAT",
    "log",
]

log = get_logger(__name__)

_GLOBAL_SEARCH_MAX_REPOS = 50
_GLOBAL_SEARCH_CONCURRENCY = 10

_QUICK_SCOPE = "repo"
_QUICK_FORMAT = "json"


def get_route_settings() -> Any:
    """Read settings from ``api.routes.wiki_routes.get_settings`` so tests can patch the wiki routes module."""
    from api.routes import wiki_routes

    return wiki_routes.get_settings()


async def get_wiki_service_dep(request: Request) -> WikiService:
    factory = getattr(request.app.state, "wiki_service_factory", None)
    if callable(factory):
        out = factory()
        if asyncio.iscoroutine(out):
            return await out
        return out  # type: ignore[no-any-return]
    raise KbServiceUnavailable("Wiki generation is not configured")


def get_wiki_store_dep(request: Request) -> Any:
    """Get FalkorDB store for reading persisted WikiPage nodes."""
    store = getattr(request.app.state, "wiki_store", None)
    if store is None:
        raise KbServiceUnavailable("Graph store not configured")
    return store


async def get_wiki_search_dep(request: Request) -> WikiSearchService:
    svc = getattr(request.app.state, "wiki_search_service", None)
    if svc is None:
        raise KbServiceUnavailable("Wiki search is not configured")
    return svc


async def get_wiki_ask_dep(request: Request) -> WikiAskService:
    svc = getattr(request.app.state, "wiki_ask_service", None)
    if svc is None:
        raise KbServiceUnavailable("Wiki ask is not configured")
    return svc


def get_wiki_deep_research_dep(request: Request) -> DeepResearchService:
    svc = getattr(request.app.state, "wiki_deep_research_service", None)
    if svc is None:
        raise KbServiceUnavailable("Deep research is not configured")
    return svc


def get_wiki_memory_loop_dep(request: Request) -> MemoryLoop | None:
    return getattr(request.app.state, "wiki_memory_loop", None)


def get_graph_query_dep(request: Request) -> GraphQueryService:
    """Resolve graph query service; use with ``Depends`` when the graph is required for every request."""
    gq = getattr(request.app.state, "graph_query_service", None)
    if gq is None:
        raise KbServiceUnavailable("Graph query is not configured")
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
        raise KbServiceUnavailable("Wiki lint is not configured")
    out = factory()
    if asyncio.iscoroutine(out):
        return await out
    return out  # type: ignore[no-any-return]


def get_wiki_feedback_store_dep(request: Request) -> WikiFeedbackStore:
    st = getattr(request.app.state, "wiki_feedback_store", None)
    if st is None:
        raise KbServiceUnavailable("Wiki feedback is not configured")
    return st


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
        raise KbServiceUnavailable("Service registry is not configured")
    kb = await registry.get_service("default")
    from api.routes import wiki_routes

    queries = wiki_routes.GraphQueryRepository(kb.store)
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
