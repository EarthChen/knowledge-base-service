"""Route group: indexing_routes (extracted from main)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request

import api.kb_state as kb_state
from api.exceptions import KbNotFound, KbServiceUnavailable
from api.routes import kb_routers
from api.routes.kb_dependencies import get_effective_business_id, get_service
from indexer.embedding_generator import doc_dict_for_embedding
from indexer.incremental_indexer import _stamp_repository_metadata, _try_git_head_sha_for_file
from api.routes.kb_index_helpers import (
    infer_repo_root,
    run_enrich_task,
    run_index_task,
    tag_repository,
    throttled_index_task,
)
from api.routes.kb_schemas import (
    EnrichRequest,
    IndexFileRequest,
    IndexFilesRequest,
    IndexRequest,
    ReindexAllRequest,
)
from services.kb_service import KnowledgeBaseService
from store.graph_queries import GraphQueryRepository
from utils.git_utils import looks_like_git_url
from core.log import get_logger

log = get_logger(__name__)
viewer_router = kb_routers.viewer_router
editor_router = kb_routers.editor_router
admin_router = kb_routers.admin_router
public_router = kb_routers.public_router


@viewer_router.get("/index/tasks")
async def list_index_tasks() -> dict[str, Any]:
    if kb_state.task_manager is None:
        raise KbServiceUnavailable("Service not ready")
    tasks = kb_state.task_manager.list_tasks()
    return {"tasks": [t.to_dict() for t in tasks], "total": len(tasks)}


@viewer_router.get("/index/tasks/{task_id}")
async def get_index_task(task_id: str) -> dict[str, Any]:
    if kb_state.task_manager is None:
        raise KbServiceUnavailable("Service not ready")
    task = kb_state.task_manager.get_task(task_id)
    if task is None:
        raise KbNotFound("Task not found")
    return task.to_dict()


@editor_router.post("/index")
async def trigger_index(
    request: Request,
    req: IndexRequest,
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    if kb_state.task_manager is None or kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")

    if not req.directory and not req.git_url:
        raise HTTPException(
            status_code=422,
            detail="Either 'directory' or 'git_url' must be provided",
        )

    if not req.git_url and req.directory and looks_like_git_url(req.directory):
        req = req.model_copy(update={"git_url": req.directory, "directory": ""})

    task = kb_state.task_manager.create_task(
        mode=req.mode,
        directory=req.directory or req.git_url,
        repository=req.repository,
        business_id=business_id,
    )

    supervisor = getattr(
        getattr(request.app.state, "container", None),
        "task_supervisor",
        None,
    )
    if supervisor is not None:
        supervisor.spawn(
            lambda tid=task.task_id, r=req, bid=business_id: throttled_index_task(tid, r, bid),
            name="indexing:index",
            max_retries=2,
        )
    else:
        asyncio.create_task(
            throttled_index_task(task.task_id, req, business_id),
        )

    return {
        "task_id": task.task_id,
        "status": task.status,
        "mode": req.mode,
        "directory": req.directory,
        "git_url": req.git_url or None,
    }


@editor_router.post("/reindex/all")
async def reindex_all_repositories(
    request: Request,
    req: ReindexAllRequest,
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    """Queue a full re-index for each repository (same semantics as POST /index with mode=full)."""
    if kb_state.task_manager is None or kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")

    svc = await kb_state.registry.get_service(business_id)
    queries = GraphQueryRepository(svc.store)

    if req.repositories:
        repo_names = [r.strip() for r in req.repositories if r.strip()]
    else:
        rows = await queries.list_repositories()
        repo_names = [str(r["repository"]) for r in rows if r.get("repository")]

    if not repo_names:
        return {
            "tasks": [],
            "task_ids": [],
            "skipped": [],
            "total": 0,
            "queued": 0,
            "message": "No repositories to re-index",
        }

    base = (req.base_dir or "").strip() or None

    skipped: list[dict[str, Any]] = []
    tasks_out: list[dict[str, Any]] = []

    samples_map: dict[str, str] = {}
    if base is None:
        for row in await queries.list_repositories_with_samples():
            rname = row.get("repo")
            sf = row.get("sample_file")
            if rname and sf:
                samples_map[str(rname)] = str(sf)

    _SAFE_REPO_NAME = re.compile(r"^[\w][\w.\-]*$")
    base_resolved = Path(base).resolve() if base else None

    for repo in repo_names:
        directory: str | None = None
        if base_resolved:
            if not _SAFE_REPO_NAME.match(repo):
                skipped.append({"repository": repo, "reason": "invalid repo name characters"})
                continue
            candidate = (base_resolved / repo).resolve()
            if not candidate.is_relative_to(base_resolved):
                skipped.append({"repository": repo, "reason": "path traversal detected"})
                continue
            if candidate.is_dir():
                directory = str(candidate)
            else:
                skipped.append({"repository": repo, "reason": f"not a directory: {candidate}"})
                continue
        else:
            sample = samples_map.get(repo)
            if not sample:
                sf = await queries.get_repository_sample_file(repo)
                sample = sf or ""
            if sample and sample.startswith("/"):
                directory = infer_repo_root(sample, repo)
            if not directory or not Path(directory).is_dir():
                skipped.append({
                    "repository": repo,
                    "reason": (
                        "could not resolve local directory; set base_dir or ensure indexed file paths are absolute"
                    ),
                })
                continue

        idx = IndexRequest(directory=directory, repository=repo, mode="full")
        task = kb_state.task_manager.create_task(
            mode="full",
            directory=directory,
            repository=repo,
            business_id=business_id,
        )

        async def _throttled_index(
            sem: asyncio.Semaphore, tid: str, ir: IndexRequest, bid: str
        ) -> None:
            async with sem:
                await run_index_task(tid, ir, bid)

        supervisor = getattr(
            getattr(request.app.state, "container", None),
            "task_supervisor",
            None,
        )
        if supervisor is not None:
            supervisor.spawn(
                lambda s=kb_state.reindex_sem, tid=task.task_id, i=idx, bid=business_id: _throttled_index(
                    s, tid, i, bid
                ),
                name="indexing:reindex",
                max_retries=2,
            )
        else:
            asyncio.create_task(
                _throttled_index(kb_state.reindex_sem, task.task_id, idx, business_id),
            )
        tasks_out.append({
            "repository": repo,
            "task_id": task.task_id,
            "directory": directory,
            "status": "queued",
        })

    return {
        "tasks": tasks_out,
        "task_ids": [t["task_id"] for t in tasks_out],
        "skipped": skipped,
        "total": len(tasks_out) + len(skipped),
        "queued": len(tasks_out),
    }


@editor_router.post("/enrich")
async def trigger_enrich(
    request: Request,
    req: EnrichRequest,
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    """对已入库实体异步执行 LLM 业务摘要补全，可通过任务接口查询进度。"""
    if kb_state.task_manager is None or kb_state.registry is None:
        raise KbServiceUnavailable("服务未就绪")

    task = kb_state.task_manager.create_task(
        mode="enrich",
        directory="",
        repository=req.repository,
        business_id=business_id,
    )

    supervisor = getattr(
        getattr(request.app.state, "container", None),
        "task_supervisor",
        None,
    )
    if supervisor is not None:
        supervisor.spawn(
            lambda tid=task.task_id, r=req, bid=business_id: run_enrich_task(tid, r, bid),
            name="indexing:enrich",
            max_retries=2,
        )
    else:
        asyncio.create_task(
            run_enrich_task(task.task_id, req, business_id),
        )

    return {
        "task_id": task.task_id,
        "status": task.status,
        "mode": "enrich",
        "repository": req.repository,
        "force": req.force,
    }


@editor_router.post("/index/files")
async def index_files(
    req: IndexFilesRequest,
    svc: KnowledgeBaseService = Depends(get_service),
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
        stats = await svc.indexer.index_file(
            file_req.file_path, file_req.content, repository=repo,
        )
        total_nodes += stats.get("nodes", 0)
        total_edges += stats.get("edges", 0)
        total_embeds += stats.get("embeddings", 0)

        if repo:
            await tag_repository(svc, file_req.file_path, repo)

        ext = file_req.file_path.rsplit(".", 1)[-1].lower() if "." in file_req.file_path else ""
        if ext in {"md", "markdown", "rst", "txt"}:
            doc = svc.doc_indexer.parse_document(file_req.file_path, file_req.content)
            doc_nodes, doc_edges = svc.doc_indexer.build_graph(doc)
            _sha = _try_git_head_sha_for_file(file_req.file_path) if repo else None
            _stamp_repository_metadata(doc_nodes, repo, commit_sha=_sha)
            await svc.store.batch_upsert(doc_nodes, doc_edges)
            total_nodes += len(doc_nodes)
            total_edges += len(doc_edges)

            embeddable = [n for n in doc_nodes if n.properties.get("content")]
            if embeddable:
                items = [doc_dict_for_embedding(n.properties) for n in embeddable]
                embeddings = await svc._embedding.generate_for_docs(items)
                for node, emb in zip(embeddable, embeddings):
                    await svc.store.set_node_embedding(node.uid, node.label, emb)
                total_embeds += len(embeddings)

            if repo:
                for n in doc_nodes:
                    await tag_repository(svc, n.properties.get("file", ""), repo)

    return {
        "indexed_files": len(req.files),
        "nodes": total_nodes,
        "edges": total_edges,
        "embeddings": total_embeds,
        "repository": req.repository,
    }
