#!/usr/bin/env python3
"""CLI for querying the Knowledge Base Service via REST API.

Usage:
    python kb_query.py search "login authentication" --repo my-service -k 5
    python kb_query.py file content --repo my-service --path src/main.py
    python kb_query.py file tree --repo my-service
    python kb_query.py code Class:my-service:AuthService
    python kb_query.py graph call-chain handleRequest --dir downstream --depth 3
    python kb_query.py graph find UserService --repo my-service
    python kb_query.py graph cypher "MATCH (f:Function)-[:CALLS]->(c) RETURN c.name LIMIT 10"
    python kb_query.py graph blast-radius processPayment --depth 3
    python kb_query.py wiki page --path __domains__/auth/_overview
    python kb_query.py wiki tree
    python kb_query.py wiki domain-tree
    python kb_query.py wiki search "authentication flow"
    python kb_query.py wiki entities WikiPage:biz:__domains__/auth/_overview
    python kb_query.py wiki refs WikiPage:biz:__domains__/auth/_overview
    python kb_query.py wiki domain-edges
    python kb_query.py stats --repo my-service
    python kb_query.py stats insights my-service
    python kb_query.py stats health
    python kb_query.py repos

Environment:
    KB_BASE_URL   (default: http://localhost:8100)
    KB_TOKEN      (default: "")
    KB_BUSINESS_ID (default: "default")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

KB_BASE_URL = os.environ.get("KB_BASE_URL", "http://localhost:8100").rstrip("/")
KB_TOKEN = os.environ.get("KB_TOKEN", "")
KB_BUSINESS_ID = os.environ.get("KB_BUSINESS_ID", "default")


def _request(method: str, path: str, body: dict | None = None, timeout: int = 60) -> dict:
    url = f"{KB_BASE_URL}{path}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if KB_TOKEN:
        headers["Authorization"] = f"Bearer {KB_TOKEN}"
    if KB_BUSINESS_ID:
        headers["X-Business-Id"] = KB_BUSINESS_ID

    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        print(f"HTTP {e.code}: {raw}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def _get(path: str, params: dict | None = None, **kw) -> dict:
    if params:
        params = {k: v for k, v in params.items() if v is not None}
        if params:
            path = f"{path}?{urlencode(params)}"
    return _request("GET", path, **kw)


def _post(path: str, body: dict, **kw) -> dict:
    return _request("POST", path, body=body, **kw)


def _output(data, compact: bool = False) -> None:
    indent = None if compact else 2
    print(json.dumps(data, ensure_ascii=False, indent=indent))


# ── Subcommand handlers ──────────────────────────────────────────────


def cmd_search(args) -> None:
    """Hybrid semantic + keyword search."""
    body: dict = {"query": args.query, "k": args.k}
    if args.repo:
        body["repository"] = args.repo
    _output(_post("/api/v1/hybrid", body), args.compact)


def cmd_file(args) -> None:
    """Read file content or tree."""
    if args.action == "content":
        params = {
            "repository": args.repo,
            "file_path": args.path,
            "start_line": args.start,
            "end_line": args.end,
        }
        _output(_get("/api/v1/files/content", params), args.compact)
    elif args.action == "tree":
        _output(_get("/api/v1/files/tree", {"repository": args.repo}), args.compact)
    elif args.action == "entities":
        _output(_get("/api/v1/files/entities", {"file_path": args.path}), args.compact)


def cmd_code(args) -> None:
    """Get code snippet by entity UID."""
    _output(_get(f"/api/v1/code/{args.uid}"), args.compact)


def cmd_graph(args) -> None:
    """Structured graph queries."""
    action = args.action

    if action == "call-chain":
        body = {
            "query_type": "call_chain",
            "name": args.name,
            "direction": args.dir,
            "depth": args.depth,
        }
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "find":
        body: dict = {"query_type": "find_entity", "name": args.name}
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "deps":
        body = {"query_type": "module_dependencies", "name": args.name}
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "reverse-deps":
        body = {"query_type": "reverse_dependencies", "name": args.name}
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "methods":
        body = {"query_type": "class_methods", "name": args.name}
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "inheritance":
        body = {"query_type": "inheritance_tree", "name": args.name}
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "cypher":
        body: dict = {"query_type": "raw_cypher", "cypher": args.cypher}
        if args.params:
            try:
                body["params"] = json.loads(args.params)
            except json.JSONDecodeError as e:
                print(f"Invalid --params JSON: {e}", file=sys.stderr)
                sys.exit(1)
        _output(_post("/api/v1/graph", body), args.compact)

    elif action == "blast-radius":
        names = [e.strip() for e in args.entities.split(",")]
        body: dict = {"entity_names": names, "max_depth": args.depth}
        if args.repo:
            body["repository"] = args.repo
        _output(_post("/api/v1/graph/blast-radius", body), args.compact)

    elif action == "explore":
        body = {"node_uid": args.uid, "depth": args.depth}
        _output(_post("/api/v1/graph/explore", body), args.compact)

    elif action == "raw":
        body: dict = {"query_type": args.query_type, "name": args.name}
        if args.repo:
            body["repository"] = args.repo
        if args.direction:
            body["direction"] = args.direction
        if args.depth:
            body["depth"] = args.depth
        _output(_post("/api/v1/graph", body), args.compact)


def cmd_wiki(args) -> None:
    """Wiki page queries."""
    action = args.action
    bid = KB_BUSINESS_ID

    if action == "page":
        params: dict = {"business_id": bid, "path": args.path}
        if args.repo:
            params["repository"] = args.repo
        _output(_get("/api/v1/wiki/pages/by-path", params), args.compact)

    elif action == "tree":
        params = {"business_id": bid, "view": args.view}
        _output(_get("/api/v1/wiki/tree", params), args.compact)

    elif action == "domain-tree":
        _output(_get("/api/v1/wiki/domain-tree", {"business_id": bid}), args.compact)

    elif action == "topic-tree":
        _output(_get("/api/v1/wiki/topic-tree", {"business_id": bid}), args.compact)

    elif action == "search":
        body: dict = {"query": args.query, "repository": bid, "limit": args.limit}
        _output(_post("/api/v1/wiki/search", body), args.compact)

    elif action == "global-search":
        body = {"query": args.query, "limit": args.limit}
        _output(_post("/api/v1/wiki/search/global", body), args.compact)

    elif action == "entities":
        path = args.path.lstrip("/")
        _output(_get(f"/api/v1/wiki/pages/{path}/entities", {"business_id": bid}), args.compact)

    elif action == "refs":
        _output(_get(f"/api/v1/wiki/pages/{args.uid}/references"), args.compact)

    elif action == "domain-edges":
        _output(_get("/api/v1/wiki/domain-edges", {"business_id": bid}), args.compact)

    elif action == "flows":
        _output(_get("/api/v1/wiki/flows", {"business_id": bid}), args.compact)

    elif action == "coverage":
        _output(_get("/api/v1/wiki/coverage-report", {"business_id": bid}), args.compact)

    elif action == "quality":
        _output(_get("/api/v1/wiki/quality-score", {"business_id": bid}), args.compact)


def cmd_stats(args) -> None:
    """Graph stats and insights."""
    action = args.action or "overview"

    if action == "overview":
        _output(_get("/api/v1/stats", {"repository": args.repo}), args.compact)

    elif action == "insights":
        path = f"/api/v1/graph/insights/{quote(args.repo, safe='')}"
        params = {"business_id": KB_BUSINESS_ID} if args.business else {}
        _output(_get(path, params), args.compact)

    elif action == "health":
        _output(_get("/api/v1/stats/health"), args.compact)

    elif action == "arch":
        params: dict = {"repository": args.repo}
        if args.layer:
            params["layer"] = args.layer
        _output(_get("/api/v1/search/architecture", params), args.compact)

    elif action == "communities":
        params = {"repository": args.repo, "min_size": args.min_size}
        _output(_get("/api/v1/graph/communities", params), args.compact)


def cmd_repos(args) -> None:
    """List indexed repositories."""
    _output(_get("/api/v1/repositories", {"offset": args.offset, "limit": args.limit}), args.compact)


# ── Argument parser ──────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kb_query",
        description="Query the Knowledge Base Service via REST API",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # shared flags inherited by every subcommand
    _common = argparse.ArgumentParser(add_help=False)
    _common.add_argument("--compact", action="store_true", help="Compact JSON output")

    # search
    sp = sub.add_parser("search", parents=[_common], help="Hybrid semantic + keyword search")
    sp.add_argument("query", help="Search query text")
    sp.add_argument("--repo", "-r", default=None, help="Repository filter")
    sp.add_argument("-k", type=int, default=5, help="Number of results (default: 5)")
    sp.set_defaults(func=cmd_search)

    # file
    sp = sub.add_parser("file", parents=[_common], help="Read file content or tree")
    file_sub = sp.add_subparsers(dest="action", required=True)

    fc = file_sub.add_parser("content", parents=[_common], help="Read file content")
    fc.add_argument("--repo", "-r", required=True, help="Repository")
    fc.add_argument("--path", "-p", required=True, help="File path")
    fc.add_argument("--start", type=int, default=None, help="Start line")
    fc.add_argument("--end", type=int, default=None, help="End line")
    fc.set_defaults(func=cmd_file)

    ft = file_sub.add_parser("tree", parents=[_common], help="File tree")
    ft.add_argument("--repo", "-r", required=True, help="Repository")
    ft.set_defaults(func=cmd_file)

    fe = file_sub.add_parser("entities", parents=[_common], help="Entities in a file")
    fe.add_argument("--path", "-p", required=True, help="File path")
    fe.set_defaults(func=cmd_file)

    # code
    sp = sub.add_parser("code", parents=[_common], help="Get code snippet by entity UID")
    sp.add_argument("uid", help="Entity UID (e.g. Class:my-repo:AuthService)")
    sp.set_defaults(func=cmd_code)

    # graph
    sp = sub.add_parser("graph", parents=[_common], help="Graph queries")
    graph_sub = sp.add_subparsers(dest="action", required=True)

    gc = graph_sub.add_parser("call-chain", parents=[_common], help="Trace call chain")
    gc.add_argument("name", help="Function/method name")
    gc.add_argument("--dir", "-d", default="downstream", choices=["downstream", "upstream"])
    gc.add_argument("--depth", type=int, default=3)
    gc.add_argument("--repo", "-r", default=None)
    gc.set_defaults(func=cmd_graph)

    gf = graph_sub.add_parser("find", parents=[_common], help="Find entity by name")
    gf.add_argument("name", help="Entity name")
    gf.add_argument("--repo", "-r", default=None)
    gf.set_defaults(func=cmd_graph)

    gd = graph_sub.add_parser("deps", parents=[_common], help="Module dependencies")
    gd.add_argument("name", help="Module name")
    gd.add_argument("--repo", "-r", default=None)
    gd.set_defaults(func=cmd_graph)

    grd = graph_sub.add_parser("reverse-deps", parents=[_common], help="Reverse dependencies")
    grd.add_argument("name", help="Module name")
    grd.add_argument("--repo", "-r", default=None)
    grd.set_defaults(func=cmd_graph)

    gm = graph_sub.add_parser("methods", parents=[_common], help="List class methods")
    gm.add_argument("name", help="Class name")
    gm.add_argument("--repo", "-r", default=None)
    gm.set_defaults(func=cmd_graph)

    gi = graph_sub.add_parser("inheritance", parents=[_common], help="Class inheritance tree")
    gi.add_argument("name", help="Class name")
    gi.add_argument("--repo", "-r", default=None)
    gi.set_defaults(func=cmd_graph)

    gcy = graph_sub.add_parser("cypher", parents=[_common], help="Raw Cypher query")
    gcy.add_argument("cypher", help="Cypher query string")
    gcy.add_argument("--params", default=None, help="JSON params dict")
    gcy.set_defaults(func=cmd_graph)

    gb = graph_sub.add_parser("blast-radius", parents=[_common], help="Impact analysis")
    gb.add_argument("entities", help="Comma-separated entity names")
    gb.add_argument("--depth", type=int, default=3)
    gb.add_argument("--repo", "-r", default=None)
    gb.set_defaults(func=cmd_graph)

    ge = graph_sub.add_parser("explore", parents=[_common], help="Neighborhood for visualization")
    ge.add_argument("uid", help="Node UID")
    ge.add_argument("--depth", type=int, default=1)
    ge.set_defaults(func=cmd_graph)

    gr = graph_sub.add_parser("raw", parents=[_common], help="Raw graph query_type")
    gr.add_argument("query_type", help="query_type value")
    gr.add_argument("name", help="name param")
    gr.add_argument("--repo", "-r", default=None)
    gr.add_argument("--direction", default=None)
    gr.add_argument("--depth", type=int, default=None)
    gr.set_defaults(func=cmd_graph)

    # wiki
    sp = sub.add_parser("wiki", parents=[_common], help="Wiki page queries")
    wiki_sub = sp.add_subparsers(dest="action", required=True)

    wp = wiki_sub.add_parser("page", parents=[_common], help="Get wiki page by path")
    wp.add_argument("--path", "-p", required=True, help="Wiki path (e.g. __domains__/auth/_overview)")
    wp.add_argument("--repo", "-r", default=None)
    wp.set_defaults(func=cmd_wiki)

    wt = wiki_sub.add_parser("tree", parents=[_common], help="Full wiki tree")
    wt.add_argument("--view", default="business_domain", help="View type")
    wt.set_defaults(func=cmd_wiki)

    wdt = wiki_sub.add_parser("domain-tree", parents=[_common], help="Domain hierarchy")
    wdt.set_defaults(func=cmd_wiki)

    wtt = wiki_sub.add_parser("topic-tree", parents=[_common], help="Topic navigation tree")
    wtt.set_defaults(func=cmd_wiki)

    ws = wiki_sub.add_parser("search", parents=[_common], help="Wiki search")
    ws.add_argument("query", help="Search query")
    ws.add_argument("--limit", "-l", type=int, default=10)
    ws.set_defaults(func=cmd_wiki)

    wgs = wiki_sub.add_parser("global-search", parents=[_common], help="Cross-repo wiki search")
    wgs.add_argument("query", help="Search query")
    wgs.add_argument("--limit", "-l", type=int, default=10)
    wgs.set_defaults(func=cmd_wiki)

    we = wiki_sub.add_parser("entities", parents=[_common], help="Source entities for wiki page")
    we.add_argument("--path", "-p", required=True, help="Wiki page path (e.g. __domains__/auth/_overview)")
    we.set_defaults(func=cmd_wiki)

    wr = wiki_sub.add_parser("refs", parents=[_common], help="Page references (incoming/outgoing)")
    wr.add_argument("uid", help="Wiki page UID")
    wr.set_defaults(func=cmd_wiki)

    wde = wiki_sub.add_parser("domain-edges", parents=[_common], help="Cross-domain CALLS edges")
    wde.set_defaults(func=cmd_wiki)

    wfl = wiki_sub.add_parser("flows", parents=[_common], help="Business flow nodes")
    wfl.set_defaults(func=cmd_wiki)

    wcv = wiki_sub.add_parser("coverage", parents=[_common], help="Wiki coverage report")
    wcv.set_defaults(func=cmd_wiki)

    wq = wiki_sub.add_parser("quality", parents=[_common], help="Wiki quality score")
    wq.set_defaults(func=cmd_wiki)

    # stats
    sp = sub.add_parser("stats", parents=[_common], help="Graph stats and architecture insights")
    stats_sub = sp.add_subparsers(dest="action")

    so = stats_sub.add_parser("overview", parents=[_common], help="Graph stats overview")
    so.add_argument("--repo", "-r", default=None)
    so.set_defaults(func=cmd_stats)

    si = stats_sub.add_parser("insights", parents=[_common], help="Architecture insights")
    si.add_argument("repo", help="Repository name")
    si.add_argument("--business", "-b", action="store_true", help="Pass business_id")
    si.set_defaults(func=cmd_stats)

    sh = stats_sub.add_parser("health", parents=[_common], help="Knowledge graph health")
    sh.set_defaults(func=cmd_stats)

    sa = stats_sub.add_parser("arch", parents=[_common], help="Architecture search (API endpoints, etc.)")
    sa.add_argument("--repo", "-r", required=True)
    sa.add_argument("--layer", default=None, help="Layer filter (api, service, etc.)")
    sa.set_defaults(func=cmd_stats)

    sc = stats_sub.add_parser("communities", parents=[_common], help="Community detection")
    sc.add_argument("--repo", "-r", required=True)
    sc.add_argument("--min-size", type=int, default=3)
    sc.set_defaults(func=cmd_stats)

    sp.set_defaults(func=cmd_stats, action="overview", repo=None, compact=False)

    # repos
    sp = sub.add_parser("repos", parents=[_common], help="List indexed repositories")
    sp.add_argument("--offset", type=int, default=0)
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_repos)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
