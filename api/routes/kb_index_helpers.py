"""Background indexing helpers and git/repository name resolution (formerly in ``main``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import api.kb_state as kb_state
from log import get_logger
from repo_registry import RepoRegistry
from service import KnowledgeBaseService
from store.graph_queries import GraphQueryRepository

from api.routes.kb_schemas import EnrichRequest, IndexRequest

log = get_logger(__name__)


async def resolve_canonical_repository_for_git(
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


async def tag_repository(svc: KnowledgeBaseService, file_path: str, repository: str) -> None:
    """Tag all nodes from a file with a repository label."""
    queries = GraphQueryRepository(svc.store)
    await queries.tag_nodes_with_repository(file_path, repository)


def infer_repo_root(sample_file: str, repo_name: str) -> str | None:
    """Infer repository root directory from a sample indexed file path and repository name."""
    idx = sample_file.find(f"/{repo_name}/")
    if idx >= 0:
        return sample_file[: idx + len(repo_name) + 1]
    idx = sample_file.find(f"/{repo_name}")
    if idx >= 0:
        candidate = sample_file[: idx + len(repo_name) + 1].rstrip("/")
        if Path(candidate).is_dir():
            return candidate
    return None


async def run_enrich_task(task_id: str, req: EnrichRequest, business_id: str) -> None:
    """后台执行仅摘要补全。"""
    if kb_state.task_manager is None or kb_state.registry is None:
        return

    kb_state.task_manager.mark_running(task_id)
    progress_cb = kb_state.task_manager.make_progress_callback(task_id)

    try:
        svc = await kb_state.registry.get_service(business_id)

        if not svc.indexer.enrichment_available:
            kb_state.task_manager.mark_failed(
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

        kb_state.task_manager.mark_completed(
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
        kb_state.task_manager.mark_failed(task_id, str(exc))


async def throttled_index_task(task_id: str, req: IndexRequest, business_id: str) -> None:
    async with kb_state.index_sem:
        await run_index_task(task_id, req, business_id)


async def run_index_task(task_id: str, req: IndexRequest, business_id: str) -> None:
    """Background coroutine that runs the actual indexing work.

    When ``git_url`` is provided, the task first clones/pulls the repo
    from a (potentially private) GitLab instance, then indexes the
    resulting local directory.
    """
    if kb_state.task_manager is None or kb_state.registry is None:
        return

    kb_state.task_manager.mark_running(task_id)
    progress_cb = kb_state.task_manager.make_progress_callback(task_id)

    try:
        svc = await kb_state.registry.get_service(business_id)

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
                kb_state.task_manager.mark_failed(
                    task_id,
                    f"Git operation failed: {clone_result.get('detail', '')}",
                )
                return

            directory = clone_result["directory"]

            if kb_state.repo_registry is None:
                kb_state.task_manager.mark_failed(task_id, "Repository registry not initialized")
                return

            queries_pre = GraphQueryRepository(svc.store)
            canonical, name_warn = await resolve_canonical_repository_for_git(
                req.git_url,
                req.repository,
                kb_state.repo_registry,
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
            kb_state.task_manager.mark_failed(task_id, "No directory resolved for indexing")
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
            err = result["error"]
            err_msg = err["message"] if isinstance(err, dict) else str(err)
            kb_state.task_manager.mark_failed(task_id, err_msg)
            return

        if repository:
            queries = GraphQueryRepository(svc.store)
            await queries.tag_unowned_nodes(
                repository,
                directory=directory,
                git_url=req.git_url or None,
            )

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

        if repository and kb_state.repo_registry:
            if req.git_url:
                kb_state.repo_registry.register(req.git_url, repository)
            elif directory:
                kb_state.repo_registry.register(str(Path(directory).resolve()), repository)

        kb_state.task_manager.mark_completed(task_id, merged_result)
    except Exception as exc:
        log.error("index_task_failed", task_id=task_id, error=str(exc))
        kb_state.task_manager.mark_failed(task_id, str(exc))
