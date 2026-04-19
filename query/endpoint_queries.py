"""Shared queries for API endpoint discovery and architecture layer breakdown.

Used by both REST routes (main.py) and MCP tool handlers (api/mcp_server.py).
"""

from __future__ import annotations

from typing import Any

from store.analysis_store import AnalysisStore
from store.falkordb_store import FalkorDBStore


async def query_all_endpoints(
    store: FalkorDBStore,
    repository: str = "",
    *,
    analysis_store: AnalysisStore | None = None,
) -> dict[str, Any]:
    analysis = analysis_store or AnalysisStore(store)

    res = await analysis.query_http_endpoints(repository)
    endpoints = [
        {
            "name": r.get("name"),
            "path": r.get("path"),
            "method": r.get("method") or "GET",
            "file": r.get("file"),
            "class": r.get("class_name"),
            "layer": r.get("layer"),
        }
        for r in res.data
    ]

    rpc_res = await analysis.query_rpc_endpoints(repository)
    rpc_endpoints = [
        {
            "class": r.get("class_name"),
            "interface": r.get("interface"),
            "method": r.get("method_name"),
            "layer": r.get("layer"),
        }
        for r in rpc_res.data
    ]

    kafka_res = await analysis.query_kafka_endpoints(repository)
    kafka_endpoints = [
        {
            "name": r.get("name"),
            "topic": r.get("topic"),
            "file": r.get("file"),
        }
        for r in kafka_res.data
    ]

    return {
        "repository": repository,
        "http_endpoints": endpoints,
        "rpc_endpoints": rpc_endpoints,
        "kafka_endpoints": kafka_endpoints,
        "total": len(endpoints) + len(rpc_endpoints) + len(kafka_endpoints),
    }


async def query_architecture_layers(
    store: FalkorDBStore,
    repository: str = "",
    *,
    analysis_store: AnalysisStore | None = None,
) -> dict[str, Any]:
    analysis = analysis_store or AnalysisStore(store)
    res = await analysis.query_architecture_layer_counts(repository)
    layers = {r.get("layer"): r.get("count") for r in res.data if r.get("layer")}
    return {"repository": repository, "layers": layers}
