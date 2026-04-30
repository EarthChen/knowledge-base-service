"""Wiki feedback, ingest, changelog, merge candidates, and repo admin exports."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from api.exceptions import KbNotFound, KbServiceUnavailable
from api.models.wiki_models import (
    ChunkIndexBody,
    IngestRequest,
    WikiBatchReviewBody,
    WikiExportExecuteBody,
    WikiExportPreviewBody,
    WikiLintBody,
    WikiPageFeedbackBody,
    WikiPageReviewBody,
    WikiQaRecordBody,
    WikiRegenerateBody,
)
from api.routes.wiki_shared import (
    get_route_settings,
    get_wiki_docs_exporter_dep,
    get_wiki_feedback_store_dep,
    get_wiki_lint_service_dep,
    get_wiki_memory_loop_dep,
    get_wiki_service_dep,
    log,
)
from auth import Role, require_role
from store.wiki_feedback_store import WikiFeedbackStore
from wiki.lint import WikiLintService
from wiki.memory_loop import MemoryLoop
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.wiki_docs_exporter import export_result_to_dict

router = APIRouter(tags=["wiki", "feedback"])


@router.post("/pages/{page_uid:path}/feedback", response_model=None)
async def post_wiki_page_feedback(
    request: Request,
    page_uid: str,
    body: WikiPageFeedbackBody,
    fb: WikiFeedbackStore = Depends(get_wiki_feedback_store_dep),
) -> dict[str, Any]:
    """Thumbs up/down feedback for a wiki page (graph persistence)."""
    decoded = unquote(page_uid)
    uid = await fb.persist_feedback(
        page_uid=decoded,
        rating=body.rating,
        comment=body.comment,
        business_id=body.business_id,
        severity=body.severity,
    )
    loop = getattr(request.app.state, "wiki_feedback_regen", None)
    regen_result: dict[str, Any] = {}
    if loop:
        try:
            regen_result = await loop.on_feedback(
                decoded, body.business_id, body.rating, severity=body.severity
            )
        except Exception:  # noqa: BLE001 — never fail the feedback persist path
            log.warning("feedback_regen_error", exc_info=True)
    return {
        "uid": uid,
        "page_uid": decoded,
        "business_id": body.business_id,
        "regen_result": regen_result,
    }


@router.get("/pages/{page_uid:path}/feedback/summary", response_model=None)
async def get_wiki_page_feedback_summary(
    page_uid: str,
    business_id: str = Query(default="default", min_length=1),
    fb: WikiFeedbackStore = Depends(get_wiki_feedback_store_dep),
) -> dict[str, Any]:
    """Aggregate up/down feedback counts for a wiki page."""
    decoded = unquote(page_uid)
    return await fb.get_feedback_summary(decoded, business_id=business_id)


@router.post(
    "/pages/{page_uid:path}/review",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def set_page_review(
    page_uid: str,
    body: WikiPageReviewBody,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Set review status for a wiki page."""
    decoded = unquote(page_uid)
    try:
        result = await svc.set_page_review_status(decoded, body.status, body.notes)
        return result
    except AttributeError:
        raise HTTPException(501, "This feature is not yet implemented in WikiService")


