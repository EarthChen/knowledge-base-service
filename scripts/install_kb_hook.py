#!/usr/bin/env python3
"""Install or remove the Knowledge Base post-commit git hook."""

from __future__ import annotations

import argparse
import shutil
import stat
import subprocess
from pathlib import Path

HOOK_MARKER = "installed-by: knowledge-base-service kb-hook"
HOOK_TEMPLATE = Path(__file__).resolve().parent / "hooks" / "post-commit"
ENV_TEMPLATE = """# Knowledge Base post-commit hook configuration
KB_URL=http://localhost:8100
KB_TOKEN=
KB_BUSINESS_ID=default
"""


def git_toplevel(start: Path | None = None) -> Path:
    """Return the git repository root for *start* (default: cwd)."""
    cwd = start or Path.cwd()
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "not a git repository").strip()
        raise SystemExit(f"error: {msg}")
    return Path(result.stdout.strip())


def _hook_paths(repo_root: Path) -> tuple[Path, Path]:
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise SystemExit(f"error: no .git directory under {repo_root}")
    return git_dir / "hooks" / "post-commit", repo_root / ".kb-hook.env"


def _is_our_hook(path: Path) -> bool:
    if not path.is_file():
        return False
    return HOOK_MARKER in path.read_text(encoding="utf-8")


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install(*, repo_root: Path, dry_run: bool, force: bool) -> None:
    hook_path, env_path = _hook_paths(repo_root)

    if not HOOK_TEMPLATE.is_file():
        raise SystemExit(f"error: hook template not found: {HOOK_TEMPLATE}")

    actions: list[str] = []

    if hook_path.is_file() and not force:
        if hook_path.read_text(encoding="utf-8") != HOOK_TEMPLATE.read_text(encoding="utf-8"):
            print(f"skip: hook already exists at {hook_path} (use --force to overwrite)")
            return
    else:
        actions.append(f"install hook -> {hook_path}")

    if not env_path.is_file():
        actions.append(f"create config -> {env_path}")

    if dry_run:
        for line in actions:
            print(f"dry-run: would {line}")
        if not actions:
            print("dry-run: nothing to do")
        return

    hook_path.parent.mkdir(parents=True, exist_ok=True)
    if force or not hook_path.is_file() or hook_path.read_text(encoding="utf-8") != HOOK_TEMPLATE.read_text(
        encoding="utf-8",
    ):
        shutil.copy2(HOOK_TEMPLATE, hook_path)
        _make_executable(hook_path)
        print(f"installed hook: {hook_path}")

    if not env_path.is_file():
        env_path.write_text(ENV_TEMPLATE, encoding="utf-8")
        print(f"created config template: {env_path}")
    else:
        print(f"config exists (unchanged): {env_path}")


def uninstall(*, repo_root: Path, dry_run: bool) -> None:
    hook_path, _env_path = _hook_paths(repo_root)

    if not hook_path.is_file():
        print(f"skip: no hook at {hook_path}")
        return

    if not _is_our_hook(hook_path):
        print(f"skip: hook at {hook_path} was not installed by this tool")
        return

    if dry_run:
        print(f"dry-run: would remove hook {hook_path}")
        return

    hook_path.unlink()
    print(f"removed hook: {hook_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Install Knowledge Base post-commit git hook")
    parser.add_argument("--uninstall", action="store_true", help="Remove the installed hook")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing files")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing post-commit hook")
    args = parser.parse_args(argv)

    repo_root = git_toplevel()

    if args.uninstall:
        uninstall(repo_root=repo_root, dry_run=args.dry_run)
    else:
        install(repo_root=repo_root, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
