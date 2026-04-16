"""Knowledge Base Service — standalone FastAPI application.

Provides HTTP endpoints for code/document indexing and querying,
backed by FalkorDB graph database and sentence-transformers embeddings.
Supports multi-business isolation via independent FalkorDB graphs.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Self

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from auth import Role, TokenInfo, get_current_role, require_role, resolve_business_id, resolve_token
from config import get_settings
from indexer.task_manager import IndexTaskManager
from log import get_logger, setup_logging
from repo_registry import RepoRegistry
from scheduler import SyncScheduleConfig, SyncScheduler
from service import KnowledgeBaseService
from service_registry import ServiceRegistry
from store.graph_queries import GraphQueryRepository

log = get_logger(__name__)

_registry: ServiceRegistry | None = None
_task_manager: IndexTaskManager | None = None
_repo_registry: RepoRegistry | None = None
_scheduler: SyncScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _registry, _task_manager, _repo_registry, _scheduler
    settings = get_settings()
    setup_logging(level=settings.log_level)
    log.info("kb_service_starting", host=settings.host, port=settings.port)

    _registry = ServiceRegistry(settings)
    _task_manager = IndexTaskManager()
    data_dir = Path(settings.git.clone_base_path).resolve().parent
    _repo_registry = RepoRegistry(str(data_dir))
    await _registry.start()

    _scheduler = SyncScheduler(
        _registry,
        settings,
        repo_registry=_repo_registry,
        schedule_store_path=data_dir / "sync_schedules.json",
    )
    await _scheduler.start()

    app.state.registry = _registry
    app.state.scheduler = _scheduler
    log.info("kb_service_started")
    yield

    log.info("kb_service_stopping")
    if _scheduler:
        await _scheduler.stop()
    if _registry:
        await _registry.stop()
    log.info("kb_service_stopped")


def _resolve_token(authorization: str | None = Header(default=None)) -> TokenInfo | None:
    return resolve_token(authorization)


def _get_effective_business_id(
    token_info: TokenInfo | None = Depends(_resolve_token),
    x_business_id: str = Header(default="default"),
) -> str:
    return resolve_business_id(token_info, x_business_id)


async def _get_service(
    business_id: str = Depends(_get_effective_business_id),
) -> KnowledgeBaseService:
    if _registry is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    try:
        return await _registry.get_service(business_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


viewer_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_role(Role.VIEWER))])
editor_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_role(Role.EDITOR))])
admin_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_role(Role.ADMIN))])
public_router = APIRouter(prefix="/api/v1")


def _looks_like_git_url(value: str) -> bool:
    """Heuristic: detect if a string is a git URL rather than a local path."""
    if value.startswith(("http://", "https://", "git@", "ssh://")):
        return True
    if value.endswith(".git"):
        return True
    return False


class SemanticSearchRequest(BaseModel):
    query: str
    k: int = Field(default=10, ge=1, le=50)
    entity_type: str = Field(default="all", pattern="^(all|function|class|document)$")
    repository: str | None = None


class GraphQueryRequest(BaseModel):
    query_type: str
    name: str = ""
    file: str = ""
    depth: int = Field(default=3, ge=1, le=10)
    direction: str = Field(default="downstream", pattern="^(upstream|downstream|children|parents)$")
    cypher: str = ""
    entity_type: str = Field(default="any", pattern="^(function|class|any)$")


class HybridSearchRequest(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=20)
    expand_depth: int = Field(default=2, ge=1, le=5)


class DeepSearchRequest(BaseModel):
    query: str
    max_iterations: int = Field(default=3, ge=1, le=5)
    include_code: bool = True


class BusinessSearchRequest(BaseModel):
    query: str
    search_type: str = Field(default="all", pattern="^(flow|concept|all)$")
    k: int = Field(default=5, ge=1, le=20)
    include_code: bool = True


class IndexRequest(BaseModel):
    directory: str = ""
    git_url: str = ""
    branch: str | None = None
    mode: str = Field(default="full", pattern="^(full|incremental)$")
    base_ref: str = "HEAD~1"
    head_ref: str = "HEAD"
    repository: str | None = None


class IndexFileRequest(BaseModel):
    file_path: str
    content: str
    repository: str | None = None


class IndexFilesRequest(BaseModel):
    files: list[IndexFileRequest]
    repository: str | None = None


class EnrichRequest(BaseModel):
    """对已索引的 Function/Class 批量补全 business_summary（不重新解析代码）。"""

    repository: str = Field(..., min_length=1, description="仓库名称")
    force: bool = False


class GraphExploreRequest(BaseModel):
    name: str = ""
    depth: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=100, ge=1, le=500)


class ImpactAnalysisRequest(BaseModel):
    changed_functions: list[str] = Field(..., min_length=1)
    max_depth: int = Field(default=5, ge=1, le=50)


class ReviewContextRequest(BaseModel):
    diff_text: str | None = Field(
        default=None,
        description="Unified diff text from git diff (optional if branch and repo_path are set)",
    )
    branch: str | None = Field(default=None, description="Branch to compare against base_branch")
    base_branch: str | None = Field(
        default=None,
        description='Base branch for git diff (defaults to "master" when using branch/repo_path)',
    )
    repo_url: str | None = Field(
        default=None,
        description="Remote git URL (reserved for future server-side fetch; validated when set)",
    )
    repo_path: str | None = Field(
        default=None,
        description="Local filesystem path to the git repository root (required with branch when diff_text is omitted)",
    )
    repository: str | None = None
    max_depth: int = Field(default=3, ge=1, le=20)

    @model_validator(mode="after")
    def validate_diff_source(self) -> Self:
        has_diff = self.diff_text is not None and self.diff_text.strip() != ""
        b = (self.branch or "").strip()
        p = (self.repo_path or "").strip()
        has_branch_path = bool(b) and bool(p)
        if not has_diff and not has_branch_path:
            raise ValueError(
                "Provide either non-empty diff_text, or both branch and repo_path",
            )
        ru = (self.repo_url or "").strip()
        if ru and not _looks_like_git_url(ru):
            raise ValueError("repo_url does not look like a valid git remote URL")
        return self


class SmartContextRequest(BaseModel):
    entity_name: str = Field(..., min_length=1)
    entity_type: str = Field(default="function", pattern="^(function|class)$")
    repository: str | None = None


class MCPToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)

_ARCHITECTURE_LAYERS = frozenset({
    "presentation",
    "business",
    "data_access",
    "rpc",
    "messaging",
    "infrastructure",
    "model",
})


async def _resolve_canonical_repository_for_git(
    git_url: str,
    requested_name: str | None,
    registry: RepoRegistry,
    queries: GraphQueryRepository,
) -> tuple[str, str | None]:
    """Pick a single repository name for a remote URL (registry + graph + normalize).

    Returns ``(canonical_name, user_visible_warning_or_none)``.
    """
    from git_manager import normalize_repo_name

    requested_stripped = requested_name.strip() if requested_name else None
    candidate = requested_stripped or normalize_repo_name(git_url)
    if not candidate:
        tail = git_url.strip().rstrip("/").split("/")[-1]
        if tail.endswith(".git"):
            tail = tail[:-4]
        candidate = tail or git_url.strip()

    existing = registry.get_canonical_name(git_url)
    if existing is None:
        existing = await queries.find_repository_by_git_url(git_url)

    if existing:
        if candidate != existing:
            return existing, (
                f"已忽略仓库名 '{candidate}'，沿用同一 git URL 已登记或已索引名称 '{existing}'"
            )
        return existing, None

    return candidate, None


@viewer_router.post("/search")
async def semantic_search(
    req: SemanticSearchRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    from query.hybrid_query import _extract_identifiers

    if req.entity_type == "function":
        sem_coro = svc.semantic_query.search_functions(req.query, k=req.k)
    elif req.entity_type == "class":
        sem_coro = svc.semantic_query.search_classes(req.query, k=req.k)
    elif req.entity_type == "document":
        sem_coro = svc.semantic_query.search_documents(req.query, k=req.k)
    else:
        sem_coro = svc.semantic_query.search_all(req.query, k=req.k)

    fqn_matches = _FQN_RE.findall(req.query)
    if fqn_matches:
        identifiers = []
        for fqn in fqn_matches:
            clean = fqn.split("(")[0].strip()
            identifiers.append(clean)
    else:
        identifiers = _extract_identifiers(req.query)
        if not identifiers:
            identifiers = [req.query.strip()]

    async def _kw_search() -> list[dict[str, Any]]:
        all_hits: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ident in identifiers[:3]:
            hits = await svc.store.keyword_search(ident, k=req.k)
            for hit in hits:
                uid = hit.get("uid", "")
                if uid and uid not in seen:
                    seen.add(uid)
                    all_hits.append(hit)
        return all_hits

    sem_result, kw_hits = await asyncio.gather(sem_coro, _kw_search())

    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for hit in kw_hits:
        key = f"{hit.get('name', '')}:{hit.get('file', '')}:{hit.get('line', '')}"
        if key not in seen_keys:
            seen_keys.add(key)
            merged.append({
                "type": hit.get("type", ""),
                "name": hit.get("name", ""),
                "file": hit.get("file", ""),
                "line": hit.get("line", 0),
                "score": hit.get("score", 1.0),
                "signature": hit.get("signature", ""),
                "docstring": hit.get("docstring", ""),
                "uid": hit.get("uid", ""),
                "fqn": hit.get("fqn", ""),
            })

    for m in sem_result.matches:
        key = f"{m.get('name', '')}:{m.get('file', '')}:{m.get('line', '')}"
        if key not in seen_keys:
            seen_keys.add(key)
            merged.append(m)

    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = merged[:req.k]
    return {"matches": top, "total": len(top), "query": req.query}


@viewer_router.get("/search/architecture")
async def search_architecture(
    layer: str,
    repository: str | None = None,
    limit: int = 50,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    if layer not in _ARCHITECTURE_LAYERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid layer; expected one of: {', '.join(sorted(_ARCHITECTURE_LAYERS))}",
        )
    lim = max(1, min(limit, 500))
    try:
        queries = GraphQueryRepository(svc.store)
        classes = await queries.search_classes_by_architecture_layer(layer, repository, lim)
        return {
            "layer": layer,
            "repository": repository,
            "limit": lim,
            "classes": classes,
            "total": len(classes),
        }
    except Exception as exc:
        log.error("search_architecture_failed", layer=layer, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@viewer_router.get("/quality/{entity_uid:path}")
async def get_code_quality(
    entity_uid: str,
    entity_type: str | None = Query(
        default=None,
        description="Optional: restrict to 'function' or 'class' (default: match either)",
    ),
    svc: KnowledgeBaseService = Depends(_get_service),
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@viewer_router.post("/graph")
async def graph_query(
    req: GraphQueryRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    return await svc.mcp_handler.handle_rag_graph(req.model_dump())


@viewer_router.post("/hybrid")
async def hybrid_search(
    req: HybridSearchRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    result = await svc.hybrid_query.search_with_context(req.query, k=req.k, expand_depth=req.expand_depth)
    return {
        "semantic_matches": result.semantic_matches,
        "graph_context": result.graph_context,
        "total": result.total,
        "query": result.query_text,
    }


@viewer_router.post("/deep-search")
async def deep_search(
    req: DeepSearchRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
    business_id: str = Depends(_get_effective_business_id),
) -> dict[str, Any]:
    if not svc.deep_search:
        raise HTTPException(
            status_code=501,
            detail="LLM not configured, deep search unavailable",
        )
    return await svc.deep_search.search(
        req.query,
        max_iterations=req.max_iterations,
        include_code=req.include_code,
        tenant_id=business_id,
    )


@viewer_router.post("/business/search")
async def business_search(
    req: BusinessSearchRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    if req.search_type in ("flow", "all"):
        flow_result = await svc.semantic_query.search_business_flows(
            req.query, req.k
        )
        results["flows"] = flow_result.matches
    if req.search_type in ("concept", "all"):
        concept_result = await svc.semantic_query.search_business_concepts(
            req.query, req.k
        )
        results["concepts"] = concept_result.matches

    if req.include_code:
        for flow in results.get("flows", []):
            flow_name = flow.get("name", "")
            if flow_name:
                code_result = await svc.graph_query.find_business_flow(flow_name, k=5)
                flow["code_locations"] = code_result.data

    return {"status": "success", "results": results}


@viewer_router.get("/index/tasks")
async def list_index_tasks() -> dict[str, Any]:
    if _task_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    tasks = _task_manager.list_tasks()
    return {"tasks": [t.to_dict() for t in tasks], "total": len(tasks)}


@viewer_router.get("/index/tasks/{task_id}")
async def get_index_task(task_id: str) -> dict[str, Any]:
    if _task_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    task = _task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@editor_router.post("/index")
async def trigger_index(
    req: IndexRequest,
    business_id: str = Depends(_get_effective_business_id),
) -> dict[str, Any]:
    if _task_manager is None or _registry is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    if not req.directory and not req.git_url:
        raise HTTPException(
            status_code=422,
            detail="Either 'directory' or 'git_url' must be provided",
        )

    if not req.git_url and req.directory and _looks_like_git_url(req.directory):
        req = req.model_copy(update={"git_url": req.directory, "directory": ""})

    task = _task_manager.create_task(
        mode=req.mode,
        directory=req.directory or req.git_url,
        repository=req.repository,
        business_id=business_id,
    )

    asyncio.create_task(_run_index_task(task.task_id, req, business_id))

    return {
        "task_id": task.task_id,
        "status": task.status,
        "mode": req.mode,
        "directory": req.directory,
        "git_url": req.git_url or None,
    }


@editor_router.post("/enrich")
async def trigger_enrich(
    req: EnrichRequest,
    business_id: str = Depends(_get_effective_business_id),
) -> dict[str, Any]:
    """对已入库实体异步执行 LLM 业务摘要补全，可通过任务接口查询进度。"""
    if _task_manager is None or _registry is None:
        raise HTTPException(status_code=503, detail="服务未就绪")

    task = _task_manager.create_task(
        mode="enrich",
        directory="",
        repository=req.repository,
        business_id=business_id,
    )

    asyncio.create_task(_run_enrich_task(task.task_id, req, business_id))

    return {
        "task_id": task.task_id,
        "status": task.status,
        "mode": "enrich",
        "repository": req.repository,
        "force": req.force,
    }


async def _run_enrich_task(task_id: str, req: EnrichRequest, business_id: str) -> None:
    """后台执行仅摘要补全。"""
    if _task_manager is None or _registry is None:
        return

    _task_manager.mark_running(task_id)
    progress_cb = _task_manager.make_progress_callback(task_id)

    try:
        svc = await _registry.get_service(business_id)

        if not svc.indexer.enrichment_available:
            _task_manager.mark_failed(
                task_id,
                "未配置 LLM 或网关摘要能力，无法执行补全。请开启 LLM 并确保网关摘要可用。",
            )
            return

        queries = GraphQueryRepository(svc.store)
        entities = await queries.get_enrichable_entities(req.repository, req.force)

        repo_id = f"enrich:{req.repository}"

        enriched = await svc.indexer.enrich_only(
            entities,
            repo_id,
            progress_callback=progress_cb,
        )

        _task_manager.mark_completed(
            task_id,
            {
                "enriched": enriched,
                "candidates": len(entities),
                "repository": req.repository,
                "force": req.force,
            },
        )
    except Exception as exc:
        log.error("enrich_task_failed", task_id=task_id, error=str(exc))
        _task_manager.mark_failed(task_id, str(exc))


async def _run_index_task(task_id: str, req: IndexRequest, business_id: str) -> None:
    """Background coroutine that runs the actual indexing work.

    When ``git_url`` is provided, the task first clones/pulls the repo
    from a (potentially private) GitLab instance, then indexes the
    resulting local directory.
    """
    if _task_manager is None or _registry is None:
        return

    _task_manager.mark_running(task_id)
    progress_cb = _task_manager.make_progress_callback(task_id)

    try:
        svc = await _registry.get_service(business_id)

        directory = req.directory
        repository = req.repository

        if req.git_url:
            from config import get_settings
            from git_manager import GitManager

            git_cfg = get_settings().git
            if not git_cfg.gitlab_url and not git_cfg.gitlab_token:
                log.warning("git_url_provided_but_no_git_config")

            mgr = GitManager(git_cfg)
            clone_result = await mgr.ensure_repo(req.git_url, branch=req.branch)
            log.info("git_ensure_repo_result", task_id=task_id, **clone_result)

            if clone_result["status"] in ("clone_failed", "pull_failed"):
                _task_manager.mark_failed(
                    task_id,
                    f"Git operation failed: {clone_result.get('detail', '')}",
                )
                return

            directory = clone_result["directory"]

            if _repo_registry is None:
                _task_manager.mark_failed(task_id, "Repository registry not initialized")
                return

            queries_pre = GraphQueryRepository(svc.store)
            canonical, name_warn = await _resolve_canonical_repository_for_git(
                req.git_url,
                req.repository,
                _repo_registry,
                queries_pre,
            )
            if name_warn:
                log.warning(
                    "repository_name_canonicalized",
                    task_id=task_id,
                    detail=name_warn,
                    git_url=req.git_url,
                )
            repository = canonical

            if clone_result["status"] == "cloned" and req.mode == "incremental":
                log.info(
                    "auto_fallback_to_full",
                    task_id=task_id,
                    reason="first_clone_no_prior_index",
                )
                req = req.model_copy(update={"mode": "full"})

            if progress_cb:
                progress_cb(f"Repository ready at {directory} (status: {clone_result['status']})")

        if not directory:
            _task_manager.mark_failed(task_id, "No directory resolved for indexing")
            return

        effective_mode = req.mode
        if effective_mode == "incremental" and repository:
            queries = GraphQueryRepository(svc.store)
            sample = await queries.get_repository_sample_file(repository)
            if sample is None:
                log.info(
                    "auto_fallback_to_full",
                    task_id=task_id,
                    reason="repository_not_indexed_yet",
                    repository=repository,
                )
                effective_mode = "full"

        args = req.model_dump()
        args["directory"] = directory
        args["mode"] = effective_mode
        if repository:
            args["repository"] = repository

        result = await svc.mcp_handler.handle_rag_index(args, progress_callback=progress_cb)

        if result.get("error"):
            _task_manager.mark_failed(task_id, result["error"])
            return

        cross_repo_stats: dict[str, Any] | None = None
        try:
            from indexer.cross_repo_enricher import CrossRepoEnricher

            enricher = CrossRepoEnricher(svc.store)
            cross_repo_stats = await enricher.enrich_all()
            log.info(
                "cross_repo_enrichment_after_index",
                task_id=task_id,
                **{k: v for k, v in (cross_repo_stats or {}).items()},
            )
        except Exception as exc:
            log.error("cross_repo_enrichment_failed", task_id=task_id, error=str(exc))
            cross_repo_stats = {"error": str(exc)}

        merged_result = dict(result)
        merged_result["cross_repo_enrichment"] = cross_repo_stats

        if repository:
            queries = GraphQueryRepository(svc.store)
            await queries.tag_unowned_nodes(
                repository,
                directory=directory,
                git_url=req.git_url or None,
            )

        if req.git_url and repository and _repo_registry:
            _repo_registry.register(req.git_url, repository)

        _task_manager.mark_completed(task_id, merged_result)
    except Exception as exc:
        log.error("index_task_failed", task_id=task_id, error=str(exc))
        _task_manager.mark_failed(task_id, str(exc))


@editor_router.post("/index/files")
async def index_files(
    req: IndexFilesRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Index files by directly passing their content — no local directory needed.

    Useful for CI pipelines that provide file content from git diff,
    or when the KB service doesn't have access to the repository.
    """

    total_nodes = 0
    total_edges = 0
    total_embeds = 0

    for file_req in req.files:
        repo = file_req.repository or req.repository
        stats = await svc.indexer.index_file(file_req.file_path, file_req.content)
        total_nodes += stats.get("nodes", 0)
        total_edges += stats.get("edges", 0)
        total_embeds += stats.get("embeddings", 0)

        if repo:
            await _tag_repository(svc, file_req.file_path, repo)

        ext = file_req.file_path.rsplit(".", 1)[-1].lower() if "." in file_req.file_path else ""
        if ext in {"md", "markdown", "rst", "txt"}:
            doc = svc.doc_indexer.parse_document(file_req.file_path, file_req.content)
            doc_nodes, doc_edges = svc.doc_indexer.build_graph(doc)
            await svc.store.batch_upsert(doc_nodes, doc_edges)
            total_nodes += len(doc_nodes)
            total_edges += len(doc_edges)

            embeddable = [n for n in doc_nodes if n.properties.get("content")]
            if embeddable:
                items = [
                    {"name": n.properties.get("title", ""), "signature": "",
                     "docstring": "", "code_snippet": n.properties.get("content", "")}
                    for n in embeddable
                ]
                embeddings = await svc._embedding.generate_for_code(items)
                for node, emb in zip(embeddable, embeddings):
                    await svc.store.set_node_embedding(node.uid, node.label, emb)
                total_embeds += len(embeddings)

            if repo:
                for n in doc_nodes:
                    await _tag_repository(svc, n.properties.get("file", ""), repo)

    return {
        "indexed_files": len(req.files),
        "nodes": total_nodes,
        "edges": total_edges,
        "embeddings": total_embeds,
        "repository": req.repository,
    }


