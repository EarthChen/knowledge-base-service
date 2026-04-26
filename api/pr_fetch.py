"""Fetch changed files from GitHub pull requests or GitLab merge requests by URL."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from services.git_manager import normalize_repo_name

_ALLOWED = frozenset({"added", "modified", "removed", "renamed"})


def parse_gitlab_merge_request_url(url: str) -> tuple[str, str, int] | None:
    """Parse a GitLab MR URL into ``(origin, project_path_with_namespace, iid)``."""
    raw = url.strip()
    if not raw:
        return None
    raw = raw.split("#", 1)[0].strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    marker = "/-/merge_requests/"
    idx = path.find(marker)
    if idx == -1:
        return None
    proj = path[1:idx].strip("/")
    if not proj:
        return None
    tail = path[idx + len(marker) :].strip("/")
    if not tail:
        return None
    iid_part = tail.split("/")[0]
    if not iid_part.isdigit():
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, proj, int(iid_part)


def parse_github_pull_request_url(url: str) -> tuple[str, str, str, int] | None:
    """Parse a GitHub-style PR URL into ``(origin, owner, repo, number)``."""
    raw = url.strip()
    if not raw:
        return None
    raw = raw.split("#", 1)[0].strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    try:
        pull_idx = parts.index("pull")
    except ValueError:
        return None
    if pull_idx < 2 or pull_idx + 1 >= len(parts):
        return None
    owner, repo_name = parts[pull_idx - 2], parts[pull_idx - 1]
    num_part = parts[pull_idx + 1]
    if not num_part.isdigit():
        return None
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, owner, repo_name, int(num_part)


def _github_api_base(origin: str) -> str:
    parsed = urlparse(origin)
    host = (parsed.hostname or "").lower()
    if host in ("github.com", "www.github.com"):
        return "https://api.github.com"
    return f"{parsed.scheme}://{parsed.netloc}/api/v3"


def _github_file_status(status: str) -> str:
    s = (status or "").lower()
    if s in _ALLOWED:
        return s
    if s in ("copied", "changed"):
        return "modified"
    return "modified"


def _normalize_path_key(path: str) -> str:
    return path.replace("\\", "/").strip().strip("/").lower()


def resolve_indexed_repository(
    canonical_path: str,
    indexed_rows: list[dict[str, Any]],
) -> tuple[str, str | None]:
    """Map a host-derived ``owner/repo`` or ``group/sub/project`` name to an indexed repository."""
    want = canonical_path.strip().strip("/")
    if not want:
        return "", "Could not derive a repository path from the URL."

    want_key = _normalize_path_key(want)
    names: list[str] = []
    for row in indexed_rows:
        n = row.get("repository")
        if isinstance(n, str) and n.strip():
            names.append(n.strip())

    for n in names:
        if _normalize_path_key(n) == want_key:
            return n, None

    for row in indexed_rows:
        n = row.get("repository")
        if not isinstance(n, str) or not n.strip():
            continue
        gu = row.get("git_url")
        if not isinstance(gu, str) or not gu.strip():
            continue
        norm = normalize_repo_name(gu).strip().strip("/")
        if _normalize_path_key(norm) == want_key:
            return n.strip(), None

    return want, (
        f"No indexed repository matched '{want}'. "
        "Select the correct repository in the dropdown before analyzing."
    )


async def _gitlab_fetch_changes(
    origin: str,
    project_path: str,
    iid: int,
    token: str,
) -> list[dict[str, str]]:
    enc = quote(project_path, safe="")
    api_url = f"{origin.rstrip('/')}/api/v4/projects/{enc}/merge_requests/{iid}/changes"
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["PRIVATE-TOKEN"] = token

    timeout = httpx.Timeout(60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(api_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    changes = data.get("changes")
    if not isinstance(changes, list):
        return []

    out: list[dict[str, str]] = []
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        old_path = ch.get("old_path") or ""
        new_path = ch.get("new_path") or ""
        if not isinstance(old_path, str):
            old_path = str(old_path)
        if not isinstance(new_path, str):
            new_path = str(new_path)

        deleted = bool(ch.get("deleted_file"))
        new_file = bool(ch.get("new_file"))
        renamed = bool(ch.get("renamed_file"))

        if deleted:
            path = old_path or new_path
            status = "removed"
        elif renamed:
            path = new_path or old_path
            status = "renamed"
        elif new_file:
            path = new_path or old_path
            status = "added"
        else:
            path = new_path or old_path
            status = "modified"

        path = path.strip()
        if not path:
            continue
        out.append({"path": path, "status": status})

    return out


async def _github_fetch_files(
    api_base: str,
    owner: str,
    repo: str,
    number: int,
    token: str,
) -> list[dict[str, str]]:
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(60.0)
    out: list[dict[str, str]] = []
    next_url: str | None = (
        f"{api_base.rstrip('/')}/repos/{owner}/{repo}/pulls/{number}/files?per_page=100"
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        while next_url:
            resp = await client.get(next_url, headers=headers)
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list):
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                fname = item.get("filename")
                if not isinstance(fname, str) or not fname.strip():
                    continue
                status = _github_file_status(str(item.get("status") or "modified"))
                out.append({"path": fname.strip(), "status": status})

            link = resp.headers.get("Link", "")
            next_url = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    m = re.search(r"<([^>]+)>", part.strip())
                    if m:
                        next_url = m.group(1)
                        break

    return out


async def fetch_pr_from_url(
    url: str,
    *,
    gitlab_token: str,
    github_token: str,
) -> dict[str, Any]:
    """Return ``provider``, ``canonical_path``, and ``changed_files`` for a PR/MR URL."""
    gl = parse_gitlab_merge_request_url(url)
    if gl is not None:
        origin, project_path, iid = gl
        files = await _gitlab_fetch_changes(origin, project_path, iid, gitlab_token)
        return {
            "provider": "gitlab",
            "canonical_path": project_path,
            "changed_files": files,
        }

    gh = parse_github_pull_request_url(url)
    if gh is not None:
        origin, owner, repo_name, num = gh
        api_base = _github_api_base(origin)
        files = await _github_fetch_files(api_base, owner, repo_name, num, github_token)
        return {
            "provider": "github",
            "canonical_path": f"{owner}/{repo_name}",
            "changed_files": files,
        }

    msg = (
        "Unsupported URL. Paste a GitHub pull request link "
        "(…/pull/123) or a GitLab merge request link (…/-/merge_requests/123)."
    )
    raise ValueError(msg)
