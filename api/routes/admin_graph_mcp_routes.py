"""Route group: admin_graph_mcp_routes (extracted from main)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse

import api.kb_state as kb_state
from api.exceptions import KbClientError, KbNotFound
from api.routes import kb_routers
from api.routes.kb_dependencies import get_effective_business_id, get_service
from auth import Role, TokenInfo, require_role
from config import get_settings
from api.routes.kb_schemas import (
    BlastRadiusRequest,
    GraphExpandRequest,
    GraphExploreRequest,
    GraphQueryRequest,
    ImpactAnalysisRequest,
    MCPToolCallRequest,
    ReviewContextRequest,
    SmartContextRequest,
)
from services.kb_service import KnowledgeBaseService
from store.graph_queries import GraphQueryRepository, validate_architecture_class_search
from utils.git_utils import looks_like_git_url
from log import get_logger

log = get_logger(__name__)
viewer_router = kb_routers.viewer_router
editor_router = kb_routers.editor_router
admin_router = kb_routers.admin_router
public_router = kb_routers.public_router

@admin_router.delete("/index/{repository:path}")
async def delete_repository_index(
    repository: str,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Delete all indexed data for a specific repository."""
    queries = GraphQueryRepository(svc.store)
    deleted = await queries.delete_repository(repository)
    return {"repository": repository, "deleted_nodes": deleted}


@admin_router.get("/index/report/{repository:path}")
async def get_index_report(
    repository: str,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Get the last indexing quality report for a repository."""
    report = svc.incremental_indexer.get_last_report()
    if report is None:
        return {"repository": repository, "report": None, "message": "No indexing report available"}
    return {"repository": repository, "report": report.to_dict()}


@admin_router.post("/enrich/graph")
async def enrich_graph(
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Run GraphEnricher on existing index data without re-parsing source files."""
    from indexer.graph_enricher import GraphEnricher

    enricher = GraphEnricher(svc.store)
    result = await enricher.enrich()
    return {"status": "completed", **result}


@admin_router.post("/enrich/cross-repo")
async def enrich_cross_repo(
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Run cross-repo enrichment: RPC resolution, DI graph, Entity mapping."""
    from indexer.cross_repo_enricher import CrossRepoEnricher

    enricher = CrossRepoEnricher(svc.store)
    result = await enricher.enrich_all()
    return {"status": "completed", **result}


@editor_router.post("/review/context")
async def build_review_context(
    req: ReviewContextRequest,
    svc: KnowledgeBaseService = Depends(get_service),
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
        raise KbClientError(str(exc)) from exc
    return ctx.to_dict()


@editor_router.post("/context/build")
async def build_smart_context(
    req: SmartContextRequest,
    svc: KnowledgeBaseService = Depends(get_service),
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
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """List all discovered API endpoints for a repository."""
    from query.endpoint_queries import query_all_endpoints

    return await query_all_endpoints(svc.store, repository)


@admin_router.post("/analysis/impact")
async def analyze_impact(
    req: ImpactAnalysisRequest,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Analyze the impact of changed functions."""
    from query.analysis_service import AnalysisService

    analysis = AnalysisService(svc.store)
    report = await analysis.analyze_impact(req.changed_functions, max_depth=req.max_depth)
    return report.to_dict()


@admin_router.get("/analysis/consistency/{repository:path}")
async def check_consistency(
    repository: str,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Check index consistency for a repository."""
    from services.git_manager import resolve_repo_clone_root
    from query.analysis_service import AnalysisService

    settings = get_settings()
    resolved = resolve_repo_clone_root(repository, settings.git, kb_state.repo_registry)
    if resolved is None:
        raise KbNotFound(f"Repository '{repository}' not found on disk")
    base_path = Path(settings.git.clone_base_path).resolve()
    if not resolved.is_relative_to(base_path):
        raise KbClientError(f"Repository path escapes clone base: {repository}")

    analysis = AnalysisService(svc.store)
    report = await analysis.verify_consistency(str(resolved), repository=repository)
    return {"repository": repository, **report.to_dict()}


@admin_router.get("/architecture/{repository:path}")
async def get_architecture(
    repository: str,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Get architecture layer breakdown."""
    from query.endpoint_queries import query_architecture_layers

    return await query_architecture_layers(svc.store, repository)


@admin_router.post("/admin/cleanup-excluded-dirs")
async def cleanup_excluded_dirs(
    svc: KnowledgeBaseService = Depends(get_service),
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
    svc: KnowledgeBaseService = Depends(get_service),
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
            {
                "id": r["uid"],
                "name": r["name"],
                "type": r["type"],
                "file": r["file"],
                "line": r["line"],
                "end_line": r.get("end_line"),
                "signature": r.get("signature") or "",
                "docstring": r.get("docstring") or "",
            }
            for r in result.data
            if r.get("uid")
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
            "end_line": r.get("end_line"),
            "signature": r.get("signature") or "",
            "docstring": r.get("docstring") or "",
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


@viewer_router.post("/graph/expand")
async def graph_expand(
    req: GraphExpandRequest,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Incremental neighbor expansion around a named entity for progressive graph rendering."""

    from query.graph_query import GraphQueryService

    gq = GraphQueryService(svc.store)
    return await gq.expand_node(
        req.node_name,
        center_uid=req.center_uid,
        limit=req.limit,
        depth=req.depth,
        exclude_uids=req.exclude_uids,
    )


@viewer_router.post("/graph/blast-radius")
async def graph_blast_radius(
    req: BlastRadiusRequest,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Upstream blast-radius impact from changed entities (callers, importers, subclasses)."""
    from query.blast_radius import BlastRadiusAnalyzer

    analyzer = BlastRadiusAnalyzer(svc.store)
    return await analyzer.analyze(
        req.entity_names,
        max_depth=req.max_depth,
        repository=req.repository,
    )


@viewer_router.get("/graph/communities")
async def graph_communities(
    repository: str | None = None,
    min_size: int = Query(default=3, ge=2, le=50),
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Community detection (label propagation) over Function/Class code graph."""
    from query.community_detection import CommunityDetector

    detector = CommunityDetector(svc.store)
    return await detector.detect(repository=repository, min_community_size=min_size)


@admin_router.post("/admin/backfill-fqn")
async def backfill_fqn(
    svc: KnowledgeBaseService = Depends(get_service),
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
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Return the code snippet for a node, useful when KB is on a remote machine."""
    queries = GraphQueryRepository(svc.store)
    data = await queries.get_code_snippet(node_uid)
    if not data:
        raise KbNotFound("Node not found")
    return data


@viewer_router.post("/mcp/tool")
async def mcp_tool_call(
    req: MCPToolCallRequest,
    svc: KnowledgeBaseService = Depends(get_service),
    token_info: TokenInfo | None = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """MCP-compatible tool call endpoint."""
    return await svc.mcp_handler.handle_tool_call(
        req.tool_name, req.arguments, token_info=token_info,
    )


@viewer_router.get("/mcp/tools")
async def mcp_tools_list(
    svc: KnowledgeBaseService = Depends(get_service),
) -> list[dict[str, Any]]:
    """List available MCP tools."""
    return svc.mcp_handler.get_tools_manifest()

