"""Route group: business_sync_routes (extracted from main)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

import api.kb_state as kb_state
from api.exceptions import KbClientError, KbError, KbNotFound, KbServiceUnavailable
from api.routes import kb_routers
from api.routes.kb_dependencies import get_effective_business_id, get_service
from api.routes.kb_index_helpers import infer_repo_root, resolve_canonical_repository_for_git
from api.routes.kb_schemas import (
    CreateBusinessRequest,
    SyncAllRequest,
    SyncRepoRequest,
    SyncScheduleRequest,
    SyncScheduleResponse,
)
from core.config import get_settings
from core.log import get_logger
from services.kb_service import KnowledgeBaseService
from services.repo_registry import RepoRegistry
from services.scheduler import SyncScheduleConfig, SyncScheduler
from store.graph_queries import GraphQueryRepository, validate_architecture_class_search
from utils.git_utils import looks_like_git_url

log = get_logger(__name__)
viewer_router = kb_routers.viewer_router
editor_router = kb_routers.editor_router
admin_router = kb_routers.admin_router
public_router = kb_routers.public_router


@admin_router.post("/businesses")
async def create_business(req: CreateBusinessRequest) -> dict[str, Any]:
    """Create a new business with its own isolated graph."""
    if kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")
    loop = asyncio.get_running_loop()
    try:
        meta = await loop.run_in_executor(
            None,
            lambda: kb_state.registry.business_manager.create_business(req.id, req.name, req.description),  # type: ignore[union-attr]
        )
    except ValueError as exc:
        raise KbClientError(str(exc)) from exc
    return meta


@viewer_router.get("/businesses/{business_id}")
async def get_business(business_id: str) -> dict[str, Any]:
    """Get business details."""
    if kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, kb_state.registry.business_manager.get_business, business_id)
    if meta is None:
        raise KbNotFound(f"Business '{business_id}' not found")
    return meta


@admin_router.delete("/businesses/{business_id}")
async def delete_business(business_id: str) -> dict[str, Any]:
    """Delete a business and all its graph data."""
    if kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")
    try:
        await kb_state.registry.remove_service(business_id)
    except ValueError as exc:
        raise KbClientError(str(exc)) from exc
    return {"deleted": business_id}


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
    if kb_state.scheduler is None:
        raise KbServiceUnavailable("Scheduler not ready")
    return kb_state.scheduler


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
        raise KbNotFound(f"No schedule for repository '{repo}'")
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
        raise KbNotFound(str(exc)) from exc


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
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Git pull a repository and run incremental re-indexing.

    When ``git_url`` is provided, uses GitManager for clone/pull
    (supports private GitLab with token or SSH key).
    """
    repo_dir: str | None = req.directory
    queries = GraphQueryRepository(svc.store)

    if req.git_url:
        from services.git_manager import GitManager

        if kb_state.repo_registry is None:
            raise KbServiceUnavailable("Repository registry not initialized")

        mgr = GitManager(get_settings().git)
        result = await mgr.ensure_repo(req.git_url, branch=req.branch)
        if result["status"] in ("clone_failed", "pull_failed"):
            raise KbError(f"Git operation failed: {result.get('detail', '')}")

        repo_name, name_warn = await resolve_canonical_repository_for_git(
            req.git_url,
            req.repository,
            kb_state.repo_registry,
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
        index_stats = await svc.indexer.index_incremental(
            repo_dir, base, req.head_ref, repository=repo_name,
        )
        if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
            await queries.tag_unowned_nodes(
                repo_name,
                directory=repo_dir,
                git_url=req.git_url,
            )

        if kb_state.repo_registry:
            kb_state.repo_registry.register(req.git_url, repo_name)

        return {
            "repository": repo_name,
            "directory": repo_dir,
            "git_pull": result["status"],
            "index_stats": index_stats,
        }

    if not repo_dir:
        sample_file = await queries.get_repository_sample_file(req.repository)
        if sample_file is None:
            raise KbNotFound(f"Repository '{req.repository}' not found in index")

        sample_file = sample_file or ""
        repo_dir = None
        if sample_file and sample_file.startswith("/"):
            repo_dir = infer_repo_root(sample_file, req.repository)

    if not repo_dir or not Path(repo_dir).is_dir():
        raise KbError(
            "Repository directory not found. "
            "Provide 'directory' or 'git_url' in request.",
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
    index_stats = await svc.indexer.index_incremental(
        repo_dir, base, req.head_ref, repository=req.repository,
    )

    if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
        await queries.tag_unowned_nodes(req.repository, directory=repo_dir)

    return {
        "repository": req.repository,
        "directory": repo_dir,
        "git_pull": pull_result,
        "index_stats": index_stats,
    }


@admin_router.post("/sync/all")
async def sync_all_repositories(
    req: SyncAllRequest | None = None,
    svc: KnowledgeBaseService = Depends(get_service),
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
            repo_dir = infer_repo_root(sample_file, repo)
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
            index_stats = await svc.indexer.index_incremental(
                repo_dir, base, head_ref, repository=repo,
            )
            if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
                await queries.tag_unowned_nodes(repo, directory=repo_dir)
            results.append({"repository": repo, "status": "synced", "stats": index_stats})
        except Exception as exc:
            log.warning("sync_repo_error", repo=repo, error=str(exc))
            results.append({"repository": repo, "status": "error", "detail": str(exc)})

    return {"synced": results, "total": len(results)}


@admin_router.post("/sync/repo-update-wiki")
async def sync_repo_and_regenerate_wiki(
    req: SyncRepoRequest,
    request: Request,
    svc: KnowledgeBaseService = Depends(get_service),
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    """Git pull a repository, run incremental re-indexing, and trigger wiki regeneration.

    Combines sync/repo + wiki/generate into a single pipeline.
    Returns sync stats immediately; wiki generation runs in the background.
    """
    queries = GraphQueryRepository(svc.store)
    repo_dir: str | None = req.directory
    repo_name = req.repository
    sync_result: dict[str, Any] = {}

    if req.git_url:
        from services.git_manager import GitManager

        if kb_state.repo_registry is None:
            raise KbServiceUnavailable("Repository registry not initialized")

        mgr = GitManager(get_settings().git)
        result = await mgr.ensure_repo(req.git_url, branch=req.branch)
        if result["status"] in ("clone_failed", "pull_failed"):
            raise KbError(f"Git operation failed: {result.get('detail', '')}")

        repo_name, name_warn = await resolve_canonical_repository_for_git(
            req.git_url, req.repository, kb_state.repo_registry, queries,
        )
        if name_warn:
            log.warning("repository_name_canonicalized", detail=name_warn, git_url=req.git_url)

        repo_dir = result["directory"]
        pre_head = result.get("pre_head", "")

        if result["status"] == "up_to_date":
            sync_result = {
                "repository": repo_name,
                "directory": repo_dir,
                "git_pull": "already_up_to_date",
                "index_stats": None,
            }
        else:
            base = pre_head if pre_head else req.base_ref
            index_stats = await svc.indexer.index_incremental(
                repo_dir, base, req.head_ref, repository=repo_name,
            )
            if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
                await queries.tag_unowned_nodes(repo_name, directory=repo_dir, git_url=req.git_url)
            if kb_state.repo_registry:
                kb_state.repo_registry.register(req.git_url, repo_name)
            # Auto-bind to business
            if kb_state.registry is not None:
                try:
                    bm = kb_state.registry.business_manager
                    current_repos = bm.get_repos(business_id)
                    if repo_name not in current_repos:
                        bm.set_repos(business_id, current_repos + [repo_name])
                        log.info("auto_bind_repo_to_business", repository=repo_name, business_id=business_id)
                except Exception:
                    log.warning("auto_bind_failed", repository=repo_name, business_id=business_id, exc_info=True)
            sync_result = {
                "repository": repo_name,
                "directory": repo_dir,
                "git_pull": result["status"],
                "index_stats": index_stats,
            }
    else:
        if not repo_dir:
            sample_file = await queries.get_repository_sample_file(repo_name)
            if sample_file is None:
                raise KbNotFound(f"Repository '{repo_name}' not found in index")
            sample_file = sample_file or ""
            if sample_file and sample_file.startswith("/"):
                repo_dir = infer_repo_root(sample_file, repo_name)

        if not repo_dir or not Path(repo_dir).is_dir():
            raise KbError("Repository directory not found.")

        pre_pull_head = await _git_rev_parse(repo_dir, "HEAD")
        pull_result = await _git_pull(repo_dir)

        if pull_result["stdout"] == "Already up to date.":
            sync_result = {
                "repository": repo_name,
                "directory": repo_dir,
                "git_pull": "already_up_to_date",
                "index_stats": None,
            }
        else:
            base = pre_pull_head if pre_pull_head else req.base_ref
            index_stats = await svc.indexer.index_incremental(
                repo_dir, base, req.head_ref, repository=repo_name,
            )
            if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
                await queries.tag_unowned_nodes(repo_name, directory=repo_dir)
            sync_result = {
                "repository": repo_name,
                "directory": repo_dir,
                "git_pull": pull_result,
                "index_stats": index_stats,
            }

    wiki_task_id: str | None = None
    try:
        factory = getattr(request.app.state, "wiki_service_factory", None)
        if callable(factory):
            wiki_svc = factory(business_id=business_id)
            if asyncio.iscoroutine(wiki_svc):
                wiki_svc = await wiki_svc

            import uuid
            wiki_task_id = f"wiki-sync-{uuid.uuid4().hex[:12]}"
            wiki_mode = "full"

            async def _wiki_bg() -> None:
                try:
                    await wiki_svc.generate(
                        repo_name, "repo", wiki_mode, "json", "zh",
                    )
                    log.info("sync_wiki_regen_done", repository=repo_name)
                except Exception:
                    log.warning("sync_wiki_regen_failed", repository=repo_name, exc_info=True)

            supervisor = getattr(
                getattr(request.app.state, "container", None),
                "task_supervisor",
                None,
            )
            if supervisor is not None:
                supervisor.spawn(lambda: _wiki_bg(), name="wiki:sync-regen")
            else:
                asyncio.create_task(_wiki_bg())
    except Exception:
        log.warning("sync_wiki_trigger_failed", repository=repo_name, exc_info=True)

    return {
        **sync_result,
        "wiki_task_id": wiki_task_id,
        "wiki_triggered": wiki_task_id is not None,
    }


@admin_router.post("/admin/migrate-to-relative-paths")
async def migrate_to_relative_paths(
    svc: KnowledgeBaseService = Depends(get_service),
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
            root = infer_repo_root(sample, repo)
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
