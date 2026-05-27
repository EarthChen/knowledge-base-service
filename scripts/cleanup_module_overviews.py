#!/usr/bin/env python3
"""One-time cleanup of legacy module_overview pages from FalkorDB.

Usage:
    cd knowledge-base-service
    PYTHONPATH=. uv run python scripts/cleanup_module_overviews.py --business-id ultron
"""
from __future__ import annotations

import argparse
import asyncio


async def cleanup(business_id: str, graph_name: str | None = None) -> int:
    """Delete legacy module_overview pages."""
    from falkordb import FalkorDB as FalkorDBClient

    from core.config import get_settings

    settings = get_settings()
    gname = graph_name or f"kb_{business_id}"
    db = FalkorDBClient(host=settings.falkordb.host, port=settings.falkordb.port)
    graph = db.select_graph(gname)

    q = (
        "MATCH (wp:WikiPage {page_type: 'module_overview'}) "
        "DETACH DELETE wp "
        "RETURN count(wp) AS deleted"
    )
    result = graph.query(q)
    deleted = result.result_set[0][0] if result.result_set else 0
    print(f"Deleted {deleted} module_overview pages from {gname}")
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup legacy module_overview pages")
    parser.add_argument("--business-id", default="ultron")
    parser.add_argument("--graph", default=None)
    args = parser.parse_args()
    asyncio.run(cleanup(args.business_id, graph_name=args.graph))


if __name__ == "__main__":
    main()
