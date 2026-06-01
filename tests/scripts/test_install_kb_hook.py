"""Tests for scripts/install_kb_hook.py and scripts/hooks/post-commit."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PROJECT_ROOT / "scripts" / "install_kb_hook.py"
HOOK_TEMPLATE = PROJECT_ROOT / "scripts" / "hooks" / "post-commit"
ENV_TEMPLATE_LINES = ("KB_URL=", "KB_TOKEN=", "KB_BUSINESS_ID=")


def _run_installer(
    git_repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(INSTALLER), *args]
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=git_repo,
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


def test_installer_creates_hook_with_template_content(git_repo: Path) -> None:
    assert HOOK_TEMPLATE.is_file()
    result = _run_installer(git_repo)
    assert result.returncode == 0, result.stderr

    hook_path = git_repo / ".git" / "hooks" / "post-commit"
    assert hook_path.is_file()
    assert hook_path.read_text(encoding="utf-8") == HOOK_TEMPLATE.read_text(encoding="utf-8")
    assert hook_path.stat().st_mode & stat.S_IXUSR


def test_installer_creates_kb_hook_env_template(git_repo: Path) -> None:
    result = _run_installer(git_repo)
    assert result.returncode == 0, result.stderr

    env_path = git_repo / ".kb-hook.env"
    assert env_path.is_file()
    content = env_path.read_text(encoding="utf-8")
    for fragment in ENV_TEMPLATE_LINES:
        assert fragment in content


def test_installer_does_not_overwrite_existing_env(git_repo: Path) -> None:
    env_path = git_repo / ".kb-hook.env"
    custom = "KB_URL=http://custom:9999\nKB_TOKEN=secret\nKB_BUSINESS_ID=custom\n"
    env_path.write_text(custom, encoding="utf-8")

    result = _run_installer(git_repo)
    assert result.returncode == 0, result.stderr
    assert env_path.read_text(encoding="utf-8") == custom


def test_uninstall_removes_hook(git_repo: Path) -> None:
    _run_installer(git_repo)
    hook_path = git_repo / ".git" / "hooks" / "post-commit"
    assert hook_path.is_file()

    result = _run_installer(git_repo, "--uninstall")
    assert result.returncode == 0, result.stderr
    assert not hook_path.exists()


def test_dry_run_does_not_create_files(git_repo: Path) -> None:
    result = _run_installer(git_repo, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout.lower() or "would" in result.stdout.lower()

    assert not (git_repo / ".git" / "hooks" / "post-commit").exists()
    assert not (git_repo / ".kb-hook.env").exists()


def test_without_force_existing_hook_not_overwritten(git_repo: Path) -> None:
    hook_path = git_repo / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    custom_hook = "#!/usr/bin/env bash\necho 'custom'\n"
    hook_path.write_text(custom_hook, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR)

    result = _run_installer(git_repo)
    assert result.returncode == 0, result.stderr
    assert hook_path.read_text(encoding="utf-8") == custom_hook
    assert "exists" in result.stdout.lower() or "skip" in result.stdout.lower()


def test_force_overwrites_existing_hook(git_repo: Path) -> None:
    hook_path = git_repo / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text("#!/usr/bin/env bash\necho 'custom'\n", encoding="utf-8")

    result = _run_installer(git_repo, "--force")
    assert result.returncode == 0, result.stderr
    assert hook_path.read_text(encoding="utf-8") == HOOK_TEMPLATE.read_text(encoding="utf-8")


def test_post_commit_hook_is_valid_bash(git_repo: Path) -> None:
    assert HOOK_TEMPLATE.is_file()
    first_line = HOOK_TEMPLATE.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!") and "bash" in first_line

    result = subprocess.run(
        ["bash", "-n", str(HOOK_TEMPLATE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    _run_installer(git_repo)
    installed = git_repo / ".git" / "hooks" / "post-commit"
    assert installed.stat().st_mode & stat.S_IXUSR
    syntax = subprocess.run(["bash", "-n", str(installed)], capture_output=True, text=True, check=False)
    assert syntax.returncode == 0, syntax.stderr


def test_post_commit_exits_zero_without_token(git_repo: Path) -> None:
    _run_installer(git_repo)
    hook = git_repo / ".git" / "hooks" / "post-commit"
    env = git_repo / ".kb-hook.env"
    env.write_text(
        "KB_URL=http://127.0.0.1:1\nKB_TOKEN=\nKB_BUSINESS_ID=default\n",
        encoding="utf-8",
    )
    result = subprocess.run([str(hook)], cwd=git_repo, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "KB_TOKEN" in result.stderr or "token" in result.stderr.lower()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_installer_fails_outside_git_repo(tmp_path: Path) -> None:
    result = _run_installer(tmp_path)
    assert result.returncode != 0
    assert "git" in (result.stderr + result.stdout).lower()
