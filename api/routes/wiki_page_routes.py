"""Wiki pages, search, tree, exports, coverage, and repository-scoped page APIs."""

from __future__ import annotations

import asyncio
import io as _io
import zipfile as _zipfile
from dataclasses import asdict
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from api.exceptions import KbNotFound, KbServiceUnavailable
from auth import Role, require_role
from services.git_manager import normalize_repo_name
from store.schema import EdgeType
from store.wiki_store import WikiStore
from wiki.coverage_analyzer import WikiCoverageAnalyzer
from wiki.models import ImportanceTier, PageType, WikiPage, WikiPageMetadata
from wiki.quality_evaluator import WikiQualityEvaluator
from wiki.quality_score import WikiQualityScorer
from wiki.service import WikiRepoNotFoundError, WikiService
from wiki.search import SearchResponse
from api.models.wiki_models import (
    AnalyzeImpactBody,
    BusinessWikiExportBody,
    WikiGlobalSearchBody,
    WikiPageContentBody,
    WikiSearchBody,
)
from api.routes.kb_routers import editor_router
from api.routes.kb_dependencies import get_effective_business_id
from api.routes.wiki_shared import (
    _GLOBAL_SEARCH_CONCURRENCY,
    _GLOBAL_SEARCH_MAX_REPOS,
    _indexed_repository_names,
    _page_type_to_scope,
    _search_response_to_json,
    get_graph_query_dep,
    get_route_settings,
    get_wiki_editing_store_dep,
    get_wiki_search_dep,
    get_wiki_service_dep,
    get_wiki_store_dep,
    log,
)
from wiki.editing_store import WikiEditingStore
from wiki.models import navigation_context_api_from_stored_json

router = APIRouter(tags=["wiki", "pages"])


async def _resolve_primary_source_entity_uid(
    raw_store: Any,
    repository: str,
    path: str,
    props: dict[str, Any],
) -> str:
    """Primary code entity uid for RELATED_TO lookups (WikiPage SOURCE_ENTITY targets)."""
    eu = str(props.get("entity_uid") or "").strip()
    if eu:
        return eu
    try:
        ws = WikiStore(raw_store)
        q = (
            f"MATCH (wp:WikiPage {{repository: $repo, path: $path}})"
            f"-[:{EdgeType.SOURCE_ENTITY.value}]->(e) "
            "RETURN e.uid AS uid LIMIT 1"
        )
        r = await ws.execute_query(q, {"repo": repository, "path": path})
        rows = getattr(r, "data", None) or []
        row0 = rows[0] if rows else {}
        uid = str((row0 or {}).get("uid") or "").strip()
        return uid
    except Exception:  # noqa: BLE001
        return ""


async def _build_related_pages(
    raw_store: Any,
    repository: str,
    entity_uid: str,
) -> list[dict[str, Any]]:
    """Fetch related neighbors (RELATED_TO plus structural edges) as lightweight dicts."""
    related_pages: list[dict[str, Any]] = []
    if not entity_uid or not getattr(raw_store, "find_related_entities", None):
        return related_pages
    repo_norm = normalize_repo_name(repository)
    try:
        related = await raw_store.find_related_entities(
            entity_uid,
            edge_types=["RELATED_TO", "CALLS", "IMPORTS", "INHERITS"],
            max_hops=1,
        )
    except Exception:  # noqa: BLE001
        return related_pages
    pairs = related[:10]
    for rel_uid, _ in pairs:
        title = rel_uid
        page_type_str = ""
        biz: Any = None
        if getattr(raw_store, "find_node_by_uid", None):
            try:
                rel_node = await raw_store.find_node_by_uid(repo_norm, rel_uid)
                if rel_node:
                    rn_props = dict(rel_node.properties) if hasattr(rel_node, "properties") else {}
                    title = str(rn_props.get("name", rel_uid) or rel_uid)
                    lab = rel_node.label
                    page_type_str = lab.value if hasattr(lab, "value") else str(lab)
                    biz = rn_props.get("business_domain")
            except Exception:  # noqa: BLE001
                pass
        related_pages.append(
            {
                "uid": rel_uid,
                "title": title,
                "page_type": page_type_str,
                "business_domain": biz,
            }
        )
    return related_pages


