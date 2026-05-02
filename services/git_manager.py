"""Git repository manager for remote clone/pull operations.

Handles cloning from private GitLab instances via HTTPS (token-injected)
or SSH (key-based), and provides incremental pull for already-cloned repos.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from core.config import GitConfig
from core.log import get_logger

log = get_logger(__name__)


def normalize_repo_name(git_url: str) -> str:
    """从任意 Git URL 或本地路径解析出用作仓库标识的路径（如 group/project）。

    支持 HTTPS、``git@host:path`` 形式的 SSH，以及 ``ssh://`` URL；本地路径原样返回。
    """
    s = git_url.strip()
    # SCP 风格 SSH：git@host:group/project(.git)
    m = re.match(r"^git@[^:]+:(.+)$", s)
    if m:
        path = m.group(1)
        return path[:-4] if path.endswith(".git") else path
    if s.startswith(("http://", "https://", "ssh://")):
        parsed = urlparse(s)
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return path or s
    return s


def resolve_repo_clone_root(
    repository: str,
    git_cfg: GitConfig,
    repo_registry: Any | None = None,
) -> Path | None:
    """Resolve a graph ``repository`` name to its on-disk clone root under ``clone_base_path``.

    First tries ``{clone_base}/{repository}`` (local indexes and URL-aligned names). If that
    directory is missing and ``repo_registry`` maps this name to a ``git_url``, uses the
    same path as :meth:`GitManager._repo_local_path` so canonical names match clone layout.
    Falls back to scanning subdirectories for a matching basename (handles
    ``group/project`` clone layouts where the graph stores only ``project``).
    """
    repo = repository.strip()
    if not repo or ".." in Path(repo).parts or repo.startswith("/"):
        return None

    base = Path(git_cfg.clone_base_path).resolve()
    direct = (base / repo).resolve()
    if direct.is_relative_to(base) and direct.is_dir():
        return direct

    if repo_registry is not None:
        git_url = repo_registry.get_git_url_for_repository(repo)
        if git_url:
            mgr = GitManager(git_cfg)
            cloned = mgr._repo_local_path(git_url).resolve()
            if cloned.is_dir():
                if cloned.is_relative_to(base):
                    return cloned
                if cloned.is_absolute():
                    return cloned

    repo_basename = repo.rsplit("/", 1)[-1]
    if base.is_dir():
        for group_dir in sorted(base.iterdir()):
            if not group_dir.is_dir():
                continue
            candidate = group_dir / repo_basename
            if candidate.is_dir() and (candidate / ".git").is_dir():
                resolved = candidate.resolve()
                if resolved.is_relative_to(base):
                    return resolved

    return None


class GitManager:
    """Manages git clone/pull operations against private GitLab instances."""

    def __init__(self, config: GitConfig) -> None:
        self._cfg = config
        self._base_path = Path(config.clone_base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _inject_token_into_url(self, git_url: str) -> str:
        """Inject GitLab token into HTTPS clone URL.

        Transforms:
          https://git.example.com/group/project.git
        Into:
          https://oauth2:<token>@git.example.com/group/project.git
        """
        parsed = urlparse(git_url)
        if parsed.scheme not in ("https", "http"):
            return git_url
        if not self._cfg.gitlab_token:
            return git_url

        authed = parsed._replace(
            netloc=f"oauth2:{self._cfg.gitlab_token}@{parsed.hostname}"
            + (f":{parsed.port}" if parsed.port else "")
        )
        return urlunparse(authed)

    def _build_env(self) -> dict[str, str]:
        """Build environment dict for git subprocess."""
        env = dict(os.environ)
        if not self._cfg.ssl_verify:
            env["GIT_SSL_NO_VERIFY"] = "1"
        if self._cfg.ssh_key_path:
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self._cfg.ssh_key_path} "
                "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
            )
        return env

    def _repo_local_path(self, git_url: str, branch: str | None = None) -> Path:
        """Derive local clone path from git URL.

        e.g. https://git.example.com/group/project.git → data/repos/group/project
        """
        path_part = normalize_repo_name(git_url)
        base = Path(path_part)
        local = base if base.is_absolute() else self._base_path / path_part
        if branch:
            local = local / branch
        return local

    async def _run_git(
        self,
        args: list[str],
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> tuple[int, str, str]:
        """Run a git command asynchronously."""
        effective_timeout = timeout or self._cfg.clone_timeout
        env = self._build_env()

        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return -1, "", f"git {args[0]} timed out after {effective_timeout}s"

        return (
            proc.returncode or 0,
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )

    async def ensure_repo(
        self,
        git_url: str,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Clone or pull a repository, returning local path and status.

        Returns dict with keys: directory, repository, status, detail.
        """
        local_path = self._repo_local_path(git_url, branch=None)
        is_ssh = git_url.startswith("git@") or git_url.startswith("ssh://")
        clone_url = git_url if is_ssh else self._inject_token_into_url(git_url)

        repo_name = normalize_repo_name(git_url)

        if local_path.is_dir() and (local_path / ".git").is_dir():
            return await self._pull_repo(local_path, repo_name, branch)

        return await self._clone_repo(clone_url, local_path, repo_name, branch)

    async def _clone_repo(
        self,
        clone_url: str,
        local_path: Path,
        repo_name: str,
        branch: str | None,
    ) -> dict[str, Any]:
        """Clone a fresh repository."""
        if local_path.exists():
            shutil.rmtree(local_path, ignore_errors=True)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        args = ["clone"]
        if branch:
            args.extend(["-b", branch])
        args.extend([clone_url, str(local_path)])

        log.info("git_clone_start", repo=repo_name, branch=branch)
        rc, stdout, stderr = await self._run_git(args, timeout=self._cfg.clone_timeout)

        if rc != 0:
            log.error("git_clone_failed", repo=repo_name, stderr=stderr[:300])
            return {
                "directory": "",
                "repository": repo_name,
                "status": "clone_failed",
                "detail": stderr[:500],
            }

        log.info("git_clone_complete", repo=repo_name, path=str(local_path))
        return {
            "directory": str(local_path),
            "repository": repo_name,
            "status": "cloned",
            "detail": stdout[:200],
        }

    async def _pull_repo(
        self,
        local_path: Path,
        repo_name: str,
        branch: str | None,
    ) -> dict[str, Any]:
        """Pull latest changes for an already-cloned repo."""
        pre_head_rc, pre_head, _ = await self._run_git(
            ["rev-parse", "HEAD"], cwd=str(local_path), timeout=10
        )
        pre_head_sha = pre_head if pre_head_rc == 0 else ""

        if branch:
            await self._run_git(
                ["checkout", branch], cwd=str(local_path), timeout=30
            )

        log.info("git_pull_start", repo=repo_name, path=str(local_path))
        rc, stdout, stderr = await self._run_git(
            ["pull", "--ff-only"],
            cwd=str(local_path),
            timeout=self._cfg.pull_timeout,
        )

        if rc != 0:
            log.warning("git_pull_failed", repo=repo_name, stderr=stderr[:300])
            return {
                "directory": str(local_path),
                "repository": repo_name,
                "status": "pull_failed",
                "detail": stderr[:500],
                "pre_head": pre_head_sha,
            }

        already_up_to_date = "Already up to date" in stdout
        status = "up_to_date" if already_up_to_date else "pulled"

        log.info("git_pull_complete", repo=repo_name, status=status)
        return {
            "directory": str(local_path),
            "repository": repo_name,
            "status": status,
            "detail": stdout[:200],
            "pre_head": pre_head_sha,
        }
