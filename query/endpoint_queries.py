"""Shared queries for API endpoint discovery and architecture layer breakdown.

Used by both REST routes (main.py) and MCP tool handlers (api/mcp_server.py).
"""

from __future__ import annotations

from typing import Any

from store.falkordb_store import FalkorDBStore


async def query_all_endpoints(
    store: FalkorDBStore,
    repository: str = "",
) -> dict[str, Any]:
    repo_filter = "AND f.repository = $repo " if repository else ""
    cls_repo_filter = "AND c.repository = $repo " if repository else ""
    params: dict[str, Any] = {"repo": repository} if repository else {}

    http_q = (
        "MATCH (f:Function) WHERE f.api_path IS NOT NULL "
        f"{repo_filter}"
        "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
        "RETURN f.name AS name, f.api_path AS path, f.http_method AS method, "
        "f.file AS file, c.name AS class_name, c.architecture_layer AS layer "
        "ORDER BY f.api_path"
    )
    res = await store.execute_query(http_q, params)
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

    rpc_q = (
        "MATCH (c:Class) WHERE c.rpc_interface IS NOT NULL "
        f"{cls_repo_filter}"
        "OPTIONAL MATCH (c)-[:CONTAINS]->(f:Function) "
        "RETURN c.name AS class_name, c.rpc_interface AS interface, "
        "f.name AS method_name, c.architecture_layer AS layer"
    )
    rpc_res = await store.execute_query(rpc_q, params)
    rpc_endpoints = [
        {
            "class": r.get("class_name"),
            "interface": r.get("interface"),
            "method": r.get("method_name"),
            "layer": r.get("layer"),
        }
        for r in rpc_res.data
    ]

    kafka_q = (
        "MATCH (f:Function) WHERE f.kafka_topic IS NOT NULL "
        f"{repo_filter}"
        "RETURN f.name AS name, f.kafka_topic AS topic, f.file AS file"
    )
    kafka_res = await store.execute_query(kafka_q, params)
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
) -> dict[str, Any]:
    repo_filter = "WHERE c.architecture_layer IS NOT NULL AND c.repository = $repo" if repository else "WHERE c.architecture_layer IS NOT NULL"
    params: dict[str, Any] = {"repo": repository} if repository else {}

    q = (
        f"MATCH (c:Class) {repo_filter} "
        "RETURN c.architecture_layer AS layer, count(c) AS count "
        "ORDER BY count DESC"
    )
    res = await store.execute_query(q, params)
    layers = {r.get("layer"): r.get("count") for r in res.data if r.get("layer")}
    return {"repository": repository, "layers": layers}
