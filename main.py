"""Knowledge Base Service — standalone FastAPI application.

Provides HTTP endpoints for code/document indexing and querying,
backed by FalkorDB graph database and sentence-transformers embeddings.
Supports multi-business isolation via independent FalkorDB graphs.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import Role, TokenInfo, get_current_role, require_role, resolve_business_id, resolve_token
from config import get_settings
from log import get_logger, setup_logging
from service import KnowledgeBaseService
from service_registry import ServiceRegistry

log = get_logger(__name__)

_registry: ServiceRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _registry
    settings = get_settings()
    setup_logging(level=settings.log_level)
    log.info("kb_service_starting", host=settings.host, port=settings.port)

    _registry = ServiceRegistry(settings)
    await _registry.start()

    app.state.registry = _registry
    log.info("kb_service_started")
    yield

    log.info("kb_service_stopping")
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


class IndexRequest(BaseModel):
    directory: str
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


class GraphExploreRequest(BaseModel):
    name: str = ""
    depth: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=100, ge=1, le=500)


class MCPToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)


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


@editor_router.post("/index")
async def trigger_index(
    req: IndexRequest,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    args = req.model_dump()
    if req.repository:
        args["repository"] = req.repository
    result = await svc.mcp_handler.handle_rag_index(args)

    if req.repository:
        await svc.store.execute_query(
            "MATCH (n) WHERE n.file STARTS WITH $dir AND n.repository IS NULL SET n.repository = $repo",
            {"dir": req.directory, "repo": req.repository},
        )

    return result


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
                from indexer.embedding_generator import EmbeddingGenerator
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
    cypher = "MATCH (n) WHERE n.file = $file SET n.repository = $repo"
    await svc.store.execute_query(cypher, {"file": file_path, "repo": repository})


@viewer_router.get("/stats")
async def graph_stats(
    repository: str | None = None,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    stats = await svc.graph_query.get_graph_stats()
    if repository:
        repo_count = await svc.store.execute_query(
            "MATCH (n) WHERE n.repository = $repo RETURN count(n) AS cnt",
            {"repo": repository},
        )
        stats["repository"] = repository
        stats["repository_nodes"] = repo_count.data[0]["cnt"] if repo_count.data else 0
    return stats


@viewer_router.get("/repositories")
async def list_repositories(
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """List all indexed repositories with node counts."""
    result = await svc.store.execute_query(
        "MATCH (n) WHERE n.repository IS NOT NULL "
        "RETURN n.repository AS repo, count(n) AS cnt "
        "ORDER BY cnt DESC",
        {},
    )
    repos = [{"repository": r["repo"], "nodes": r["cnt"]} for r in result.data]
    return {"repositories": repos, "total": len(repos)}


@admin_router.delete("/index/{repository}")
async def delete_repository_index(
    repository: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Delete all indexed data for a specific repository."""
    result = await svc.store.execute_query(
        "MATCH (n) WHERE n.repository = $repo DETACH DELETE n RETURN count(n) AS deleted",
        {"repo": repository},
    )
    deleted = result.data[0]["deleted"] if result.data else 0
    return {"repository": repository, "deleted_nodes": deleted}


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

    if not req.name:
        overview_q = (
            "MATCH (n) "
            "WHERE n:Function OR n:Class OR n:Module "
            "WITH n, rand() AS r ORDER BY r LIMIT $limit "
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, "
            "n.file AS file, n.start_line AS line"
        )
        result = await svc.store.execute_query(overview_q, {"limit": req.limit})
        nodes = [
            {"id": r["uid"], "name": r["name"], "type": r["type"],
             "file": r["file"], "line": r["line"]}
            for r in result.data if r.get("uid")
        ]
        return {"nodes": nodes, "edges": []}

    nodes_q = (
        "MATCH (center) "
        "WHERE (center:Function OR center:Class OR center:Module) "
        "AND (center.name = $name OR center.fqn = $name) "
        f"OPTIONAL MATCH (center)-[*1..{req.depth}]-(neighbor) "
        "WHERE neighbor:Function OR neighbor:Class OR neighbor:Module "
        "WITH center, collect(DISTINCT neighbor) AS nbrs "
        "UNWIND ([center] + nbrs) AS n "
        "WITH DISTINCT n LIMIT $limit "
        "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, "
        "n.file AS file, n.start_line AS line"
    )
    nodes_result = await svc.store.execute_query(nodes_q, {"name": req.name, "limit": req.limit})

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

    edges_q = (
        "MATCH (a)-[rel]->(b) "
        "WHERE a.uid IN $uids AND b.uid IN $uids "
        "RETURN a.uid AS source, b.uid AS target, type(rel) AS rel_type"
    )
    edges_result = await svc.store.execute_query(edges_q, {"uids": node_uids})

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
    result = await svc.store.execute_query(
        "MATCH (n) WHERE (n:Class OR n:Function) AND n.file ENDS WITH '.java' "
        "AND n.fqn IS NULL "
        "RETURN n.uid AS uid, n.name AS name, n.file AS file, labels(n)[0] AS label",
    )

    updated = 0
    for row in result.data:
        label = row.get("label", "")
        parent_class = ""
        if label == "Function":
            file_fqn = row.get("file", "")
            cls_result = await svc.store.execute_query(
                "MATCH (c:Class)-[:CONTAINS]->(f:Function {uid: $uid}) RETURN c.name AS cname LIMIT 1",
                {"uid": row["uid"]},
            )
            if cls_result.data:
                parent_class = cls_result.data[0].get("cname", "")

        fqn = compute_fqn(row.get("file", ""), row.get("name", ""), label, parent_class=parent_class)
        if fqn:
            await svc.store.execute_query(
                "MATCH (n {uid: $uid}) SET n.fqn = $fqn",
                {"uid": row["uid"], "fqn": fqn},
            )
            updated += 1

    return {"updated": updated, "total_checked": len(result.data)}


@viewer_router.get("/code/{node_uid:path}")
async def get_code_snippet(
    node_uid: str,
    svc: KnowledgeBaseService = Depends(_get_service),
) -> dict[str, Any]:
    """Return the code snippet for a node, useful when KB is on a remote machine."""
    result = await svc.store.execute_query(
        "MATCH (n {uid: $uid}) "
        "RETURN n.name AS name, n.file AS file, n.start_line AS start_line, "
        "n.end_line AS end_line, coalesce(n.code_snippet, '') AS code_snippet, "
        "coalesce(n.signature, '') AS signature, coalesce(n.docstring, '') AS docstring, "
        "coalesce(n.fqn, '') AS fqn, labels(n)[0] AS type",
        {"uid": node_uid},
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Node not found")
    return result.data[0]


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
async def health() -> dict[str, str]:
    return {"status": "ok"}


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


_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

_SPA_ROUTES = {"search", "graph", "explorer", "repositories", "indexing", "settings", "businesses"}


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
