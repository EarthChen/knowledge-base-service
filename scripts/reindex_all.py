#!/usr/bin/env python3
"""Re-index all repositories in the knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:38888"


def _client_headers(business_id: str, api_token: str) -> dict[str, str]:
    h: dict[str, str] = {"X-Business-Id": business_id}
    if api_token:
        h["Authorization"] = f"Bearer {api_token}"
    return h


async def get_repositories(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Fetch distinct repository names from GET /api/v1/repositories."""
    r = await client.get(f"{base_url.rstrip('/')}/api/v1/repositories")
    r.raise_for_status()
    data = r.json()
    repos: list[str] = []
    for row in data.get("repositories") or []:
        name = row.get("repository")
        if name:
            repos.append(str(name))
    return repos


def _resolve_directory(
    repo: str,
    repo_dir: Path | None,
    paths_map: dict[str, str],
) -> str | None:
    if repo in paths_map:
        p = Path(paths_map[repo])
        return str(p.resolve()) if p.is_dir() else None
    if repo_dir is not None:
        p = repo_dir / repo
        if p.is_dir():
            return str(p.resolve())
    return None


async def reindex_repo(
    client: httpx.AsyncClient,
    base_url: str,
    directory: str,
    repository: str,
) -> dict[str, Any]:
    payload = {
        "directory": directory,
        "repository": repository,
        "mode": "full",
    }
    r = await client.post(
        f"{base_url.rstrip('/')}/api/v1/index",
        json=payload,
    )
    out: dict[str, Any] = {"repository": repository, "directory": directory}
    try:
        out["response"] = r.json()
    except Exception:
        out["response"] = {"raw": r.text}
    out["http_status"] = r.status_code
    if r.is_success:
        out["task_id"] = (out.get("response") or {}).get("task_id")
    else:
        err = out.get("response")
        if isinstance(err, dict):
            out["error"] = err.get("detail", r.text)
        else:
            out["error"] = r.text
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("KB_BASE_URL", DEFAULT_BASE_URL),
        help="Knowledge base HTTP base URL (env: KB_BASE_URL)",
    )
    default_rd = os.environ.get("KB_REPO_DIR", "").strip()
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=Path(default_rd) if default_rd else None,
        help="Directory with one subdirectory per repository name (env: KB_REPO_DIR)",
    )
    parser.add_argument(
        "--repo-paths",
        type=Path,
        default=None,
        help="JSON file mapping repository name -> absolute path",
    )
    parser.add_argument(
        "--repositories",
        nargs="*",
        default=None,
        help="Only these repository names (default: all from the service)",
    )
    parser.add_argument(
        "--via-api",
        action="store_true",
        help="Call POST /api/v1/reindex/all once (server resolves paths when possible)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    api_token = os.environ.get("KB_API_TOKEN", "").strip()
    business_id = os.environ.get("KB_BUSINESS_ID", "default")

    paths_map: dict[str, str] = {}
    if args.repo_paths:
        raw = json.loads(args.repo_paths.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            print("--repo-paths JSON must be an object", file=sys.stderr)
            sys.exit(2)
        paths_map = {str(k): str(v) for k, v in raw.items()}

    timeout = httpx.Timeout(600.0)
    headers = _client_headers(business_id, api_token)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        if args.via_api:
            body: dict[str, Any] = {"repositories": list(args.repositories or [])}
            if args.repo_dir:
                body["base_dir"] = str(args.repo_dir.resolve())
            print("POST /api/v1/reindex/all ...", flush=True)
            r = await client.post(f"{base_url}/api/v1/reindex/all", json=body)
            print(r.text)
            if not r.is_success:
                sys.exit(1)
            return

        names = (
            list(args.repositories)
            if args.repositories is not None
            else await get_repositories(client, base_url)
        )
        if not names:
            print("No repositories to re-index.", file=sys.stderr)
            sys.exit(1)

        if not paths_map and args.repo_dir is None:
            print(
                "Provide --repo-dir (or KB_REPO_DIR), --repo-paths, or use --via-api "
                "(optionally with --repo-dir for base_dir).",
                file=sys.stderr,
            )
            sys.exit(2)

        repo_base = args.repo_dir.resolve() if args.repo_dir else None

        ok = 0
        failed: list[dict[str, Any]] = []

        for i, repo in enumerate(names, 1):
            directory = _resolve_directory(repo, repo_base, paths_map)
            if not directory:
                print(f"[{i}/{len(names)}] SKIP {repo}: no local directory resolved", flush=True)
                failed.append({"repository": repo, "error": "no local directory"})
                continue

            print(f"[{i}/{len(names)}] START {repo} -> {directory}", flush=True)
            try:
                result = await reindex_repo(client, base_url, directory, repo)
            except Exception as exc:
                print(f"[{i}/{len(names)}] FAIL {repo}: {exc}", flush=True)
                failed.append({"repository": repo, "error": str(exc)})
                continue

            if result.get("http_status", 0) >= 400:
                print(
                    f"[{i}/{len(names)}] FAIL {repo}: HTTP {result.get('http_status')} "
                    f"{result.get('error', '')}",
                    flush=True,
                )
                failed.append(result)
                continue

            tid = result.get("task_id", "")
            print(f"[{i}/{len(names)}] QUEUED {repo} task_id={tid}", flush=True)
            ok += 1

        print("--- summary ---")
        print(f"total: {len(names)}, queued: {ok}, failed/skipped: {len(failed)}")
        if failed:
            for f in failed:
                print(f"  - {f}")
        if failed:
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
