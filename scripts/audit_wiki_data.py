#!/usr/bin/env python3
"""Audit wiki data by querying FalkorDB directly.

Usage (on dev machine):
    cd ~/review-bot/knowledge-base-service
    source .venv/bin/activate
    python scripts/audit_wiki_data.py --business-id ultron --output /tmp/wiki-audit.json

Usage (remote via SSH):
    ssh dev 'cd ~/review-bot/knowledge-base-service && source .venv/bin/activate && python scripts/audit_wiki_data.py --business-id ultron' > data/wiki-audit.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any


async def query_wiki_data(business_id: str, graph_name: str | None = None) -> dict[str, Any]:
    """Query all wiki data from FalkorDB for a business."""
    from falkordb import FalkorDB as FalkorDBClient

    from core.config import get_settings

    settings = get_settings()
    gname = graph_name or f"kb_{business_id}"
    db = FalkorDBClient(host=settings.falkordb.host, port=settings.falkordb.port)
    graph = db.select_graph(gname)

    class _Store:
        """Minimal wrapper to reuse existing query logic."""

        async def execute_query(self, cypher: str, params: dict) -> Any:
            import asyncio

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: graph.query(cypher, params=params))
            header = [col[1] if isinstance(col, (list, tuple)) else str(col) for col in (result.header or [])]
            data = [dict(zip(header, row)) for row in (result.result_set or [])]

            class _R:
                pass

            r = _R()
            r.data = data  # type: ignore[attr-defined]
            return r

        async def close(self) -> None:
            pass

    store = _Store()

    results: dict[str, Any] = {"business_id": business_id, "graph_name": gname}

    # 1. All WikiPage nodes
    pages_q = (
        "MATCH (wp:WikiPage) "
        "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
        "wp.page_type AS page_type, wp.repository AS repository, "
        "wp.content AS content, wp.generated_at AS generated_at, "
        "coalesce(wp.canonical_key, '') AS canonical_key, "
        "coalesce(wp.business_domain, '') AS business_domain "
        "ORDER BY wp.path"
    )
    pages_result = await store.execute_query(pages_q, {})
    pages_data = getattr(pages_result, "data", None) or []
    pages = []
    for row in pages_data:
        content = str(row.get("content") or "")
        pages.append({
            "uid": str(row.get("uid") or ""),
            "title": str(row.get("title") or ""),
            "path": str(row.get("path") or ""),
            "page_type": str(row.get("page_type") or ""),
            "repository": str(row.get("repository") or ""),
            "content_len": len(content),
            "content_preview": content[:500] if content else "",
            "generated_at": str(row.get("generated_at") or ""),
            "canonical_key": str(row.get("canonical_key") or ""),
            "business_domain": str(row.get("business_domain") or ""),
        })
    results["pages"] = pages
    results["total_pages"] = len(pages)

    # 2. WikiSection nodes (domains)
    sections_q = (
        "MATCH (ws:WikiSection) "
        "RETURN ws.uid AS uid, ws.title AS title, "
        "ws.section_type AS section_type, ws.sort_order AS sort_order "
        "ORDER BY ws.sort_order"
    )
    sections_result = await store.execute_query(sections_q, {})
    sections_data = getattr(sections_result, "data", None) or []
    sections = []
    for row in sections_data:
        sections.append({
            "uid": str(row.get("uid") or ""),
            "title": str(row.get("title") or ""),
            "section_type": str(row.get("section_type") or ""),
            "sort_order": row.get("sort_order"),
        })
    results["sections"] = sections
    results["total_sections"] = len(sections)

    # 3. Domain tree from WikiSpace
    tree_q = (
        "MATCH (ws:WikiSpace)-[:HAS_CHILD]->(sec:WikiSection) "
        "OPTIONAL MATCH (sec)-[:HAS_CHILD]->(child:WikiSection) "
        "RETURN ws.uid AS space_uid, sec.uid AS section_uid, "
        "sec.title AS section_title, sec.section_type AS section_type, "
        "coalesce(child.uid, '') AS child_uid, "
        "coalesce(child.title, '') AS child_title "
        "ORDER BY sec.sort_order"
    )
    tree_result = await store.execute_query(tree_q, {})
    tree_data = getattr(tree_result, "data", None) or []
    results["tree_edges"] = [
        {
            "space_uid": str(row.get("space_uid") or ""),
            "section_uid": str(row.get("section_uid") or ""),
            "section_title": str(row.get("section_title") or ""),
            "section_type": str(row.get("section_type") or ""),
            "child_uid": str(row.get("child_uid") or ""),
            "child_title": str(row.get("child_title") or ""),
        }
        for row in tree_data
    ]

    # 3b. Section → Page edges (HAS_CHILD from WikiSection to WikiPage)
    sec_page_q = (
        "MATCH (sec:WikiSection)-[:HAS_CHILD]->(wp:WikiPage) "
        "RETURN sec.uid AS section_uid, sec.title AS section_title, "
        "wp.uid AS page_uid, wp.path AS page_path, wp.page_type AS page_type "
        "ORDER BY sec.uid, wp.path"
    )
    sec_page_result = await store.execute_query(sec_page_q, {})
    sec_page_data = getattr(sec_page_result, "data", None) or []
    results["section_page_edges"] = [
        {
            "section_uid": str(row.get("section_uid") or ""),
            "section_title": str(row.get("section_title") or ""),
            "page_uid": str(row.get("page_uid") or ""),
            "page_path": str(row.get("page_path") or ""),
            "page_type": str(row.get("page_type") or ""),
        }
        for row in sec_page_data
    ]
    results["total_section_page_edges"] = len(sec_page_data)

    # 4. Summary statistics
    domain_overviews = [p for p in pages if p["page_type"] == "domain_overview"]
    topics = [p for p in pages if p["page_type"] == "topic"]
    other_pages = [p for p in pages if p["page_type"] not in ("domain_overview", "topic")]

    domain_slugs = set()
    for p in pages:
        path = p["path"]
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "__domains__":
            domain_slugs.add(parts[1])

    # Content length stats
    overview_lens = [p["content_len"] for p in domain_overviews]
    topic_lens = [p["content_len"] for p in topics]
    thin_overviews = [p for p in domain_overviews if p["content_len"] < 2000]
    thin_topics = [p for p in topics if p["content_len"] < 1000]

    # Domains with/without topics
    domains_with_topics: set[str] = set()
    for p in topics:
        parts = p["path"].strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "__domains__":
            domains_with_topics.add(parts[1])

    domains_without_topics = domain_slugs - domains_with_topics

    # CN ratio estimation
    import re
    cn_re = re.compile(r"[\u4e00-\u9fff]")
    low_cn_pages = []
    for p in pages:
        preview = p["content_preview"]
        if len(preview) < 50:
            continue
        cn_count = len(cn_re.findall(preview))
        ratio = cn_count / len(preview) if preview else 0
        if ratio < 0.15:
            low_cn_pages.append({"path": p["path"], "title": p["title"], "cn_ratio": round(ratio, 3)})

    results["stats"] = {
        "total_pages": len(pages),
        "domain_overviews": len(domain_overviews),
        "topics": len(topics),
        "other_pages": len(other_pages),
        "unique_domain_slugs": len(domain_slugs),
        "domains_with_topics": len(domains_with_topics),
        "domains_without_topics": len(domains_without_topics),
        "thin_overviews_lt_2000": len(thin_overviews),
        "thin_topics_lt_1000": len(thin_topics),
        "overview_len_avg": round(sum(overview_lens) / len(overview_lens)) if overview_lens else 0,
        "overview_len_min": min(overview_lens) if overview_lens else 0,
        "overview_len_max": max(overview_lens) if overview_lens else 0,
        "topic_len_avg": round(sum(topic_lens) / len(topic_lens)) if topic_lens else 0,
        "topic_len_min": min(topic_lens) if topic_lens else 0,
        "topic_len_max": max(topic_lens) if topic_lens else 0,
        "low_cn_ratio_pages": len(low_cn_pages),
    }

    results["domain_slugs"] = sorted(domain_slugs)
    results["domains_without_topics"] = sorted(domains_without_topics)
    results["thin_overviews"] = sorted(thin_overviews, key=lambda p: p["content_len"])[:20]
    results["low_cn_pages"] = sorted(low_cn_pages, key=lambda p: p["cn_ratio"])[:20]

    await store.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Audit wiki data from FalkorDB")
    parser.add_argument("--business-id", default="ultron", help="Business ID to query")
    parser.add_argument("--graph", default=None, help="FalkorDB graph name (default: kb_{business_id})")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    args = parser.parse_args()

    data = asyncio.run(query_wiki_data(args.business_id, graph_name=args.graph))

    output = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Written to {args.output} ({len(output)} bytes)", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
