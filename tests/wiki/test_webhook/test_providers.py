"""Tests for wiki.webhook.providers — per-platform push payload parsers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wiki.webhook.event_model import ChangedFile
from wiki.webhook.providers.gitea import GiteaWebhookParser
from wiki.webhook.providers.github import GitHubWebhookParser
from wiki.webhook.providers.gitlab import GitLabWebhookParser


class TestGitHubWebhookParser:
    def test_parse_push_full_fields(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "1111111111111111111111111111111111111111",
            "after": "2222222222222222222222222222222222222222222",
            "repository": {"full_name": "acme/widget"},
            "sender": {"login": "alice"},
            "commits": [
                {
                    "added": ["new.py"],
                    "modified": ["src/app.py"],
                    "removed": [],
                },
                {
                    "added": [],
                    "modified": ["src/app.py"],
                    "removed": ["legacy.txt"],
                },
            ],
            "head_commit": {
                "timestamp": "2026-04-18T12:34:56Z",
            },
        }
        headers = {
            "x-github-event": "push",
            "x-github-delivery": "delivery-uuid-001",
        }
        ev = GitHubWebhookParser.parse_push(headers, payload)
        assert ev is not None
        assert ev.provider == "github"
        assert ev.event_type == "push"
        assert ev.delivery_id == "delivery-uuid-001"
        assert ev.repository == "acme/widget"
        assert ev.ref == "refs/heads/main"
        assert ev.before == payload["before"]
        assert ev.after == payload["after"]
        assert ev.sender == "alice"
        assert ev.timestamp == datetime(2026, 4, 18, 12, 34, 56, tzinfo=UTC)
        paths = {(cf.path, cf.status, cf.old_path) for cf in ev.changed_files}
        assert ("new.py", "added", None) in paths
        assert ("src/app.py", "modified", None) in paths
        assert ("legacy.txt", "removed", None) in paths

    def test_changed_files_dedup_last_wins(self) -> None:
        commits = [
            {"added": ["x.txt"], "modified": [], "removed": []},
            {"added": [], "modified": ["x.txt"], "removed": []},
        ]
        files = GitHubWebhookParser.extract_changed_files(commits)
        assert files == [ChangedFile(path="x.txt", status="modified")]

    def test_missing_optional_sender_and_delivery(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "o/r"},
            "commits": [],
            "head_commit": {"timestamp": "2026-01-01T00:00:00Z"},
        }
        ev = GitHubWebhookParser.parse_push({"x-github-event": "push"}, payload)
        assert ev is not None
        assert ev.sender == ""
        assert ev.delivery_id == ""
        assert ev.changed_files == []

    def test_commits_not_list_treated_as_empty(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "o/r"},
            "sender": {"login": "u"},
            "commits": "not-a-list",
            "head_commit": {"timestamp": "2026-01-01T00:00:00Z"},
        }
        ev = GitHubWebhookParser.parse_push(
            {"x-github-event": "push", "x-github-delivery": "d1"},
            payload,
        )
        assert ev is not None
        assert ev.changed_files == []

    def test_extract_delivery_id(self) -> None:
        assert (
            GitHubWebhookParser.extract_delivery_id({"x-github-delivery": "abc"})
            == "abc"
        )
        assert GitHubWebhookParser.extract_delivery_id({}) == ""

    def test_non_push_returns_none(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "o/r"},
            "commits": [],
            "head_commit": {"timestamp": "2026-01-01T00:00:00Z"},
        }
        assert GitHubWebhookParser.parse_push({"x-github-event": "issues"}, payload) is None


class TestGitLabWebhookParser:
    def test_parse_push_full_fields(self) -> None:
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/develop",
            "before": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "after": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "project": {"path_with_namespace": "group/sub/repo"},
            "user_username": "bob",
            "commits": [
                {
                    "timestamp": "2026-03-01T10:20:30Z",
                    "added": ["a.rb"],
                    "modified": [],
                    "removed": [],
                },
            ],
        }
        headers = {
            "x-gitlab-event-uuid": "gitlab-event-uuid-777",
        }
        ev = GitLabWebhookParser.parse_push(headers, payload)
        assert ev is not None
        assert ev.provider == "gitlab"
        assert ev.event_type == "push"
        assert ev.delivery_id == "gitlab-event-uuid-777"
        assert ev.repository == "group/sub/repo"
        assert ev.ref == "refs/heads/develop"
        assert ev.sender == "bob"
        assert ev.before == payload["before"]
        assert ev.after == payload["after"]
        assert ev.changed_files == [ChangedFile(path="a.rb", status="added")]
        assert ev.timestamp == datetime(2026, 3, 1, 10, 20, 30, tzinfo=UTC)

    def test_sender_fallback_user_name(self) -> None:
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/x",
            "before": "a" * 40,
            "after": "b" * 40,
            "project": {"path_with_namespace": "p/q"},
            "user_name": "Name Only",
            "commits": [{"timestamp": "2026-01-01T00:00:00Z"}],
        }
        ev = GitLabWebhookParser.parse_push({}, payload)
        assert ev is not None
        assert ev.sender == "Name Only"

    def test_changed_files_gitlab_rename(self) -> None:
        commits = [
            {
                "added": [],
                "modified": [],
                "removed": [],
                "renamed_file": {"old_path": "old.rb", "new_path": "new.rb"},
            },
        ]
        files = GitLabWebhookParser.extract_changed_files(commits)
        assert files == [
            ChangedFile(path="new.rb", status="renamed", old_path="old.rb"),
        ]

    def test_missing_delivery_and_empty_commits(self) -> None:
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/x",
            "before": "a" * 40,
            "after": "b" * 40,
            "project": {"path_with_namespace": "p/q"},
            "commits": [],
        }
        ev = GitLabWebhookParser.parse_push({}, payload)
        assert ev is not None
        assert ev.delivery_id == ""
        assert isinstance(ev.timestamp, datetime)

    def test_extract_delivery_id(self) -> None:
        assert (
            GitLabWebhookParser.extract_delivery_id({"x-gitlab-event-uuid": "u1"})
            == "u1"
        )
        assert GitLabWebhookParser.extract_delivery_id({}) == ""

    def test_non_push_returns_none(self) -> None:
        assert GitLabWebhookParser.parse_push({}, {"object_kind": "merge_request"}) is None


class TestGiteaWebhookParser:
    def test_parse_push_prefers_sender_over_pusher(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "c" * 40,
            "after": "d" * 40,
            "repository": {"full_name": "tea/k"},
            "sender": {"login": "sender-user"},
            "pusher": {"login": "pusher-user"},
            "commits": [{"added": [], "modified": ["x.go"], "removed": []}],
            "head_commit": {"timestamp": "2026-01-02T03:04:05+00:00"},
        }
        headers = {"x-gitea-event": "push", "x-gitea-delivery": "gitea-delivery-999"}
        ev = GiteaWebhookParser.parse_push(headers, payload)
        assert ev is not None
        assert ev.delivery_id == "gitea-delivery-999"
        assert ev.repository == "tea/k"
        assert ev.sender == "sender-user"
        assert ev.ref == "refs/heads/main"
        assert ev.before == payload["before"]
        assert ev.after == payload["after"]
        assert ev.changed_files == [ChangedFile(path="x.go", status="modified")]
        assert ev.timestamp == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    def test_pusher_when_no_sender(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "o/r"},
            "pusher": {"login": "carol"},
            "commits": [],
            "head_commit": {"timestamp": "2026-04-18T00:00:00Z"},
        }
        ev = GiteaWebhookParser.parse_push({"x-gitea-event": "push"}, payload)
        assert ev is not None
        assert ev.sender == "carol"

    def test_changed_files_dedup(self) -> None:
        commits = [
            {"added": ["f.go"], "modified": [], "removed": []},
            {"added": [], "modified": [], "removed": ["f.go"]},
        ]
        files = GiteaWebhookParser.extract_changed_files(commits)
        assert files == [ChangedFile(path="f.go", status="removed")]

    def test_extract_delivery_id(self) -> None:
        assert GiteaWebhookParser.extract_delivery_id({"x-gitea-delivery": "z"}) == "z"
        assert GiteaWebhookParser.extract_delivery_id({}) == ""

    def test_non_push_returns_none(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "o/r"},
            "commits": [],
            "head_commit": {"timestamp": "2026-01-01T00:00:00Z"},
        }
        assert GiteaWebhookParser.parse_push({"x-gitea-event": "pull_request"}, payload) is None


@pytest.mark.parametrize(
    "commits",
    [
        [
            {"added": ["a"], "modified": [], "removed": []},
            {"added": [], "modified": ["a"], "removed": []},
        ],
    ],
)
def test_extract_changed_files_same_path_across_commits(commits: list[dict]) -> None:
    """All providers share dedup semantics via extract_changed_files."""
    gh = GitHubWebhookParser.extract_changed_files(commits)
    gl = GitLabWebhookParser.extract_changed_files(commits)
    gt = GiteaWebhookParser.extract_changed_files(commits)
    expected = [ChangedFile(path="a", status="modified")]
    assert gh == expected and gl == expected and gt == expected
