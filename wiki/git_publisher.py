"""Git incremental publisher for wiki content."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from log import get_logger

log = get_logger(__name__)


@dataclass
class PublishResult:
    """Result of a git publish operation."""
    success: bool
    files_added: int
    files_modified: int
    files_deleted: int
    commit_sha: str | None = None
    error: str | None = None
    annotations_found: int = 0


class GitPublisher:
    """Publishes wiki export to a Git repository with incremental commits."""

    def __init__(
        self,
        remote_url: str,
        branch: str = "main",
        author_name: str = "KBS Wiki Bot",
        author_email: str = "wiki-bot@company.com",
        commit_message_prefix: str = "docs(wiki):",
        git_token: str = "",
        ssh_key_path: str = "",
    ) -> None:
        self._remote_url = remote_url
        self._branch = branch
        self._author_name = author_name
        self._author_email = author_email
        self._prefix = commit_message_prefix
        self._git_token = git_token
        self._ssh_key_path = ssh_key_path

    def detect_changes(
        self,
        existing_hashes: dict[str, str],
        new_files: dict[str, str],
    ) -> dict[str, list[str]]:
        """Compare content hashes to identify added/modified/deleted files."""
        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

        for path, content in new_files.items():
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if path not in existing_hashes:
                added.append(path)
            elif existing_hashes[path] != content_hash:
                modified.append(path)

        for path in existing_hashes:
            if path not in new_files:
                deleted.append(path)

        return {"added": added, "modified": modified, "deleted": deleted}

    def generate_commit_message(
        self,
        added: list[str],
        modified: list[str],
        deleted: list[str] | None = None,
        trigger_info: str = "",
        is_full: bool = False,
    ) -> str:
        """Generate a descriptive commit message."""
        if is_full:
            return f"{self._prefix} full regeneration for business wiki"

        parts: list[str] = []
        if added:
            names = ", ".join(Path(p).stem for p in added[:5])
            suffix = f" (+{len(added) - 5} more)" if len(added) > 5 else ""
            parts.append(f"add {names}{suffix}")
        if modified:
            names = ", ".join(Path(p).stem for p in modified[:5])
            suffix = f" (+{len(modified) - 5} more)" if len(modified) > 5 else ""
            parts.append(f"update {names}{suffix}")
        if deleted:
            parts.append(f"remove {len(deleted)} pages")

        summary = "; ".join(parts) if parts else "no changes"
        msg = f"{self._prefix} {summary}"
        if trigger_info:
            msg += f" (triggered by {trigger_info})"
        return msg

    def scan_annotations(self, repo_dir: str) -> dict[str, str]:
        """Scan a directory tree for .annotations.md files."""
        annotations: dict[str, str] = {}
        root = Path(repo_dir)
        for ann_file in root.rglob("*.annotations.md"):
            rel = ann_file.relative_to(root)
            wiki_path = str(rel).replace(".annotations.md", "").replace(os.sep, "/")
            try:
                content = ann_file.read_text(encoding="utf-8")
                annotations[wiki_path] = content
            except OSError:
                log.warning("Failed to read annotation file: %s", ann_file, exc_info=True)
        return annotations

    def _auth_url(self) -> str:
        if self._git_token and self._remote_url.startswith("https://"):
            parts = self._remote_url.split("://", 1)
            return f"{parts[0]}://oauth2:{self._git_token}@{parts[1]}"
        return self._remote_url

    def _build_git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self._ssh_key_path:
            env["GIT_SSH_COMMAND"] = f"ssh -i {self._ssh_key_path} -o StrictHostKeyChecking=no"
        env["GIT_AUTHOR_NAME"] = self._author_name
        env["GIT_AUTHOR_EMAIL"] = self._author_email
        env["GIT_COMMITTER_NAME"] = self._author_name
        env["GIT_COMMITTER_EMAIL"] = self._author_email
        return env

    async def publish(
        self,
        export_files: dict[str, str],
        trigger_info: str = "",
        is_full: bool = False,
    ) -> PublishResult:
        """Clone/pull target repo, write files, commit and push changes."""
        if not self._remote_url:
            return PublishResult(
                success=False, files_added=0, files_modified=0,
                files_deleted=0, error="No remote_url configured",
            )

        work_dir = tempfile.mkdtemp(prefix="kbs-wiki-publish-")
        try:
            return await self._do_publish(work_dir, export_files, trigger_info, is_full)
        except Exception as exc:
            log.error("Git publish failed: %s", exc, exc_info=True)
            return PublishResult(
                success=False, files_added=0, files_modified=0,
                files_deleted=0, error=str(exc),
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _do_publish(
        self,
        work_dir: str,
        export_files: dict[str, str],
        trigger_info: str,
        is_full: bool,
    ) -> PublishResult:
        env = self._build_git_env()

        await self._run_git(
            ["clone", "--depth=1", "-b", self._branch, self._auth_url(), work_dir],
            env=env,
        )

        annotations = self.scan_annotations(work_dir)
        existing_hashes = self._hash_existing_files(work_dir)
        changes = self.detect_changes(existing_hashes, export_files)

        if not changes["added"] and not changes["modified"] and not changes["deleted"]:
            return PublishResult(
                success=True, files_added=0, files_modified=0,
                files_deleted=0, annotations_found=len(annotations),
            )

        for path, content in export_files.items():
            full = Path(work_dir) / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")

        for path in changes["deleted"]:
            full = Path(work_dir) / path
            if full.exists():
                full.unlink()

        msg = self.generate_commit_message(
            changes["added"], changes["modified"], changes["deleted"],
            trigger_info=trigger_info, is_full=is_full,
        )

        await self._run_git(["add", "-A"], cwd=work_dir, env=env)
        await self._run_git(
            ["commit", "-m", msg,
             "--author", f"{self._author_name} <{self._author_email}>"],
            cwd=work_dir, env=env,
        )
        await self._run_git(
            ["push", "origin", self._branch], cwd=work_dir, env=env,
        )

        sha = await self._get_head_sha(work_dir, env)

        return PublishResult(
            success=True,
            files_added=len(changes["added"]),
            files_modified=len(changes["modified"]),
            files_deleted=len(changes["deleted"]),
            commit_sha=sha,
            annotations_found=len(annotations),
        )

    @staticmethod
    def _hash_existing_files(repo_dir: str) -> dict[str, str]:
        hashes: dict[str, str] = {}
        root = Path(repo_dir)
        for f in root.rglob("*.md"):
            if f.name.startswith("."):
                continue
            rel = str(f.relative_to(root)).replace(os.sep, "/")
            try:
                content = f.read_text(encoding="utf-8")
                hashes[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            except OSError:
                pass
        return hashes

    @staticmethod
    async def _run_git(
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"git {args[0]} failed (rc={proc.returncode}): {err_msg}")
        return stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    async def _get_head_sha(repo_dir: str, env: dict[str, str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_dir,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout.decode("utf-8", errors="replace").strip()
