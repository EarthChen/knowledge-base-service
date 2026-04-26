"""Tests for shared git URL detection."""

from __future__ import annotations

from utils.git_utils import looks_like_git_url


def test_looks_like_git_url_http_https_ssh_gitat() -> None:
    assert looks_like_git_url("https://github.com/a/b.git") is True
    assert looks_like_git_url("http://x/y") is True
    assert looks_like_git_url("git@github.com:a/b.git") is True
    assert looks_like_git_url("ssh://host/repo.git") is True


def test_looks_like_git_url_endswith_git() -> None:
    assert looks_like_git_url("local/path/case.git") is True


def test_looks_like_git_url_rejects_plain_path() -> None:
    assert looks_like_git_url("relative/path") is False
    assert looks_like_git_url("C:/dev/repo") is False
