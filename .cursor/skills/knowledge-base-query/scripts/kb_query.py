#!/usr/bin/env python3
"""CLI for querying the Knowledge Base Service MCP tools.

Usage:
    python scripts/kb_query.py <tool_name> [--arg key=value ...]

Examples:
    python scripts/kb_query.py rag_query --arg query="login handler" --arg k=5
    python scripts/kb_query.py rag_graph --arg query_type=call_chain --arg name=handleRequest
    python scripts/kb_query.py get_file_content --arg repository=my-repo --arg file_path=src/main.py
    python scripts/kb_query.py rag_graph --arg query_type=nl_query --arg name="列出所有调用 UserService 的函数"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KB_BASE_URL = os.environ.get("KB_BASE_URL", "http://localhost:8100")
KB_TOKEN = os.environ.get("KB_TOKEN", "")
KB_BUSINESS_ID = os.environ.get("KB_BUSINESS_ID", "default")

AVAILABLE_TOOLS = [
    "rag_query",
    "rag_graph",
    "documents",
    "get_code_snippet",
    "get_file_content",
    "graph_path",
    "analyze_code",
    "search_architecture",
    "analyze_changes",
    "get_complete_context",
    "get_insights",
    "index_freshness",
    "get_wiki_page",
    "list_wiki_pages",
    "wiki_search",
    "unified_knowledge_query",
    "wiki_export",
    "wiki_get_tree",
    "wiki_get_related",
    "wiki_get_domain_overview",
    "wiki_get_snapshot",
    "wiki_find_implementing_modules",
]


def _parse_value(raw: str) -> str | int | float | bool | list:
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def call_tool(tool_name: str, arguments: dict) -> dict:
    url = f"{KB_BASE_URL}/api/v1/mcp/tool"
    payload = json.dumps({"tool_name": tool_name, "arguments": arguments}).encode()

    headers = {"Content-Type": "application/json"}
    if KB_TOKEN:
        headers["Authorization"] = f"Bearer {KB_TOKEN}"
    if KB_BUSINESS_ID:
        headers["X-Business-Id"] = KB_BUSINESS_ID

    req = Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": {"code": str(e.code), "message": body}}
    except URLError as e:
        return {"error": {"code": "connection_error", "message": str(e.reason)}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the Knowledge Base Service")
    parser.add_argument("tool", choices=AVAILABLE_TOOLS, help="MCP tool name")
    parser.add_argument("--arg", action="append", default=[], metavar="key=value",
                        help="Tool argument (repeatable)")
    parser.add_argument("--json-args", type=str, default=None,
                        help="Full arguments as JSON string")
    parser.add_argument("--compact", action="store_true",
                        help="Compact JSON output (no indentation)")
    args = parser.parse_args()

    if args.json_args:
        try:
            arguments = json.loads(args.json_args)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        arguments = {}
        for pair in args.arg:
            if "=" not in pair:
                print(f"Invalid arg format '{pair}', expected key=value", file=sys.stderr)
                sys.exit(1)
            key, val = pair.split("=", 1)
            arguments[key.strip()] = _parse_value(val.strip())

    result = call_tool(args.tool, arguments)
    indent = None if args.compact else 2
    print(json.dumps(result, ensure_ascii=False, indent=indent))

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