async def _tag_repository(svc: KnowledgeBaseService, file_path: str, repository: str) -> None:
    """Tag all nodes from a file with a repository label."""
    queries = GraphQueryRepository(svc.store)
    await queries.tag_nodes_with_repository(file_path, repository)


@viewer_router.get("/stats")
async def graph_stats(
    repository: str | None = None,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    stats = await svc.graph_query.get_graph_stats()
    if repository:
        queries = GraphQueryRepository(svc.store)
        stats["repository"] = repository
        stats["repository_nodes"] = await queries.get_repository_node_count(repository)
    return stats


@viewer_router.get("/repositories")
async def list_repositories(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """List all indexed repositories with node counts and optional git URL metadata."""
    queries = GraphQueryRepository(svc.store)
    repos = await queries.list_repositories()
    reg_by_repo: dict[str, dict[str, Any]] = {}
    if _repo_registry:
        for entry in _repo_registry.list_all():
            rname = entry.get("repository")
            if rname:
                reg_by_repo[str(rname)] = entry
    for row in repos:
        name = row.get("repository")
        if not name:
            continue
        reg = reg_by_repo.get(str(name))
        if reg:
            if not row.get("git_url") and reg.get("git_url"):
                row["git_url"] = reg["git_url"]
            row["last_indexed"] = reg.get("last_indexed")
    return {"repositories": repos, "total": len(repos)}


def _relative_file_path(file_path: str, repository: str | None) -> str:
    """Strip clone/base prefix from absolute paths so responses use repo-relative paths."""
    if not file_path:
        return file_path
    normalized = file_path.replace("\\", "/")
    if repository:
        marker = f"/{repository}/"
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx + len(marker) :]
    return normalized


@viewer_router.get("/documents")
async def list_documents(
    repository: str | None = None,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """List top-level document nodes with section metadata for sidebar navigation."""
    queries = GraphQueryRepository(svc.store)
    result = await queries.list_documents(repository)

    by_uid: dict[str, dict[str, Any]] = {}
    for r in result.data:
        uid = r.get("uid")
        if not uid:
            continue
        if uid not in by_uid:
            repo = r.get("repository")
            raw_file = r.get("file") or ""
            by_uid[uid] = {
                "file": _relative_file_path(raw_file, repo),
                "title": r.get("title") or r.get("name") or "",
                "repository": repo,
                "uid": uid,
                "content_hash": r.get("content_hash"),
                "sections": [],
            }
        sec_uid = r.get("sec_uid")
        if sec_uid:
            by_uid[uid]["sections"].append({
                "title": r.get("sec_name") or r.get("sec_title") or "",
                "uid": sec_uid,
                "start_line": r.get("sec_start_line"),
            })

    documents = sorted(
        by_uid.values(),
        key=lambda d: (d.get("repository") or "", d.get("file") or ""),
    )
    for d in documents:
        d["sections"].sort(key=lambda s: (s.get("start_line") is None, s.get("start_line") or 0))

    return {"documents": documents, "total": len(documents)}


_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.\s]")

def _infer_section_levels(sections: list[dict[str, Any]], file_path: str | None = None) -> None:
    """Infer heading levels from original file or numbered title patterns."""
    heading_levels: dict[str, int] = {}

    if file_path:
        try:
            fpath = Path(file_path)
            if fpath.is_file():
                raw = fpath.read_text(encoding="utf-8")
                for line in raw.split("\n"):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        hashes = len(stripped) - len(stripped.lstrip("#"))
                        title = stripped[hashes:].strip()
                        heading_levels[title] = hashes
        except OSError:
            pass

    if heading_levels:
        for s in sections:
            title = s.get("title", "")
            clean_title = title.rsplit(" > ", 1)[-1] if " > " in title else title
            if clean_title in heading_levels:
                s["level"] = heading_levels[clean_title]
        return

    prev_level = 2
    for i, s in enumerate(sections):
        title = s.get("title", "")
        m = _NUMBERED_HEADING_RE.match(title)
        if m:
            dots = m.group(1).count(".")
            s["level"] = 2 + dots
        elif i == 0:
            s["level"] = 1
        else:
            s["level"] = prev_level
        prev_level = s["level"]


@viewer_router.get("/documents/{doc_uid:path}")
async def get_document(
    doc_uid: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Return a root document and all section children with full section content."""
    queries = GraphQueryRepository(svc.store)
    result = await queries.get_document(doc_uid)
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")

    first = result.data[0]
    repo = first.get("repository")
    raw_file = first.get("file") or ""

    sections: list[dict[str, Any]] = []
    for r in result.data:
        suid = r.get("section_uid")
        if not suid:
            continue
        sections.append({
            "title": r.get("section_name") or r.get("section_title") or "",
            "content": r.get("content") or "",
            "start_line": r.get("start_line"),
            "uid": suid,
            "level": r.get("level"),
        })

    has_stored_levels = any(s.get("level") is not None for s in sections)
    if not has_stored_levels:
        _infer_section_levels(sections, file_path=first.get("file"))

    for s in sections:
        if s.get("level") is None:
            s["level"] = 2

    return {
        "title": first.get("title") or "",
        "file": _relative_file_path(raw_file, repo),
        "repository": repo,
        "sections": sections,
    }


@admin_router.delete("/index/{repository:path}")
async def delete_repository_index(
    repository: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Delete all indexed data for a specific repository."""
    queries = GraphQueryRepository(svc.store)
    deleted = await queries.delete_repository(repository)
    return {"repository": repository, "deleted_nodes": deleted}


@admin_router.get("/index/report/{repository:path}")
async def get_index_report(
    repository: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Get the last indexing quality report for a repository."""
    report = svc.incremental_indexer.get_last_report()
    if report is None:
        return {"repository": repository, "report": None, "message": "No indexing report available"}
    return {"repository": repository, "report": report.to_dict()}


@admin_router.post("/enrich/graph")
async def enrich_graph(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Run GraphEnricher on existing index data without re-parsing source files."""
    from indexer.graph_enricher import GraphEnricher

    enricher = GraphEnricher(svc.store)
    result = await enricher.enrich()
    return {"status": "completed", **result}


@admin_router.post("/enrich/cross-repo")
async def enrich_cross_repo(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Run cross-repo enrichment: RPC resolution, DI graph, Entity mapping."""
    from indexer.cross_repo_enricher import CrossRepoEnricher

    enricher = CrossRepoEnricher(svc.store)
    result = await enricher.enrich_all()
    return {"status": "completed", **result}


@editor_router.post("/review/context")
async def build_review_context(
    req: ReviewContextRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Build structured review context from a git diff for AI code review."""
    from query.agent_workflow import AgentWorkflowService

    workflow = AgentWorkflowService(svc.store)
    try:
        ctx = await workflow.build_review_context(
            diff_text=req.diff_text,
            repository=req.repository,
            max_depth=req.max_depth,
            repo_path=req.repo_path,
            branch=req.branch,
            base_branch=req.base_branch,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ctx.to_dict()


@editor_router.post("/context/build")
async def build_smart_context(
    req: SmartContextRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Build an optimal context package for a code entity."""
    from query.agent_workflow import AgentWorkflowService

    workflow = AgentWorkflowService(svc.store)
    ctx = await workflow.build_smart_context(
        entity_name=req.entity_name,
        entity_type=req.entity_type,
        repository=req.repository,
    )
    return ctx.to_dict()


@admin_router.get("/endpoints/{repository:path}")
async def list_api_endpoints(
    repository: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """List all discovered API endpoints for a repository."""
    from query.endpoint_queries import query_all_endpoints

    return await query_all_endpoints(svc.store, repository)


@admin_router.post("/analysis/impact")
async def analyze_impact(
    req: ImpactAnalysisRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Analyze the impact of changed functions."""
    from query.analysis_service import AnalysisService

    analysis = AnalysisService(svc.store)
    report = await analysis.analyze_impact(req.changed_functions, max_depth=req.max_depth)
    return report.to_dict()


@admin_router.get("/analysis/consistency/{repository:path}")
async def check_consistency(
    repository: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Check index consistency for a repository."""
    from query.analysis_service import AnalysisService
    from git_manager import GitManager

    settings = get_settings()
    git_mgr = GitManager(settings.git)
    repo_path = git_mgr._repo_local_path(repository)
    base_path = Path(settings.git.clone_base_path).resolve()
    resolved = repo_path.resolve()
    if not resolved.is_relative_to(base_path):
        raise HTTPException(
            status_code=400,
            detail=f"Repository path escapes clone base: {repository}",
        )

    analysis = AnalysisService(svc.store)
    report = await analysis.verify_consistency(str(resolved), repository=repository)
    return {"repository": repository, **report.to_dict()}


@admin_router.get("/architecture/{repository:path}")
async def get_architecture(
    repository: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Get architecture layer breakdown."""
    from query.endpoint_queries import query_architecture_layers

    return await query_architecture_layers(svc.store, repository)


@admin_router.post("/admin/cleanup-excluded-dirs")
async def cleanup_excluded_dirs(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Delete nodes from IDE/agent tool directories that should not be indexed."""
    from config import get_settings
    all_dirs = get_settings().exclude_dirs
    exclude_patterns = [d for d in all_dirs if d.startswith(".")]
    queries = GraphQueryRepository(svc.store)
    total_deleted = await queries.cleanup_excluded_dirs(exclude_patterns)
    return {"deleted_nodes": total_deleted, "patterns": exclude_patterns}


@viewer_router.post("/graph/explore")
async def graph_explore(
    req: GraphExploreRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Return nodes and edges around a named entity for force-directed graph rendering.

    Uses a two-phase approach:
    Phase 1 — collect neighbor nodes around the center entity.
    Phase 2 — query all edges between the collected node set.
    """

    queries = GraphQueryRepository(svc.store)

    if not req.name:
        result = await queries.explore_overview(req.limit)
        nodes = [
            {"id": r["uid"], "name": r["name"], "type": r["type"],
             "file": r["file"], "line": r["line"]}
            for r in result.data if r.get("uid")
        ]
        return {"nodes": nodes, "edges": []}

    nodes_result = await queries.explore_by_name(req.name, req.depth, req.limit)

    if not nodes_result.data:
        return {"nodes": [], "edges": []}

    node_uids: list[str] = []
    nodes_list: list[dict[str, Any]] = []
    for r in nodes_result.data:
        uid = r.get("uid", "")
        if not uid:
            continue
        node_uids.append(uid)
        nodes_list.append({
            "id": uid,
            "name": r.get("name", ""),
            "type": r.get("type", ""),
            "file": r.get("file", ""),
            "line": r.get("line", 0),
        })

    if nodes_list:
        first_name = req.name
        for nd in nodes_list:
            if nd["name"] == first_name:
                nd["is_center"] = True
                break

    edges_result = await queries.explore_edges(node_uids)

    edges_list: list[dict[str, Any]] = []
    edge_keys: set[str] = set()
    for r in edges_result.data:
        src = r.get("source", "")
        tgt = r.get("target", "")
        rtype = r.get("rel_type", "")
        key = f"{src}-{rtype}->{tgt}"
        if key not in edge_keys:
            edge_keys.add(key)
            edges_list.append({"source": src, "target": tgt, "type": rtype})

    return {"nodes": nodes_list, "edges": edges_list}


@admin_router.post("/admin/backfill-fqn")
async def backfill_fqn(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Compute and set fqn property for all Java Class/Function nodes."""
    from indexer.code_graph_builder import compute_fqn
    queries = GraphQueryRepository(svc.store)
    candidates = await queries.backfill_fqn_candidates()

    updated = 0
    for row in candidates:
        label = row.get("label", "")
        parent_class = ""
        if label == "Function":
            parent = await queries.get_function_parent_class(row["uid"])
            if parent:
                parent_class = parent

        fqn = compute_fqn(row.get("file", ""), row.get("name", ""), label, parent_class=parent_class)
        if fqn:
            await queries.set_node_fqn(row["uid"], fqn)
            updated += 1

    return {"updated": updated, "total_checked": len(candidates)}


@viewer_router.get("/code/{node_uid:path}")
async def get_code_snippet(
    node_uid: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Return the code snippet for a node, useful when KB is on a remote machine."""
    queries = GraphQueryRepository(svc.store)
    data = await queries.get_code_snippet(node_uid)
    if not data:
        raise HTTPException(status_code=404, detail="Node not found")
    return data


@editor_router.post("/mcp/tool")
async def mcp_tool_call(
    req: MCPToolCallRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """MCP-compatible tool call endpoint."""
    return await svc.mcp_handler.handle_tool_call(req.tool_name, req.arguments)


@viewer_router.get("/mcp/tools")
async def mcp_tools_list(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List available MCP tools."""
    return svc.mcp_handler.get_tools_manifest()


@public_router.get("/health")
async def health() -> JSONResponse:
    if _registry is None:
        return JSONResponse(
            status_code=503,
            content={"status": "initializing", "detail": "registry not started"},
        )
    body, status_code = await _registry.readiness()
    return JSONResponse(status_code=status_code, content=body)


@public_router.get("/auth/me")
async def auth_me(info: dict[str, Any] = Depends(get_current_role)) -> dict[str, Any]:
    """Return the current token's role information."""
    return info


# ── Business CRUD endpoints ──────────────────────────────────────────────


class CreateBusinessRequest(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    name: str
    description: str = ""


@viewer_router.get("/businesses")
async def list_businesses() -> dict[str, Any]:
    """List all businesses."""
    if _registry is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    loop = asyncio.get_running_loop()
    businesses = await loop.run_in_executor(None, _registry.business_manager.list_businesses)
    return {"businesses": businesses, "total": len(businesses)}


@admin_router.post("/businesses")
async def create_business(req: CreateBusinessRequest) -> dict[str, Any]:
    """Create a new business with its own isolated graph."""
    if _registry is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    loop = asyncio.get_running_loop()
    try:
        meta = await loop.run_in_executor(
            None,
            lambda: _registry.business_manager.create_business(req.id, req.name, req.description),  # type: ignore[union-attr]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return meta


@viewer_router.get("/businesses/{business_id}")
async def get_business(business_id: str) -> dict[str, Any]:
    """Get business details."""
    if _registry is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, _registry.business_manager.get_business, business_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Business '{business_id}' not found")
    return meta


@admin_router.delete("/businesses/{business_id}")
async def delete_business(business_id: str) -> dict[str, Any]:
    """Delete a business and all its graph data."""
    if _registry is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    try:
        await _registry.remove_service(business_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": business_id}


class SyncRepoRequest(BaseModel):
    """Request to git pull and incrementally re-index a repository."""
    repository: str = Field(..., description="Repository name (must already be indexed)")
    directory: str | None = Field(
        default=None,
        description="Repository root directory (required when using relative paths)",
    )
    git_url: str = Field(default="", description="Git clone URL for remote repos (auto-clones if not yet local)")
    branch: str | None = Field(default=None, description="Branch to checkout")
    base_ref: str = Field(default="HEAD~1", description="Git diff base reference")
    head_ref: str = Field(default="HEAD", description="Git diff head reference")


class SyncAllRequest(BaseModel):
    """Request to sync all indexed repositories."""
    repo_dirs: dict[str, str] | None = Field(
        default=None,
        description=(
            "Mapping of repo name → local directory path "
            "(required for relative-path indexed repos)"
        ),
    )
    base_ref: str = Field(default="HEAD~1", description="Git diff base reference")
    head_ref: str = Field(default="HEAD", description="Git diff head reference")


class SyncScheduleRequest(BaseModel):
    """Create or update a periodic git pull + incremental re-index schedule."""

    repo_name: str = Field(..., min_length=1)
    git_url: str = Field(..., min_length=1)
    branch: str | None = None
    interval_minutes: int = Field(default=60, ge=5, le=1440)
    enabled: bool = True


class SyncScheduleResponse(BaseModel):
    """One persisted schedule row returned to clients."""

    repo_name: str
    git_url: str
    branch: str | None
    interval_minutes: int
    enabled: bool
    last_sync_at: str | None
    last_sync_status: str
    last_sync_detail: str
    created_at: str


def _schedule_to_response(cfg: SyncScheduleConfig) -> SyncScheduleResponse:
    return SyncScheduleResponse(
        repo_name=cfg.repo_name,
        git_url=cfg.git_url,
        branch=cfg.branch,
        interval_minutes=cfg.interval_minutes,
        enabled=cfg.enabled,
        last_sync_at=cfg.last_sync_at,
        last_sync_status=cfg.last_sync_status,
        last_sync_detail=cfg.last_sync_detail,
        created_at=cfg.created_at,
    )


def _require_scheduler() -> SyncScheduler:
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    return _scheduler


@admin_router.get("/sync/schedules")
async def list_sync_schedules(
    sched: SyncScheduler = Depends(_require_scheduler),
) -> dict[str, Any]:
    """List all periodic sync schedules."""
    rows = await sched.list_schedules()
    return {
        "schedules": [_schedule_to_response(c).model_dump() for c in rows],
        "total": len(rows),
    }


@admin_router.post("/sync/schedules")
async def upsert_sync_schedule(
    req: SyncScheduleRequest,
    sched: SyncScheduler = Depends(_require_scheduler),
) -> SyncScheduleResponse:
    """Create or update a sync schedule for a repository."""
    branch_raw = req.branch.strip() if req.branch else ""
    cfg = SyncScheduleConfig(
        repo_name=req.repo_name.strip(),
        git_url=req.git_url.strip(),
        branch=branch_raw if branch_raw else None,
        interval_minutes=req.interval_minutes,
        enabled=req.enabled,
    )
    saved = await sched.add_schedule(cfg)
    return _schedule_to_response(saved)


@admin_router.delete("/sync/schedules/{repo:path}")
async def delete_sync_schedule(
    repo: str,
    sched: SyncScheduler = Depends(_require_scheduler),
) -> dict[str, str]:
    """Remove a sync schedule."""
    ok = await sched.remove_schedule(repo)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No schedule for repository '{repo}'")
    return {"deleted": repo}


@admin_router.post("/sync/schedules/{repo:path}/trigger")
async def trigger_sync_schedule_now(
    repo: str,
    sched: SyncScheduler = Depends(_require_scheduler),
) -> dict[str, Any]:
    """Run git pull + incremental index immediately for a scheduled repository."""
    try:
        return await sched.trigger_sync_now(repo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _git_rev_parse(repo_dir: str, ref: str = "HEAD") -> str | None:
    """Resolve a git ref to a full SHA. Returns None on failure."""
    import subprocess

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["git", "rev-parse", ref],
                capture_output=True,
                text=True,
                cwd=repo_dir,
                timeout=10,
            ),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as exc:
        log.warning("git_rev_parse_failed", ref=ref, error=str(exc))
    return None


async def _git_pull(directory: str) -> dict[str, str]:
    """Run git pull in a directory."""
    loop = asyncio.get_running_loop()
    import subprocess
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True, cwd=directory, timeout=60,
        ),
    )
    return {
        "returncode": str(result.returncode),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


@admin_router.post("/sync/repo")
async def sync_repository(
    req: SyncRepoRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Git pull a repository and run incremental re-indexing.

    When ``git_url`` is provided, uses GitManager for clone/pull
    (supports private GitLab with token or SSH key).
    """
    repo_dir: str | None = req.directory
    queries = GraphQueryRepository(svc.store)

    if req.git_url:
        from git_manager import GitManager

        if _repo_registry is None:
            raise HTTPException(status_code=503, detail="Repository registry not initialized")

        mgr = GitManager(get_settings().git)
        result = await mgr.ensure_repo(req.git_url, branch=req.branch)
        if result["status"] in ("clone_failed", "pull_failed"):
            raise HTTPException(
                status_code=500,
                detail=f"Git operation failed: {result.get('detail', '')}",
            )

        repo_name, name_warn = await _resolve_canonical_repository_for_git(
            req.git_url,
            req.repository,
            _repo_registry,
            queries,
        )
        if name_warn:
            log.warning("repository_name_canonicalized", detail=name_warn, git_url=req.git_url)

        repo_dir = result["directory"]
        pre_head = result.get("pre_head", "")

        if result["status"] == "up_to_date":
            return {
                "repository": repo_name,
                "directory": repo_dir,
                "git_pull": "already_up_to_date",
                "index_stats": None,
            }

        base = pre_head if pre_head else req.base_ref
        index_stats = await svc.indexer.index_incremental(repo_dir, base, req.head_ref)
        if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
            await queries.tag_unowned_nodes(
                repo_name,
                git_url=req.git_url,
            )

        if _repo_registry:
            _repo_registry.register(req.git_url, repo_name)

        return {
            "repository": repo_name,
            "directory": repo_dir,
            "git_pull": result["status"],
            "index_stats": index_stats,
        }

    if not repo_dir:
        sample_file = await queries.get_repository_sample_file(req.repository)
        if sample_file is None:
            raise HTTPException(status_code=404, detail=f"Repository '{req.repository}' not found in index")

        sample_file = sample_file or ""
        repo_dir = None
        if sample_file and sample_file.startswith("/"):
            repo_dir = _infer_repo_root(sample_file, req.repository)

    if not repo_dir or not Path(repo_dir).is_dir():
        raise HTTPException(
            status_code=500,
            detail=(
                "Repository directory not found. "
                "Provide 'directory' or 'git_url' in request."
            ),
        )

    pre_pull_head = await _git_rev_parse(repo_dir, "HEAD")

    pull_result = await _git_pull(repo_dir)

    if pull_result["stdout"] == "Already up to date.":
        return {
            "repository": req.repository,
            "directory": repo_dir,
            "git_pull": "already_up_to_date",
            "index_stats": None,
        }

    base = pre_pull_head if pre_pull_head else req.base_ref
    index_stats = await svc.indexer.index_incremental(repo_dir, base, req.head_ref)

    if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
        await queries.tag_unowned_nodes(req.repository)

    return {
        "repository": req.repository,
        "directory": repo_dir,
        "git_pull": pull_result,
        "index_stats": index_stats,
    }


@admin_router.post("/sync/all")
async def sync_all_repositories(
    req: SyncAllRequest | None = None,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Git pull all indexed repositories and run incremental re-indexing for each."""
    queries = GraphQueryRepository(svc.store)
    repos_rows = await queries.list_repositories_with_samples()

    if not repos_rows:
        return {"synced": [], "total": 0}

    base_ref = (req.base_ref if req else "HEAD~1")
    head_ref = (req.head_ref if req else "HEAD")
    repo_dirs_map = (req.repo_dirs if req else None) or {}

    results = []
    for row in repos_rows:
        repo = row.get("repo", "")
        sample_file = row.get("sample_file", "")
        if not repo:
            continue

        repo_dir = repo_dirs_map.get(repo)
        if not repo_dir and sample_file and sample_file.startswith("/"):
            repo_dir = _infer_repo_root(sample_file, repo)
        if not repo_dir or not Path(repo_dir).is_dir():
            results.append({
                "repository": repo,
                "status": "error",
                "detail": "directory not found; provide repo_dirs mapping",
            })
            continue

        try:
            # Record pre-pull HEAD so incremental diff covers the full pull range
            pre_pull_head = await _git_rev_parse(repo_dir, "HEAD")

            pull_result = await _git_pull(repo_dir)
            if pull_result["stdout"] == "Already up to date.":
                results.append({"repository": repo, "status": "up_to_date"})
                continue

            base = pre_pull_head if pre_pull_head else base_ref
            index_stats = await svc.indexer.index_incremental(repo_dir, base, head_ref)
            if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
                await queries.tag_unowned_nodes(repo)
            results.append({"repository": repo, "status": "synced", "stats": index_stats})
        except Exception as exc:
            log.warning("sync_repo_error", repo=repo, error=str(exc))
            results.append({"repository": repo, "status": "error", "detail": str(exc)})

    return {"synced": results, "total": len(results)}


def _infer_repo_root(sample_file: str, repo_name: str) -> str | None:
    """Infer repository root directory from a sample indexed file path and repository name."""
    idx = sample_file.find(f"/{repo_name}/")
    if idx >= 0:
        return sample_file[:idx + len(repo_name) + 1]
    idx = sample_file.find(f"/{repo_name}")
    if idx >= 0:
        candidate = sample_file[:idx + len(repo_name) + 1].rstrip("/")
        if Path(candidate).is_dir():
            return candidate
    return None


@admin_router.post("/admin/migrate-to-relative-paths")
async def migrate_to_relative_paths(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Migrate stored absolute file paths to relative paths (per repository).

    Uses batch Cypher operations — replaces the repo-root prefix in
    ``file``, ``path``, and ``uid`` properties in a single pass per repo.
    """
    queries = GraphQueryRepository(svc.store)
    repos_rows = await queries.list_repositories_with_multiple_samples()

    if not repos_rows:
        return {"status": "nothing_to_migrate", "repos": []}

    repo_stats: list[dict] = []
    for row in repos_rows:
        repo = row.get("repo", "")
        samples = row.get("samples", [])
        if not repo or not samples:
            continue

        root = None
        for sample in samples:
            if not sample or not sample.startswith("/"):
                continue
            root = _infer_repo_root(sample, repo)
            if root:
                break

        if not root:
            repo_stats.append({"repo": repo, "status": "skip", "detail": "no absolute paths or cannot infer root"})
            continue

        prefix = root.rstrip("/") + "/"

        cnt = await queries.count_nodes_with_prefix(repo, prefix)

        if cnt == 0:
            repo_stats.append({"repo": repo, "status": "skip", "detail": "already migrated"})
            continue

        await queries.migrate_file_paths(repo, prefix)

        await queries.migrate_node_paths(repo, prefix)

        repo_stats.append({"repo": repo, "status": "migrated", "nodes_updated": cnt, "prefix_removed": prefix})

    return {"status": "completed", "repos": repo_stats}


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

_SPA_ROUTES = {
    "search",
    "deep-search",
    "graph",
    "explorer",
    "repositories",
    "indexing",
    "settings",
    "businesses",
    "documents",
    "sync",
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Knowledge Base Service",
        description="Code knowledge base with graph + vector search",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(public_router)
    app.include_router(viewer_router)
    app.include_router(editor_router)
    app.include_router(admin_router)

    if _STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="static-assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:
            file_path = _STATIC_DIR / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(_INDEX_HTML)

    return app


app = create_app()
