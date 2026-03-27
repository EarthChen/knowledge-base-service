#!/usr/bin/env python3
"""Knowledge Base Query Tool

Usage:
  kb_query.py search "用户认证流程"                          # Semantic search
  kb_query.py search "AuthService" --type class              # Search by entity type
  kb_query.py graph stats                                    # Graph statistics
  kb_query.py graph call_chain --name handleRequest          # Call chain (downstream)
  kb_query.py graph call_chain --name save --direction upstream  # Call chain (upstream)
  kb_query.py graph class_methods --name AuthService         # Class methods
  kb_query.py graph inheritance_tree --name BaseService      # Inheritance tree
  kb_query.py graph file_entities --file src/main.py         # File entities
  kb_query.py graph find_entity --name AuthService           # Find entity
  kb_query.py hybrid "API 错误处理"                           # Hybrid search
  kb_query.py index /path/to/repo                            # Incremental index
  kb_query.py index /path/to/repo --mode full                # Full index
  kb_query.py repos                                          # List indexed repos

Environment variables:
  KB_URL    Knowledge base API URL (default: http://localhost:8100/api/v1)
  KB_TOKEN  API authentication token (required)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _api(method: str, path: str, body: dict | None = None) -> dict:
    kb_url = os.environ.get("KB_URL", "http://localhost:8100/api/v1")
    kb_token = os.environ.get("KB_TOKEN", "")
    if not kb_token:
        print("Error: KB_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)

    url = f"{kb_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {kb_token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        print(f"Error: HTTP {e.code} - {err_body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: Connection failed - {e.reason}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print("Error: Request timed out", file=sys.stderr)
        sys.exit(1)


def _print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ── Commands ──────────────────────────────────────────────────────────


def cmd_search(args: argparse.Namespace) -> None:
    body = {"query": args.query, "k": args.k, "entity_type": args.type}
    result = _api("POST", "search", body)

    if args.brief:
        results = result.get("results", [])
        print(f"Found {len(results)} results for '{args.query}':")
        for r in results:
            score = r.get("score", 0)
            name = r.get("name", "?")
            fpath = r.get("file", "?")
            line = r.get("start_line", "?")
            print(f"  [{score:.2f}] {name}  ({fpath}:{line})")
    else:
        _print_json(result)


def cmd_graph(args: argparse.Namespace) -> None:
    qt = args.graph_type

    if qt == "stats":
        result = _api("POST", "graph", {"query_type": "graph_stats"})
    elif qt == "call_chain":
        result = _api("POST", "graph", {
            "query_type": "call_chain",
            "name": args.name,
            "depth": args.depth,
            "direction": args.direction,
        })
    elif qt == "class_methods":
        result = _api("POST", "graph", {"query_type": "class_methods", "name": args.name})
    elif qt in ("inheritance_tree", "inheritance"):
        result = _api("POST", "graph", {"query_type": "inheritance", "name": args.name})
    elif qt == "file_entities":
        result = _api("POST", "graph", {"query_type": "file_entities", "file": args.file})
    elif qt == "find_entity":
        result = _api("POST", "graph", {
            "query_type": "find_entity",
            "name": args.name,
            "entity_type": args.entity_type,
        })
    elif qt == "module_deps":
        result = _api("POST", "graph", {"query_type": "module_deps", "name": args.name})
    else:
        print(f"Error: Unknown graph type '{qt}'", file=sys.stderr)
        sys.exit(1)

    if args.brief and qt == "find_entity":
        data = result.get("data", [])
        print(f"Found {len(data)} entities for '{args.name}':")
        for d in data:
            name = d.get("name", "?")
            fpath = d.get("file", d.get("path", "?"))
            line = d.get("start_line", "")
            sig = d.get("signature", "")
            loc = f"{fpath}:{line}" if line else fpath
            print(f"  {name}  ({loc})")
            if sig:
                print(f"    signature: {sig}")
    elif args.brief and qt == "stats":
        data = result.get("data", result)
        if isinstance(data, list) and data:
            data = data[0]
        nodes = data.get("nodes", data)
        if isinstance(nodes, dict):
            total = sum(nodes.values())
            print(f"Total nodes: {total}")
            for k, v in nodes.items():
                print(f"  {k}: {v}")
        else:
            _print_json(result)
    else:
        _print_json(result)


def cmd_hybrid(args: argparse.Namespace) -> None:
    body = {"query": args.query, "k": args.k, "expand_depth": args.expand_depth}
    result = _api("POST", "hybrid", body)
    _print_json(result)


def cmd_index(args: argparse.Namespace) -> None:
    body = {"directory": args.directory, "mode": args.mode}
    result = _api("POST", "index", body)
    _print_json(result)


def cmd_repos(_args: argparse.Namespace) -> None:
    result = _api("GET", "repositories")

    if _args.brief:
        repos = result.get("repositories", [])
        print(f"Indexed repositories ({len(repos)}):")
        for r in repos:
            name = r.get("repository", "?")
            nodes = r.get("nodes", 0)
            print(f"  {name}: {nodes} nodes")
    else:
        _print_json(result)


# ── CLI ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Knowledge Base Query Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--brief", action="store_true", help="Print human-readable summary instead of raw JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Semantic search")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--type", default="all", choices=["all", "function", "class", "document"])
    p_search.add_argument("--k", type=int, default=5, help="Number of results")
    p_search.set_defaults(func=cmd_search)

    # graph
    p_graph = sub.add_parser("graph", help="Graph queries")
    p_graph.add_argument("graph_type", choices=[
        "stats", "call_chain", "class_methods", "inheritance_tree",
        "file_entities", "find_entity", "module_deps",
    ])
    p_graph.add_argument("--name", default="", help="Entity name")
    p_graph.add_argument("--file", default="", help="File path (for file_entities)")
    p_graph.add_argument("--depth", type=int, default=3, help="Traversal depth")
    p_graph.add_argument("--direction", default="downstream", choices=["upstream", "downstream"])
    p_graph.add_argument("--entity-type", default="any", choices=["function", "class", "any"])
    p_graph.set_defaults(func=cmd_graph)

    # hybrid
    p_hybrid = sub.add_parser("hybrid", help="Hybrid search (semantic + graph)")
    p_hybrid.add_argument("query", help="Search query")
    p_hybrid.add_argument("--k", type=int, default=5)
    p_hybrid.add_argument("--expand-depth", type=int, default=2)
    p_hybrid.set_defaults(func=cmd_hybrid)

    # index
    p_index = sub.add_parser("index", help="Trigger indexing")
    p_index.add_argument("directory", help="Directory to index")
    p_index.add_argument("--mode", default="incremental", choices=["full", "incremental"])
    p_index.set_defaults(func=cmd_index)

    # repos
    p_repos = sub.add_parser("repos", help="List indexed repositories")
    p_repos.set_defaults(func=cmd_repos)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
