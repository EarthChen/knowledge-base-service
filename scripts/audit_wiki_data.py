#!/usr/bin/env python3
"""Audit wiki data by querying FalkorDB directly.

Usage:
    # On dev machine (recommended)
    ssh dev "cd ~/review-bot/knowledge-base-service && PYTHONPATH=. .venv/bin/python scripts/audit_wiki_data.py --full-content --output data/wiki-audit.json"
    scp dev:~/review-bot/knowledge-base-service/data/wiki-audit.json data/

    # With repository filter (exclude stale module_overview from other repos)
    ssh dev "cd ~/review-bot/knowledge-base-service && PYTHONPATH=. .venv/bin/python scripts/audit_wiki_data.py --full-content --repo ultron --output data/wiki-audit.json"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any

_ENGLISH_H2_RE = re.compile(r"^## [A-Z][A-Za-z][\w ]*$", re.MULTILINE)


def _compute_cn_ratio(content: str) -> float:
    """Compute Chinese character ratio, stripping code fences."""
    text = re.sub(r"```[\s\S]*?```", "", content or "")
    if not text:
        return 0.0
    cn_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return round(cn_count / len(text), 4)


def _extract_english_h2_list(content: str) -> list[str]:
    """Extract H2 headings that are primarily English."""
    return _ENGLISH_H2_RE.findall(content or "")


def _extract_h2_list(content: str) -> list[str]:
    """Extract all H2 headings from content."""
    return re.findall(r"^## .+$", content or "", re.MULTILINE)


def _detect_hallucination_patterns(content: str) -> list[str]:
    """Detect common LLM hallucination patterns in wiki content."""
    patterns = []
    hallucination_res = [
        (r"\d+\.\d+%", "fabricated percentage"),
        (r"\b\d{2,3}%", "fabricated round percentage"),
        (r"≤\d+s|≥\d+\.\d+", "fabricated SLA"),
        (r"P\d{2}\s*[<≤]\s*\d+", "fabricated latency SLA"),
        (r"留存.*[+\-]\d+", "fabricated retention metric"),
        (r"健身|看护|儿童", "fabricated business scenario"),
        (r"\d{4}年\d{1,2}月\d{1,2}日", "fabricated date"),
        (r"\d{4}-\d{2}-\d{2}\s+复核", "fabricated review date"),
    ]
    text = re.sub(r"```[\s\S]*?```", "", content or "")
    for pat, desc in hallucination_res:
        if re.search(pat, text):
            patterns.append(desc)
    return patterns


def _detect_render_issues(content: str) -> list[str]:
    """Detect Markdown rendering problems."""
    issues = []
    if re.search(r"^## .+\n[a-z]", content or "", re.MULTILINE):
        issues.append("h2_line_break")
    if re.search(r"```\w*\n\s*```", content or ""):
        issues.append("empty_code_block")
    if re.search(r"\[\[\s*\]\]", content or ""):
        issues.append("empty_wikilink")
    return issues


async def query_wiki_data(
    business_id: str,
    graph_name: str | None = None,
    full_content: bool = False,
    repo_filter: str | None = None,
) -> dict[str, Any]:
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

    # 1. All WikiPage nodes (with optional repo filter)
    if repo_filter:
        pages_q = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $repo "
            "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
            "wp.page_type AS page_type, wp.repository AS repository, "
            "wp.content AS content, wp.generated_at AS generated_at, "
            "coalesce(wp.canonical_key, '') AS canonical_key, "
            "coalesce(wp.business_domain, '') AS business_domain "
            "ORDER BY wp.path"
        )
        pages_result = await store.execute_query(pages_q, {"repo": repo_filter})
    else:
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
        english_h2s = _extract_english_h2_list(content)
        page_entry: dict[str, Any] = {
            "uid": str(row.get("uid") or ""),
            "title": str(row.get("title") or ""),
            "path": str(row.get("path") or ""),
            "page_type": str(row.get("page_type") or ""),
            "repository": str(row.get("repository") or ""),
            "content_length": len(content),
            "content_preview": content[:500] if content else "",
            "cn_ratio": _compute_cn_ratio(content),
            "has_english_h2": len(english_h2s) > 0,
            "english_h2_list": english_h2s,
            "h2_list": _extract_h2_list(content),
            "hallucination_flags": _detect_hallucination_patterns(content),
            "render_issues": _detect_render_issues(content),
            "generated_at": str(row.get("generated_at") or ""),
            "canonical_key": str(row.get("canonical_key") or ""),
            "business_domain": str(row.get("business_domain") or ""),
        }
        if full_content:
            page_entry["content"] = content
        pages.append(page_entry)
    results["pages"] = pages
    results["total_pages"] = len(pages)
    if repo_filter:
        results["repo_filter"] = repo_filter

    # 2. WikiSection nodes (domains)
    sections_q = (
        "MATCH (ws:WikiSection) "
        "RETURN ws.uid AS uid, ws.title AS title, "
        "ws.section_type AS section_type, ws.sort_order AS sort_order "
        "ORDER BY ws.sort_order"
    )
    sections_result = await store.execute_query(sections_q, {})
    sections_data = getattr(sections_result, "data", None) or []

    children_count_q = (
        "MATCH (sec:WikiSection)-[:HAS_CHILD]->(child) "
        "WHERE sec.uid CONTAINS $business_id "
        "RETURN sec.uid AS section_uid, count(child) AS children_count"
    )
    children_count_result = await store.execute_query(children_count_q, {"business_id": business_id})
    children_count_data = getattr(children_count_result, "data", None) or []
    children_count_by_uid = {
        str(row.get("section_uid") or ""): int(row.get("children_count") or 0) for row in children_count_data
    }

    sections = []
    for row in sections_data:
        uid = str(row.get("uid") or "")
        sections.append({
            "uid": uid,
            "title": str(row.get("title") or ""),
            "section_type": str(row.get("section_type") or ""),
            "sort_order": row.get("sort_order"),
            "children_count": children_count_by_uid.get(uid, 0),
        })
    results["sections"] = sections
    results["total_sections"] = len(sections)

    # 3. Full section/page hierarchy (WikiSpace and WikiSection parents)
    tree_q = (
        "MATCH (p)-[r:HAS_CHILD]->(c) "
        "WHERE (p:WikiSection OR p:WikiSpace) "
        "AND (c:WikiSection OR c:WikiPage) "
        "AND p.uid CONTAINS $business_id "
        "RETURN labels(p)[0] AS parent_type, p.uid AS parent_uid, p.title AS parent_title, "
        "labels(c)[0] AS child_type, c.uid AS child_uid, c.title AS child_title, "
        "r.view_type AS view_type "
        "ORDER BY parent_uid, child_uid"
    )
    tree_result = await store.execute_query(tree_q, {"business_id": business_id})
    tree_data = getattr(tree_result, "data", None) or []
    results["tree_edges"] = [
        {
            "parent_type": str(row.get("parent_type") or ""),
            "parent_uid": str(row.get("parent_uid") or ""),
            "parent_title": str(row.get("parent_title") or ""),
            "child_type": str(row.get("child_type") or ""),
            "child_uid": str(row.get("child_uid") or ""),
            "child_title": str(row.get("child_title") or ""),
            "view_type": row.get("view_type"),
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
    overview_lens = [p["content_length"] for p in domain_overviews]
    topic_lens = [p["content_length"] for p in topics]
    thin_overviews = [p for p in domain_overviews if p["content_length"] < 2000]
    thin_topics = [p for p in topics if p["content_length"] < 1000]

    # Domains with/without topics
    domains_with_topics: set[str] = set()
    for p in topics:
        parts = p["path"].strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "__domains__":
            domains_with_topics.add(parts[1])

    domains_without_topics = domain_slugs - domains_with_topics

    # CN ratio estimation (full content via per-page cn_ratio)
    low_cn_pages = []
    for p in pages:
        ratio = p["cn_ratio"]
        if p["content_length"] < 50:
            continue
        if ratio < 0.25:
            low_cn_pages.append({"path": p["path"], "title": p["title"], "cn_ratio": ratio, "page_type": p["page_type"]})

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
    results["thin_overviews"] = sorted(thin_overviews, key=lambda p: p["content_length"])[:20]
    results["low_cn_pages"] = sorted(low_cn_pages, key=lambda p: p["cn_ratio"])[:20]

    # Render issue summary
    pages_with_render_issues = [
        {"path": p["path"], "title": p["title"], "issues": p["render_issues"]}
        for p in pages if p.get("render_issues")
    ]
    results["pages_with_render_issues"] = pages_with_render_issues
    results["stats"]["pages_with_render_issues"] = len(pages_with_render_issues)

    # Stub topics (< 1500 chars)
    stub_topics = [
        {"path": p["path"], "title": p["title"], "content_length": p["content_length"]}
        for p in topics if p["content_length"] < 1500
    ]
    results["stub_topics"] = sorted(stub_topics, key=lambda p: p["content_length"])

    # Duplicate H2 detection within pages
    pages_with_dup_h2 = []
    for p in pages:
        h2s = p.get("h2_list", [])
        seen: set[str] = set()
        dups: list[str] = []
        for h in h2s:
            if h in seen:
                dups.append(h)
            seen.add(h)
        if dups:
            pages_with_dup_h2.append({"path": p["path"], "title": p["title"], "duplicate_h2s": dups})
    results["pages_with_duplicate_h2"] = pages_with_dup_h2

    # 5. Tree depth and structure analysis
    tree_edges = results.get("tree_edges", [])
    parent_to_children: dict[str, list[str]] = {}
    for edge in tree_edges:
        pid = edge["parent_uid"]
        cid = edge["child_uid"]
        parent_to_children.setdefault(pid, []).append(cid)

    def _compute_max_depth(node_uid: str, depth: int = 0) -> int:
        children = parent_to_children.get(node_uid, [])
        if not children:
            return depth
        return max(_compute_max_depth(c, depth + 1) for c in children)

    root_uids = [s["uid"] for s in sections if "__root__" in s["uid"]]
    max_tree_depth = 0
    for root_uid in root_uids:
        max_tree_depth = max(max_tree_depth, _compute_max_depth(root_uid))

    root_section = next((s for s in sections if "__root__" in s["uid"]), None)
    l1_domain_count = root_section["children_count"] if root_section else 0

    shell_sections = []
    for s in sections:
        if s["section_type"] != "business_domain":
            continue
        uid = s["uid"]
        if "__root__" in uid:
            continue
        has_child_sections = any(
            e["parent_uid"] == uid and e["child_type"] == "WikiSection" for e in tree_edges
        )
        has_topics = any(
            e["parent_uid"] == uid and e["child_type"] == "WikiPage"
            and any(p["path"] == (e.get("child_uid", "").split(":")[-1] if ":" in e.get("child_uid", "") else "")
                    for p in topics)
            for e in tree_edges
        )
        section_has_topic_children = False
        for edge in tree_edges:
            if edge["parent_uid"] == uid and edge["child_type"] == "WikiPage":
                child_title = edge["child_title"]
                for p in topics:
                    if p["title"] == child_title:
                        section_has_topic_children = True
                        break
            if section_has_topic_children:
                break
        if has_child_sections and not section_has_topic_children:
            shell_sections.append({"uid": uid, "title": s["title"], "children_count": s["children_count"]})

    results["stats"]["max_tree_depth"] = max_tree_depth
    results["stats"]["l1_domain_count"] = l1_domain_count
    results["stats"]["shell_sections"] = len(shell_sections)
    results["shell_sections"] = shell_sections

    # 6. Duplicate title detection
    title_to_pages: dict[str, list[dict[str, str]]] = {}
    for p in pages:
        if p["page_type"] in ("domain_overview", "topic"):
            title_to_pages.setdefault(p["title"], []).append({"path": p["path"], "page_type": p["page_type"]})
    duplicate_titles = {t: ps for t, ps in title_to_pages.items() if len(ps) > 1}
    results["duplicate_titles"] = duplicate_titles

    # 7. Slug quality analysis
    slug_issues = []
    java_keywords = {"abs", "long", "int", "void", "null", "byte", "char", "short", "float", "double", "boolean"}
    for slug in domain_slugs:
        issues = []
        if slug in java_keywords or slug.rstrip("-domain") in java_keywords:
            issues.append("java_keyword_leak")
        if slug.islower() and not any(c == "-" for c in slug) and len(slug) > 8:
            issues.append("possible_classname_leak")
        if issues:
            slug_issues.append({"slug": slug, "issues": issues})
    results["slug_issues"] = slug_issues

    # 8. Topic-domain mismatch detection
    topic_domain_mismatches = []
    for p in topics:
        path_parts = p["path"].strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "__domains__":
            domain_slug = path_parts[1]
            title = p["title"]
            if "closed-friend" in domain_slug and "家族" in title:
                topic_domain_mismatches.append({"path": p["path"], "domain": domain_slug, "title": title, "issue": "family_topic_in_friend_domain"})
            elif "family" in domain_slug and "挚友" in title:
                topic_domain_mismatches.append({"path": p["path"], "domain": domain_slug, "title": title, "issue": "friend_topic_in_family_domain"})
            elif "intimacy" in domain_slug and ("家族" in title or "挚友" in title):
                topic_domain_mismatches.append({"path": p["path"], "domain": domain_slug, "title": title, "issue": "cross_domain_topic_in_intimacy"})
    results["topic_domain_mismatches"] = topic_domain_mismatches

    # 9. English H2 summary
    eng_h2_overview_count = sum(1 for p in domain_overviews if p["has_english_h2"])
    eng_h2_topic_count = sum(1 for p in topics if p["has_english_h2"])
    results["stats"]["eng_h2_overview_count"] = eng_h2_overview_count
    results["stats"]["eng_h2_overview_pct"] = round(eng_h2_overview_count / len(domain_overviews) * 100, 1) if domain_overviews else 0
    results["stats"]["eng_h2_topic_count"] = eng_h2_topic_count
    results["stats"]["eng_h2_topic_pct"] = round(eng_h2_topic_count / len(topics) * 100, 1) if topics else 0

    # 10. Hallucination summary
    pages_with_hallucinations = [
        {"path": p["path"], "title": p["title"], "flags": p["hallucination_flags"]}
        for p in pages if p.get("hallucination_flags")
    ]
    results["pages_with_hallucinations"] = pages_with_hallucinations
    results["stats"]["pages_with_hallucination_flags"] = len(pages_with_hallucinations)

    await store.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Audit wiki data from FalkorDB")
    parser.add_argument("--business-id", default="ultron", help="Business ID to query")
    parser.add_argument("--graph", default=None, help="FalkorDB graph name (default: kb_{business_id})")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    parser.add_argument("--full-content", action="store_true", help="Include full page content in output")
    parser.add_argument("--repo", default=None, help="Filter by repository name (e.g. 'ultron' to exclude stale module_overview from other repos)")
    args = parser.parse_args()

    data = asyncio.run(query_wiki_data(args.business_id, graph_name=args.graph, full_content=args.full_content, repo_filter=args.repo))

    output = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Written to {args.output} ({len(output)} bytes)", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
