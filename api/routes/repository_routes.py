"""Route group: repository_routes (extracted from main)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

import api.kb_state as kb_state
from api.routes import kb_routers
from api.routes.kb_dependencies import get_effective_business_id, get_service
from api.routes.kb_schemas import PrFetchRequest
from api.routes.repository_path_utils import (
    build_file_tree,
    infer_section_levels,
    relative_file_path,
)
from service import KnowledgeBaseService
from store.graph_queries import GraphQueryRepository, validate_architecture_class_search
from utils.git_utils import looks_like_git_url
from log import get_logger

log = get_logger(__name__)
viewer_router = kb_routers.viewer_router
editor_router = kb_routers.editor_router
admin_router = kb_routers.admin_router
public_router = kb_routers.public_router

@viewer_router.get("/stats")
async def graph_stats(
    repository: str | None = None,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    stats = await svc.graph_query.get_graph_stats()
    if repository:
        queries = GraphQueryRepository(svc.store)
        stats["repository"] = repository
        stats["repository_nodes"] = await queries.get_repository_node_count(repository)
    return stats


@viewer_router.get("/stats/p2")
async def get_p2_stats(
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Return P2 enrichment stats for dashboard."""
    return await svc.graph_query.get_p2_stats()


@viewer_router.get("/stats/health")
async def get_knowledge_health_stats(
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Knowledge graph health: index coverage, staleness, orphans, totals."""
    if svc.store.graph is None:
        raise HTTPException(status_code=503, detail="Graph store is not connected")
    queries = GraphQueryRepository(svc.store)
    return await queries.get_knowledge_health_stats()


@viewer_router.get("/graph/insights/{repository:path}")
async def get_graph_insights(
    repository: str,
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Return automated graph insights (isolation, cycles, layering, cohesion, bridges)."""
    if svc.store.graph is None:
        raise HTTPException(status_code=503, detail="Graph store is not connected")
    from query.graph_insights import GraphInsightsService

    insights_svc = GraphInsightsService(svc.store)
    report = await insights_svc.analyze(repository)
    return report.to_dict()


async def _enriched_repository_rows(svc: KnowledgeBaseService) -> list[dict[str, Any]]:
    """Indexed repository rows merged with optional ``RepoRegistry`` git metadata."""
    queries = GraphQueryRepository(svc.store)
    repos = await queries.list_repositories()
    reg_by_repo: dict[str, dict[str, Any]] = {}
    if kb_state.repo_registry:
        for entry in kb_state.repo_registry.list_all():
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
    return repos


@viewer_router.get("/repositories")
async def list_repositories(
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """List all indexed repositories with node counts and optional git URL metadata."""
    repos = await _enriched_repository_rows(svc)
    return {"repositories": repos, "total": len(repos)}


@viewer_router.post("/pr/fetch")
async def fetch_pr_changed_files(
    req: PrFetchRequest,
    svc: KnowledgeBaseService = Depends(get_service),
    git_remote_token: str | None = Header(default=None, alias="X-Git-Remote-Token"),
) -> dict[str, Any]:
    """Resolve a GitHub PR or GitLab MR URL and return changed file paths for PR impact analysis."""
    from api.pr_fetch import fetch_pr_from_url, resolve_indexed_repository

    settings = get_settings()
    override = (git_remote_token or "").strip()
    gl_t = override or (settings.git.gitlab_token or "").strip()
    gh_t = override or (settings.git.github_token or "").strip()

    try:
        raw = await fetch_pr_from_url(req.url.strip(), gitlab_token=gl_t, github_token=gh_t)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        snippet = (exc.response.text or "")[:800]
        raise HTTPException(
            status_code=502,
            detail=f"Git host API error ({exc.response.status_code}): {snippet}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Git host: {exc}") from exc

    rows = await _enriched_repository_rows(svc)
    resolved, warning = resolve_indexed_repository(raw["canonical_path"], rows)
    return {
        "repository": resolved,
        "changed_files": raw["changed_files"],
        "provider": raw["provider"],
        "warning": warning,
    }


def relative_file_path(file_path: str, repository: str | None) -> str:
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


def build_file_tree(rows: list[dict[str, Any]], repository: str) -> dict[str, Any]:
    """Convert flat Module ``file`` paths into a nested directory/file tree."""
    root: dict[str, Any] = {"name": "/", "type": "directory", "children": [], "path": ""}
    for row in rows:
        raw_file = row.get("file") or ""
        file_path = raw_file.replace("\\", "/")
        if not file_path:
            continue
        parts = [p for p in file_path.split("/") if p]
        current = root
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            existing = next((c for c in current["children"] if c["name"] == part), None)
            if existing is None:
                if is_file:
                    node: dict[str, Any] = {
                        "name": part,
                        "type": "file",
                        "path": file_path,
                    }
                    repo_val = row.get("repository") or repository
                    if repo_val:
                        node["repository"] = repo_val
                else:
                    node = {
                        "name": part,
                        "type": "directory",
                        "path": "/".join(parts[: i + 1]),
                        "children": [],
                    }
                current["children"].append(node)
                current = node if not is_file else current
            else:
                current = existing if not is_file else current

    def sort_tree(node: dict[str, Any]) -> None:
        ch = node.get("children")
        if isinstance(ch, list) and ch:
            ch.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
            for child in ch:
                sort_tree(child)

    sort_tree(root)
    return root


@viewer_router.get("/files/tree")
async def get_file_tree(
    repository: str = Query(..., min_length=1),
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Return a nested directory tree built from Module nodes for a specific repository."""
    store = svc.store
    cypher = (
        "MATCH (m:Module) WHERE m.repository = $repo "
        "AND NOT coalesce(m.file, m.path) STARTS WITH '<import:' "
        "RETURN coalesce(m.file, m.path) AS file, m.name AS name, m.repository AS repository "
        "ORDER BY file"
    )
    params: dict[str, Any] = {"repo": repository}

    result = await store.execute_query(cypher, params)
    tree = build_file_tree(result.data, repository)
    return tree


@viewer_router.get("/files/content")
async def get_file_content(
    repository: str = Query(...),
    file_path: str = Query(...),
    start_line: int | None = Query(default=None, ge=1),
    end_line: int | None = Query(default=None, ge=1),
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Read file content from indexed repository on disk (via MCP handler)."""
    rel = relative_file_path(file_path.replace("\\", "/").strip(), repository).lstrip("/")
    payload: dict[str, Any] = {
        "repository": repository,
        "file_path": rel,
        "start_line": start_line,
        "end_line": end_line,
    }
    result = await svc.mcp_handler.handle_get_file_content(payload)
    if "error" in result:
        code = result["error"]["code"]
        status = 404 if code == "not_found" else 400
        raise HTTPException(status_code=status, detail=result["error"]["message"])
    return result


@viewer_router.get("/files/entities")
async def get_file_entities(
    file_path: str = Query(...),
    svc: KnowledgeBaseService = Depends(get_service),
) -> dict[str, Any]:
    """Return functions and classes defined in a file (graph ``file`` path)."""
    result = await svc.graph_query.find_file_entities(file_path)
    entities: list[dict[str, Any]] = []
    for row in result.data:
        line = row.get("line")
        entities.append({
            "uid": row.get("uid"),
            "name": row.get("name"),
            "type": row.get("type"),
            "start_line": line,
            "end_line": row.get("end_line"),
            "signature": row.get("signature") or "",
            "docstring": row.get("docstring") or "",
        })
    return {"entities": entities, "file": file_path}


@viewer_router.get("/documents")
async def list_documents(
    repository: str | None = None,
    svc: KnowledgeBaseService = Depends(get_service),
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
                "file": relative_file_path(raw_file, repo),
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

def infer_section_levels(sections: list[dict[str, Any]], file_path: str | None = None) -> None:
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
    svc: KnowledgeBaseService = Depends(get_service),
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
        infer_section_levels(sections, file_path=first.get("file"))

    for s in sections:
        if s.get("level") is None:
            s["level"] = 2

    return {
        "title": first.get("title") or "",
        "file": relative_file_path(raw_file, repo),
        "repository": repo,
        "sections": sections,
    }