@router.post("/review/batch", response_model=None, dependencies=[Depends(require_role(Role.EDITOR))])
async def batch_review(
    body: WikiBatchReviewBody,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Batch review multiple wiki pages at once."""
    reviews_payload = [r.model_dump() for r in body.reviews]
    try:
        result = await svc.batch_review(body.business_id, reviews_payload)
        return result
    except AttributeError:
        raise HTTPException(501, "This feature is not yet implemented in WikiService")


@router.post(
    "/pages/{page_uid:path}/regenerate",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def trigger_regeneration(
    page_uid: str,
    body: WikiRegenerateBody,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Trigger regeneration of a single wiki page with optional heal hints."""
    decoded = unquote(page_uid)
    try:
        result = await svc.trigger_page_regeneration(decoded, body.heal_hints)
        return result
    except AttributeError:
        raise HTTPException(501, "This feature is not yet implemented in WikiService")


@router.post("/chunks/index", response_model=None, dependencies=[Depends(require_role(Role.EDITOR))])
async def wiki_chunk_index(
    body: ChunkIndexBody,
    request: Request,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> JSONResponse:
    """Trigger batch embedding generation for Chunk nodes (RAG indexing)."""
    try:
        await svc.ensure_repository(body.repository)
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' is not indexed. Use /wiki/quick to auto-index."
        ) from exc

    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")

    from store.wiki_store import WikiStore as _WikiStore
    from wiki.chunk_indexer import CodeChunkIndexer

    wiki_store_inst = _WikiStore(raw_store)
    s = get_route_settings()
    indexer = CodeChunkIndexer(
        wiki_store_inst,
        raw_store,
        embedding_config=s.embedding,
        chunk_embedding_max_length=s.wiki.chunk_embedding_max_length,
        batch_size=s.wiki.chunk_embedding_batch_size,
    )
    result = await indexer.index_all_chunks(body.repository)
    return JSONResponse(content=result)


@router.post("/qa/record", response_model=None)
async def wiki_record_qa(
    body: WikiQaRecordBody,
    mem: MemoryLoop | None = Depends(get_wiki_memory_loop_dep),
) -> dict[str, Any]:
    """Store a Q&A pair (e.g. after wiki ask) as :WikiQA with embedding."""
    if mem is None:
        raise KbServiceUnavailable("Wiki memory loop is not configured")
    uid = await mem.record(
        body.question, body.answer, list(body.source_pages), business_id=body.business_id,
    )
    return {"ok": True, "uid": uid}


@router.post("/{repository}/lint", response_model=None)
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
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc
    scope = body.scope if body else "all"
    return await lint_svc.run_lint(repository, scope=scope)


@router.post(
    "/{repository}/export/preview",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_export_preview(
    repository: str,
    body: WikiExportPreviewBody,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
    exporter: Any = Depends(get_wiki_docs_exporter_dep),
) -> dict[str, Any]:
    """Preview wiki → markdown export for ``target_dir`` without writing files."""
    try:
        await wiki_svc.ensure_repository(repository)
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc
    result = await exporter.preview_export(
        repository,
        body.target_dir,
        include_auto_generated_marker=body.include_auto_generated_marker,
    )
    return export_result_to_dict(result)


@router.post(
    "/{repository}/export/execute",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_export_execute(
    repository: str,
    body: WikiExportExecuteBody,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
    exporter: Any = Depends(get_wiki_docs_exporter_dep),
) -> dict[str, Any]:
    """Write selected wiki pages as markdown under ``target_dir``."""
    try:
        await wiki_svc.ensure_repository(repository)
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc
    result = await exporter.execute_export(repository, body.target_dir, selected_files=body.selected_files)
    return export_result_to_dict(result)


@router.get("/merge-candidates", response_model=None)
async def wiki_merge_candidates(
    request: Request,
    business_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """List cross-repository merge candidate pairs (embedding similarity)."""
    settings = get_route_settings()
    if not settings.wiki.concept_merging_enabled:
        raise KbNotFound("Concept merging is disabled")
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")
    from wiki.concept_merger import ConceptMerger

    merger = ConceptMerger(
        raw_store,
        similarity_threshold=settings.wiki.concept_merge_similarity_threshold,
    )
    candidates = await merger.find_candidates(business_id)
    return {"candidates": [asdict(c) for c in candidates]}


@router.post("/ingest")
async def wiki_ingest(req: IngestRequest, request: Request) -> dict[str, Any]:
    """Trigger incremental wiki regeneration for changed files."""
    if not req.files and not req.git_ref:
        return {
            "pages_regenerated": 0,
            "pages_total": 0,
            "trigger": "api",
            "message": "No files specified",
        }

    detector = getattr(request.app.state, "change_detector", None)
    factory = getattr(request.app.state, "wiki_service_factory", None)

    if detector is None or factory is None:
        raise KbServiceUnavailable("Incremental ingest not configured")

    affected = await detector.detect_from_file_list(
        req.repository, req.files, trigger="api"
    )
    out = factory()
    service = await out if asyncio.iscoroutine(out) else out
    result = await service.bump_affected_wiki_pages(req.repository, affected)
    return result


@router.get("/changelog")
async def wiki_changelog(
    repository: str,
    request: Request,
    limit: int = 20,
) -> dict[str, Any]:
    """Get wiki change audit trail."""
    changelog_store = getattr(request.app.state, "wiki_changelog_store", None)
    if changelog_store is None:
        return {"changelogs": []}

    logs = await changelog_store.list_changelogs(repository, limit=limit)
    return {"changelogs": logs}
