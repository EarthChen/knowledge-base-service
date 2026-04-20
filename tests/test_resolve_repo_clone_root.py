"""Tests for :func:`git_manager.resolve_repo_clone_root`."""

from __future__ import annotations

from pathlib import Path

from config import GitConfig
from git_manager import resolve_repo_clone_root
from repo_registry import RepoRegistry


def test_resolve_direct_name_under_clone_base(tmp_path: Path) -> None:
    clone_base = tmp_path / "repos"
    clone_base.mkdir()
    named = clone_base / "my-service"
    named.mkdir()
    cfg = GitConfig(clone_base_path=str(clone_base))
    assert resolve_repo_clone_root("my-service", cfg, None) == named.resolve()


def test_resolve_canonical_name_via_repo_registry(tmp_path: Path) -> None:
    clone_base = tmp_path / "repos"
    clone_base.mkdir()
    url_layout = clone_base / "group" / "project"
    url_layout.mkdir(parents=True)
    (url_layout / "main.py").write_text("print(1)\n", encoding="utf-8")

    reg_dir = tmp_path / "data"
    reg_dir.mkdir()
    reg = RepoRegistry(str(reg_dir))
    reg.register("https://git.example.com/group/project.git", "user-moa")

    cfg = GitConfig(clone_base_path=str(clone_base))
    got = resolve_repo_clone_root("user-moa", cfg, reg)
    assert got == url_layout.resolve()


def test_resolve_absolute_local_path_via_registry_outside_clone_base(tmp_path: Path) -> None:
    """Directory indexes may register an absolute path; it must resolve even if not under clone_base."""
    clone_base = tmp_path / "managed_repos"
    clone_base.mkdir()
    external = tmp_path / "work" / "user-moa"
    external.mkdir(parents=True)
    (external / "README.md").write_text("ok\n", encoding="utf-8")

    reg_dir = tmp_path / "data"
    reg_dir.mkdir()
    reg = RepoRegistry(str(reg_dir))
    reg.register(str(external.resolve()), "user-moa")

    cfg = GitConfig(clone_base_path=str(clone_base))
    got = resolve_repo_clone_root("user-moa", cfg, reg)
    assert got == external.resolve()