def _wiki_quality_rows_to_pages_and_tiers(
    rows: list[dict[str, Any]],
) -> tuple[list[WikiPage], dict[str, ImportanceTier]]:
    pages: list[WikiPage] = []
    tier_map: dict[str, ImportanceTier] = {}
    for row in rows:
        path = row.get("path")
        if not path:
            continue
        raw_pt = row.get("page_type") or "class_detail"
        try:
            page_type = PageType(str(raw_pt))
        except ValueError:
            page_type = PageType.CLASS_DETAIL
        tier_raw = str(row.get("importance_tier") or "").strip().lower()
        path_s = str(path)
        if tier_raw:
            try:
                tier_map[path_s] = ImportanceTier(tier_raw)
            except ValueError:
                tier_map[path_s] = ImportanceTier.STANDARD
        else:
            tier_map[path_s] = ImportanceTier.STANDARD
        pages.append(
            WikiPage(
                path=path_s,
                title=str(row.get("title") or ""),
                page_type=page_type,
                content=str(row.get("content") or ""),
                diagrams=[],
                source_locations=[],
                metadata=WikiPageMetadata(0, 0),
            )
        )
    return pages, tier_map


@router.post("/search", response_model=None)
async def wiki_search(
    body: WikiSearchBody,
    search_svc: Any = Depends(get_wiki_search_dep),
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


@router.post("/search/global", response_model=None)
async def wiki_search_global(
    body: WikiGlobalSearchBody,
    request: Request,
    search_svc: Any = Depends(get_wiki_search_dep),
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


@router.get("/pages/by-path")
async def wiki_get_page_by_path(
    request: Request,
    business_id: str = Query(default="default"),
    path: str = Query(...),
) -> dict[str, Any]:
    """Fetch a wiki page by its path under a business space."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")

    store = WikiStore(raw_store)
    result = await store.get_page_by_path(business_id, path)
    if not result.data:
        raise KbNotFound(f"Wiki page not found: {path}")

    row = result.data[0]
    sources_raw = row.get("sources") or []
    source_locations: list[dict[str, Any]] = []
    source_entity_uids: list[str] = []
    for s in sources_raw:
        if isinstance(s, dict) and s.get("file_path"):
            source_locations.append(s)
        if isinstance(s, dict):
            eu = str(s.get("entity_uid") or "").strip()
            if eu and eu not in source_entity_uids:
                source_entity_uids.append(eu)

    is_stale = "false"
    page_uid = str(row.get("uid") or "")
    settings = get_route_settings()
    if page_uid and settings.wiki.stale_detection_enabled:
        stale_count = await store.get_page_stale_source_count(page_uid)
        if stale_count > 0:
            is_stale = "true"

    ctx: dict[str, str] = {
        "repository": str(row.get("repository") or ""),
        "page_type": str(row.get("page_type") or ""),
        "importance_tier": str(row.get("importance_tier") or ""),
        "uid": page_uid,
        "is_stale": is_stale,
    }
    qo = row.get("quality_overall")
    if qo is not None and str(qo).strip() != "":
        ctx["quality_overall"] = str(qo)
    if row.get("confidence_score") is not None:
        ctx["confidence_score"] = str(row.get("confidence_score"))
    if page_uid and settings.wiki.contradiction_detection_enabled:
        c_rows = await store.list_wiki_contradictions_for_page(
            page_uid,
            include_resolved=False,
        )
        ctx["unresolved_contradictions"] = str(len(c_rows))
        if c_rows:
            d0 = c_rows[0].get("description") or ""
            ctx["contradiction_summary"] = str(d0)[:500]

    repo_for_graph = str(row.get("repository") or "")
    entity_for_related = source_entity_uids[0] if source_entity_uids else ""
    related_pages = await _build_related_pages(raw_store, repo_for_graph, entity_for_related)

    return {
        "path": str(row.get("path") or ""),
        "title": str(row.get("title") or ""),
        "content": str(row.get("content") or ""),
        "diagrams": [],
        "source_locations": source_locations,
        "source_entity_uids": source_entity_uids,
        "method_locations": [],
        "context": ctx,
        "generated_at": str(row.get("generated_at") or "") or None,
        "related_pages": related_pages,
    }


@router.get("/pages/by-source-entity", response_model=None)
async def wiki_get_path_by_source_entity(
    request: Request,
    business_id: str = Query(default="default"),
    entity_uid: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Return a wiki page path for a code entity linked via SOURCE_ENTITY, if any."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    cypher = (
        "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
        "MATCH (wp)-[:SOURCE_ENTITY]->(e {uid: $entity_uid}) "
        "RETURN coalesce(wp.path, '') AS path LIMIT 1"
    )
    result = await raw_store.execute_query(
        cypher, {"business_id": business_id, "entity_uid": entity_uid}
    )
    row = (getattr(result, "data", None) or [None])[0]
    p = str((row or {}).get("path") or "").strip() if row else ""
    return {"path": p or None}


@router.get("/pages/claim-history", response_model=None)
async def wiki_list_claim_history(
    request: Request,
    page_uid: str = Query(..., min_length=1, description="WikiPage uid (URL-encoded)"),
) -> dict[str, Any]:
    """Return WikiClaimHistory rows for a page (see SP5 supersession)."""
    if not get_route_settings().wiki.supersession_tracking_enabled:
        return {"items": []}
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    rows = await store.list_wiki_claims_for_page(page_uid)
    return {"items": rows}


@router.get("/flows", response_model=None)
async def wiki_business_flows(
    request: Request,
    business_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Return BusinessFlow nodes (and optional edges) for business wiki visualization."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")
    cypher = (
        "MATCH (ws:WikiSpace {business_id: $business_id})-[:HAS_CHILD*1..10]->(wp:WikiPage) "
        "WITH collect(DISTINCT wp.repository) AS raw_repos "
        "WITH [r IN raw_repos WHERE r IS NOT NULL AND r <> ''] AS repos "
        "MATCH (bf:BusinessFlow) "
        "WHERE bf.repository IN repos "
        "RETURN bf.uid AS uid, bf.name AS name, coalesce(bf.description, '') AS description, "
        "coalesce(bf.category, '') AS category, coalesce(bf.repository, '') AS repository "
        "LIMIT 200"
    )
    result = await raw_store.execute_query(cypher, {"business_id": business_id})
    rows = getattr(result, "data", None) or []
    nodes: list[dict[str, Any]] = []
    for r in rows:
        uid = str(r.get("uid") or "")
        if not uid:
            continue
        nodes.append(
            {
                "uid": uid,
                "title": str(r.get("name") or uid),
                "description": str(r.get("description") or ""),
                "type": "business_flow",
            }
        )
    return {"nodes": nodes, "edges": []}


@router.get("/tree")
async def wiki_get_tree(
    request: Request,
    business_id: str = Query(default="default"),
    view: str = Query(default="business_domain"),
    wiki_tier: Literal["comprehensive", "standard", "essential"] | None = Query(
        default=None,
        description="Importance tier filter: comprehensive (all), standard (no skeleton/supplementary), or essential (core+essential only)",
    ),
) -> dict[str, Any]:
    """Return the wiki tree structure for the given business and view type."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        return {"tree": [], "view_type": view, "business_id": business_id}

    store = WikiStore(raw_store)
    result = await store.get_wiki_tree(business_id, view, wiki_tier=wiki_tier)
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


@router.post(
    "/export",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def business_wiki_export(
    body: BusinessWikiExportBody,
    request: Request,
) -> Any:
    """Export business wiki in various formats (markdown, zip, git, obsidian, mkdocs)."""
    from api.exceptions import KbClientError
    from wiki.business_wiki_exporter import BusinessWikiExporter
    from wiki.git_publisher import GitPublisher
    from wiki.mkdocs_exporter import MkDocsExporter
    from wiki.obsidian_exporter import ObsidianExporter

    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")

    wiki_store = WikiStore(raw_store)

    if body.format == "git" and body.git_config is None:
        raise KbClientError("git_config is required for git format")

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
        settings = get_route_settings()
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


@router.get("/pages/{page_uid:path}/versions", response_model=None)
async def wiki_list_page_versions(
    request: Request,
    page_uid: str,
    business_id: str = Depends(get_effective_business_id),
) -> list[dict[str, Any]]:
    """Version history for a wiki page (``WikiVersion``-shaped rows for the dashboard)."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    return await store.list_wiki_page_versions(decoded)


@router.get("/pages/{page_uid:path}/diff", response_model=None)
async def wiki_page_version_diff(
    request: Request,
    page_uid: str,
    from_version: int = Query(..., ge=0, description="Source version (inclusive)"),
    to_version: int = Query(..., ge=0, description="Target version (inclusive)"),
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    """Unified-diff-style ``WikiDiff`` for two logical versions of a page."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    out = await store.get_wiki_page_version_diff(decoded, from_version, to_version)
    if out is None:
        raise KbNotFound("One or both versions are not available for this page")
    return out


@router.get("/pages/{page_uid:path}/references", response_model=None)
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


@router.get("/coverage-report", response_model=None)
async def wiki_coverage_report(
    request: Request,
    business_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Return wiki documentation coverage analysis for a business."""
    settings = get_route_settings()
    if not settings.wiki.coverage_report_enabled:
        raise KbNotFound("Coverage report is disabled")

    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")

    wiki_store = WikiStore(raw_store)
    analyzer = WikiCoverageAnalyzer(wiki_store)
    report = await analyzer.analyze(
        business_id, include_stale=settings.wiki.stale_detection_enabled,
    )

    return report.to_dict()


@router.get("/quality-score", response_model=None)
async def wiki_quality_score(
    request: Request,
    business_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Aggregate quality score 0-100 (coverage, staleness, references, enrichment)."""
    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")
    ws = WikiStore(raw_store)
    scorer = WikiQualityScorer(ws)
    result = await scorer.compute_score(business_id)
    return result.to_dict()


@router.get("/references", response_model=None)
async def wiki_business_references(
    request: Request,
    business_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Wiki reference network for a business: pages and WIKI_REFERENCES edges (both ends in space)."""
    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")
    ws = WikiStore(raw_store)
    return await ws.get_business_wiki_references_graph(business_id)


@router.get("/qa", response_model=None)
async def wiki_list_qa(
    request: Request,
    business_id: str = Query(..., min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    """Paginated :WikiQA entries for a business."""
    raw_store = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Graph store not configured")
    ws = WikiStore(raw_store)
    r = await ws.list_wiki_qa(business_id, skip, limit)
    return {"items": r.data or [], "skip": skip, "limit": limit, "total": await ws.count_wiki_qa(business_id)}


@router.post("/{repository}/analyze-impact", response_model=None)
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
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
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
        raise KbServiceUnavailable("graph_query_failed") from exc


@router.get("/{repository}/enrichment-status", response_model=None)
async def wiki_enrichment_status(
    repository: str,
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Return enrichment level counts for persisted wiki pages in the repository."""
    repo = normalize_repo_name(repository)
    try:
        return await wiki_svc.get_enrichment_status(repo)
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc


@router.get("/{repository}/documentation-quality/summary", response_model=None)
async def wiki_documentation_quality_summary(
    repository: str,
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    """Aggregate persisted documentation quality scores for a repository (WikiPage graph properties)."""
    settings = get_route_settings()
    repo = normalize_repo_name(repository)
    ws = WikiStore(store)
    min_score = float(getattr(settings.wiki, "quality_min_score", 0.6) or 0.6)
    return await ws.get_quality_summary(repo, min_score=min_score)


@router.post(
    "/{repository}/documentation-quality/evaluate",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def wiki_documentation_quality_evaluate(
    repository: str,
    store: Any = Depends(get_wiki_store_dep),
    mode: Literal["quick", "sampled", "full"] = Query(default="quick"),
    wiki_svc: WikiService = Depends(get_wiki_service_dep),
) -> dict[str, Any]:
    """Run documentation quality evaluation and persist scores on WikiPage nodes."""
    settings = get_route_settings()
    repo = normalize_repo_name(repository)
    try:
        await wiki_svc.ensure_repository(repo)
    except WikiRepoNotFoundError as exc:
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc

    ws = WikiStore(store)
    rows = await ws.list_wiki_pages_for_quality_evaluation(repo)
    pages, tier_map = _wiki_quality_rows_to_pages_and_tiers(rows)

    if not pages:
        return {"mode": mode, "summary": {"overall": 0, "page_count": 0}, "evaluated_pages": 0}

    sample_size = int(getattr(settings.wiki, "quality_sample_size", 20) or 20)
    if mode == "sampled":
        sampler = WikiQualityEvaluator(llm=None)
        pages = sampler.select_sample_pages(pages, tier_map, sample_size=sample_size)

    judge_model = str(getattr(settings.wiki, "quality_judge_model", "") or "")
    llm_port = None if mode == "quick" else wiki_svc._resolve_llm_port(None)
    evaluator = WikiQualityEvaluator(llm=llm_port, judge_model=judge_model)

    if mode == "quick":
        scores = [evaluator.structural_check(p) for p in pages]
    else:
        scores = [await evaluator.llm_judge_evaluate(p) for p in pages]

    await ws.save_quality_scores(repo, scores)
    summary = evaluator.aggregate_scores(scores, tier_map)

    min_score = float(getattr(settings.wiki, "quality_min_score", 0.6) or 0.6)
    if summary.get("overall", 1.0) < min_score:
        log.warning(
            "wiki_quality_below_threshold",
            repository=repo,
            score=summary.get("overall"),
            threshold=min_score,
        )

    return {"mode": mode, "summary": summary, "evaluated_pages": len(scores)}


@router.post(
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
        raise KbNotFound(
            f"Repository '{exc.repository}' not indexed. Use /wiki/quick to auto-index."
        ) from exc


@router.get("/{repository}/offline-pack", response_model=None)
async def wiki_offline_pack(
    repository: str,
    business_id: str | None = Query(default=None),
    store: Any = Depends(get_wiki_store_dep),
) -> JSONResponse:
    """Return a JSON package of wiki pages, tree, and optional snapshot for offline use."""
    from wiki.offline_pack import WikiOfflinePack

    pack = WikiOfflinePack(store)
    result = await pack.build(repository, business_id or "")
    return JSONResponse(content=result, media_type="application/json")


@router.get("/{repository}/pages", response_model=None)
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


@router.get("/{repository}/pages/{wiki_page_path:path}", response_model=None)
async def wiki_get_page_detail(
    repository: str,
    wiki_page_path: str,
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    decoded_path = unquote(wiki_page_path).lstrip("/")
    result = await WikiStore(store).get_wiki_page_detail(repository, decoded_path)
    if not result.data:
        raise KbNotFound(f"No wiki page at path {decoded_path!r}")
    row = result.data[0]
    wp = row.get("wp")
    props = dict(wp.properties) if hasattr(wp, "properties") else (wp if isinstance(wp, dict) else {})
    ctx = {"repository": repository, "module": "", "page": decoded_path}
    entity_uid = await _resolve_primary_source_entity_uid(store, repository, decoded_path, props)
    related_pages = await _build_related_pages(store, repository, entity_uid)
    return {
        "path": props.get("path", ""),
        "title": props.get("title", ""),
        "content": props.get("content", ""),
        "diagrams": [],
        "source_locations": [],
        "method_locations": [],
        "context": ctx,
        "generated_at": props.get("generated_at"),
        "related_pages": related_pages,
    }


@router.get("/{repository}/navigation", response_model=None)
async def get_wiki_page_navigation(
    repository: str,
    path: str = Query(..., description="Wiki page path"),
    store: Any = Depends(get_wiki_store_dep),
) -> dict[str, Any]:
    """Return NavigationContext for a persisted wiki page (empty defaults if unset)."""
    repo = normalize_repo_name(repository)
    decoded_path = unquote(path).lstrip("/")
    ws = WikiStore(store)
    result = await ws.get_wiki_page_navigation_row(repo, decoded_path)
    if not result.data:
        raise KbNotFound(f"No wiki page at path {decoded_path!r}")
    raw = result.data[0].get("navigation_json")
    return navigation_context_api_from_stored_json(
        str(raw) if raw is not None else None,
    )


def _raw_bearer_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str | None:
    if not authorization:
        token_q = request.query_params.get("token")
        if token_q:
            authorization = f"Bearer {token_q}"
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:].strip() or None


def _client_host(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


@editor_router.post("/wiki/pages/{page_uid:path}/editing", response_model=None)
async def wiki_page_editing_heartbeat(
    request: Request,
    page_uid: str,
    business_id: str = Depends(get_effective_business_id),
    raw_token: str | None = Depends(_raw_bearer_token),
    editing_store: WikiEditingStore | None = Depends(get_wiki_editing_store_dep),
) -> dict[str, Any]:
    """Register or refresh editing presence (heartbeat) for a wiki page."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    if editing_store is None:
        return {"ok": True, "degraded": True}
    eid = WikiEditingStore.editor_fingerprint(
        token=raw_token, client_host=_client_host(request),
    )
    await editing_store.heartbeat(decoded, eid)
    return {"ok": True, "degraded": False}


@editor_router.delete("/wiki/pages/{page_uid:path}/editing", response_model=None)
async def wiki_page_editing_stop(
    request: Request,
    page_uid: str,
    business_id: str = Depends(get_effective_business_id),
    raw_token: str | None = Depends(_raw_bearer_token),
    editing_store: WikiEditingStore | None = Depends(get_wiki_editing_store_dep),
) -> Response:
    """Remove editing presence for the current client."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    if editing_store is not None:
        eid = WikiEditingStore.editor_fingerprint(
            token=raw_token, client_host=_client_host(request),
        )
        await editing_store.stop(decoded, eid)
    return Response(status_code=204)


@editor_router.get("/wiki/pages/{page_uid:path}/editors", response_model=None)
async def wiki_page_list_editors(
    request: Request,
    page_uid: str,
    business_id: str = Depends(get_effective_business_id),
    raw_token: str | None = Depends(_raw_bearer_token),
    editing_store: WikiEditingStore | None = Depends(get_wiki_editing_store_dep),
) -> dict[str, Any]:
    """List active editors; ``other_active`` is true if another client is also editing."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    if editing_store is None:
        return {"editors": [], "other_active": False, "degraded": True}
    self_id = WikiEditingStore.editor_fingerprint(
        token=raw_token, client_host=_client_host(request),
    )
    out = await editing_store.list_editors(decoded, self_editor_id=self_id)
    return {**out, "degraded": False}


@editor_router.patch("/wiki/pages/{page_uid:path}/content", response_model=None)
async def wiki_edit_page_content(
    page_uid: str,
    body: WikiPageContentBody,
    request: Request,
    business_id: str = Depends(get_effective_business_id),
) -> dict[str, Any]:
    """Update wiki page body with optimistic concurrency (LWW) and a ``WikiPageVersion`` snapshot."""
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise KbServiceUnavailable("Wiki store unavailable")
    store = WikiStore(raw_store)
    decoded = unquote(page_uid)
    if not await store.assert_wiki_page_in_business(business_id, decoded):
        raise KbNotFound(f"Wiki page not found: {decoded}")
    out = await store.update_wiki_page_content(
        decoded,
        body.content,
        source="human_edit",
        expected_version=body.expected_version,
        edit_reason=body.edit_reason,
    )
    if not out.get("ok"):
        if out.get("error") == "wiki_page_not_found":
            raise KbNotFound(f"Wiki page not found: {decoded}")
        raise KbServiceUnavailable(str(out.get("error", "update_failed")))
    return out


wiki_page_router = router
