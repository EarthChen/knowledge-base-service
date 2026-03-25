"""Knowledge Base Service — standalone FastAPI application.

Provides HTTP endpoints for code/document indexing and querying,
backed by FalkorDB graph database and sentence-transformers embeddings.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from config import get_settings
from log import get_logger, setup_logging
from service import KnowledgeBaseService

log = get_logger(__name__)

_kb_service: KnowledgeBaseService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _kb_service
    settings = get_settings()
    setup_logging(level=settings.log_level)
    log.info("kb_service_starting", host=settings.host, port=settings.port)

    _kb_service = KnowledgeBaseService(settings)
    await _kb_service.start()

    app.state.kb_service = _kb_service
    log.info("kb_service_started")
    yield

    log.info("kb_service_stopping")
    if _kb_service:
        await _kb_service.stop()
    log.info("kb_service_stopped")


def _get_service() -> KnowledgeBaseService:
    if _kb_service is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return _kb_service


def _verify_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.api_token:
        expected = f"Bearer {settings.api_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(_verify_token)])


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


class MCPToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/search")
async def semantic_search(req: SemanticSearchRequest) -> dict[str, Any]:
    svc = _get_service()
    if req.entity_type == "function":
        result = await svc.semantic_query.search_functions(req.query, k=req.k)
    elif req.entity_type == "class":
        result = await svc.semantic_query.search_classes(req.query, k=req.k)
    elif req.entity_type == "document":
        result = await svc.semantic_query.search_documents(req.query, k=req.k)
    else:
        result = await svc.semantic_query.search_all(req.query, k=req.k)
    return {"matches": result.matches, "total": result.total, "query": result.query_text}


@router.post("/graph")
async def graph_query(req: GraphQueryRequest) -> dict[str, Any]:
    svc = _get_service()
    return await svc.mcp_handler.handle_rag_graph(req.model_dump())


@router.post("/hybrid")
async def hybrid_search(req: HybridSearchRequest) -> dict[str, Any]:
    svc = _get_service()
    result = await svc.hybrid_query.search_with_context(req.query, k=req.k, expand_depth=req.expand_depth)
    return {
        "semantic_matches": result.semantic_matches,
        "graph_context": result.graph_context,
        "total": result.total,
        "query": result.query_text,
    }


@router.post("/index")
async def trigger_index(req: IndexRequest) -> dict[str, Any]:
    svc = _get_service()
    args = req.model_dump()
    if req.repository:
        args["repository"] = req.repository
    return await svc.mcp_handler.handle_rag_index(args)


@router.post("/index/files")
async def index_files(req: IndexFilesRequest) -> dict[str, Any]:
    """Index files by directly passing their content — no local directory needed.

    Useful for CI pipelines that provide file content from git diff,
    or when the KB service doesn't have access to the repository.
    """
    svc = _get_service()

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


@router.get("/stats")
async def graph_stats(repository: str | None = None) -> dict[str, Any]:
    svc = _get_service()
    stats = await svc.graph_query.get_graph_stats()
    if repository:
        repo_count = await svc.store.execute_query(
            "MATCH (n) WHERE n.repository = $repo RETURN count(n) AS cnt",
            {"repo": repository},
        )
        stats["repository"] = repository
        stats["repository_nodes"] = repo_count.data[0]["cnt"] if repo_count.data else 0
    return stats


@router.get("/repositories")
async def list_repositories() -> dict[str, Any]:
    """List all indexed repositories with node counts."""
    svc = _get_service()
    result = await svc.store.execute_query(
        "MATCH (n) WHERE n.repository IS NOT NULL "
        "RETURN n.repository AS repo, count(n) AS cnt "
        "ORDER BY cnt DESC",
        {},
    )
    repos = [{"repository": r["repo"], "nodes": r["cnt"]} for r in result.data]
    return {"repositories": repos, "total": len(repos)}


@router.delete("/index/{repository}")
async def delete_repository_index(repository: str) -> dict[str, Any]:
    """Delete all indexed data for a specific repository."""
    svc = _get_service()
    result = await svc.store.execute_query(
        "MATCH (n) WHERE n.repository = $repo DETACH DELETE n RETURN count(n) AS deleted",
        {"repo": repository},
    )
    deleted = result.data[0]["deleted"] if result.data else 0
    return {"repository": repository, "deleted_nodes": deleted}


@router.post("/mcp/tool")
async def mcp_tool_call(req: MCPToolCallRequest) -> dict[str, Any]:
    """MCP-compatible tool call endpoint."""
    svc = _get_service()
    return await svc.mcp_handler.handle_tool_call(req.tool_name, req.arguments)


@router.get("/mcp/tools")
async def mcp_tools_list() -> list[dict[str, Any]]:
    """List available MCP tools."""
    svc = _get_service()
    return svc.mcp_handler.get_tools_manifest()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Knowledge Base Service",
        description="Code knowledge base with graph + vector search",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
