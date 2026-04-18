"""Tests for wiki.webhook.receiver — WebhookReceiver verification and parsing (TDD)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from wiki.webhook.event_model import ChangedFile
from wiki.webhook.receiver import WebhookReceiver


def _github_sig(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _gitea_sig(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestVerifySignatureGithub:
    def test_accepts_valid_hmac_sha256(self) -> None:
        secret = "gh-secret"
        body = b'{"action":"opened"}'
        header = _github_sig(secret, body)
        assert WebhookReceiver.verify_signature("github", secret, body, header) is True

    def test_rejects_wrong_secret(self) -> None:
        secret = "gh-secret"
        body = b'{"x":1}'
        header = _github_sig("other-secret", body)
        assert WebhookReceiver.verify_signature("github", secret, body, header) is False

    def test_rejects_missing_sha256_prefix(self) -> None:
        secret = "gh-secret"
        body = b"{}"
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert WebhookReceiver.verify_signature("github", secret, body, digest) is False

    def test_rejects_none_header(self) -> None:
        assert WebhookReceiver.verify_signature("github", "s", b"{}", None) is False


class TestVerifySignatureGitlab:
    def test_accepts_matching_token(self) -> None:
        secret = "gl-token-value"
        body = b'{"object_kind":"push"}'
        assert WebhookReceiver.verify_signature("gitlab", secret, body, secret) is True

    def test_rejects_mismatched_token(self) -> None:
        secret = "gl-token-value"
        body = b"{}"
        assert WebhookReceiver.verify_signature("gitlab", secret, body, "other") is False

    def test_rejects_none_header(self) -> None:
        assert WebhookReceiver.verify_signature("gitlab", "s", b"{}", None) is False


class TestVerifySignatureGitea:
    def test_accepts_valid_hmac_hex(self) -> None:
        secret = "gte-secret"
        body = b'{"ref":"refs/heads/main"}'
        header = _gitea_sig(secret, body)
        assert WebhookReceiver.verify_signature("gitea", secret, body, header) is True

    def test_rejects_bad_signature(self) -> None:
        secret = "gte-secret"
        body = b'{"ref":"refs/heads/main"}'
        assert WebhookReceiver.verify_signature("gitea", secret, body, "deadbeef") is False


class TestParseEventGithubPush:
    def test_parses_push_extracts_fields(self) -> None:
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
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-uuid-001",
            "Content-Type": "application/json",
        }
        event = WebhookReceiver.parse_event("github", headers, body)
        assert event is not None
        assert event.provider == "github"
        assert event.event_type == "push"
        assert event.delivery_id == "delivery-uuid-001"
        assert event.repository == "acme/widget"
        assert event.ref == "refs/heads/main"
        assert event.before == payload["before"]
        assert event.after == payload["after"]
        assert event.sender == "alice"
        assert event.timestamp == datetime(2026, 4, 18, 12, 34, 56, tzinfo=UTC)
        paths = {(cf.path, cf.status, cf.old_path) for cf in event.changed_files}
        assert ("new.py", "added", None) in paths
        assert ("src/app.py", "modified", None) in paths
        assert ("legacy.txt", "removed", None) in paths


class TestParseEventGitlabPush:
    def test_parses_gitlab_push(self) -> None:
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/develop",
            "before": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "after": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "project": {"path_with_namespace": "group/sub/repo"},
            "user_username": "bob",
            "commits": [
                {"added": ["a.rb"], "modified": [], "removed": []},
            ],
        }
        body = json.dumps(payload).encode()
        headers = {
            "X-Gitlab-Event": "Push Hook",
            "X-Gitlab-Event-UUID": "gitlab-event-uuid-777",
        }
        event = WebhookReceiver.parse_event("gitlab", headers, body)
        assert event is not None
        assert event.provider == "gitlab"
        assert event.event_type == "push"
        assert event.delivery_id == "gitlab-event-uuid-777"
        assert event.repository == "group/sub/repo"
        assert event.ref == "refs/heads/develop"
        assert event.sender == "bob"
        assert isinstance(event.timestamp, datetime)


class TestParseEventGiteaPush:
    def test_parses_gitea_push(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "cccccccccccccccccccccccccccccccccccccccc",
            "after": "dddddddddddddddddddddddddddddddddddddddd",
            "repository": {"full_name": "tea/k"},
            "pusher": {"login": "carol"},
            "commits": [{"added": [], "modified": ["x.go"], "removed": []}],
            "head_commit": {"timestamp": "2026-01-02T03:04:05+00:00"},
        }
        body = json.dumps(payload).encode()
        headers = {
            "X-Gitea-Event": "push",
            "X-Gitea-Delivery": "gitea-delivery-999",
        }
        event = WebhookReceiver.parse_event("gitea", headers, body)
        assert event is not None
        assert event.provider == "gitea"
        assert event.delivery_id == "gitea-delivery-999"
        assert event.repository == "tea/k"
        assert event.sender == "carol"
        assert event.changed_files == [ChangedFile(path="x.go", status="modified")]


class TestParseEventNonPushReturnsNone:
    def test_github_issues_event_returns_none(self) -> None:
        payload = {"action": "opened", "repository": {"full_name": "a/b"}}
        body = json.dumps(payload).encode()
        headers = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "d1"}
        assert WebhookReceiver.parse_event("github", headers, body) is None

    def test_gitlab_merge_request_returns_none(self) -> None:
        payload = {"object_kind": "merge_request"}
        body = json.dumps(payload).encode()
        headers = {"X-Gitlab-Event": "Merge Request Hook"}
        assert WebhookReceiver.parse_event("gitlab", headers, body) is None

    def test_gitea_pull_request_returns_none(self) -> None:
        payload = {"pull_request": {}, "repository": {"full_name": "a/b"}}
        body = json.dumps(payload).encode()
        headers = {"X-Gitea-Event": "pull_request"}
        assert WebhookReceiver.parse_event("gitea", headers, body) is None


class TestParseEventMalformedPayload:
    def test_invalid_json_returns_none(self) -> None:
        headers = {"X-GitHub-Event": "push", "X-GitHub-Delivery": "x"}
        assert WebhookReceiver.parse_event("github", headers, b"not-json") is None

    def test_github_push_missing_repository_returns_none(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "commits": [],
            "head_commit": {"timestamp": "2026-04-18T00:00:00Z"},
        }
        body = json.dumps(payload).encode()
        headers = {"X-GitHub-Event": "push", "X-GitHub-Delivery": "d"}
        assert WebhookReceiver.parse_event("github", headers, body) is None


class TestDeliveryIdExtraction:
    def test_github_delivery_header(self) -> None:
        payload = _minimal_github_push_payload()
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "abc-def-ghi",
        }
        ev = WebhookReceiver.parse_event("github", headers, body)
        assert ev is not None and ev.delivery_id == "abc-def-ghi"

    def test_gitlab_event_uuid_header(self) -> None:
        payload = {
            "object_kind": "push",
            "ref": "refs/heads/x",
            "before": "a" * 40,
            "after": "b" * 40,
            "project": {"path_with_namespace": "p/q"},
            "commits": [],
        }
        body = json.dumps(payload).encode()
        headers = {"X-Gitlab-Event-UUID": "uuid-only"}
        ev = WebhookReceiver.parse_event("gitlab", headers, body)
        assert ev is not None and ev.delivery_id == "uuid-only"

    def test_gitea_delivery_header(self) -> None:
        payload = {
            "ref": "refs/heads/x",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "o/r"},
            "sender": {"login": "u"},
            "commits": [],
            "head_commit": {"timestamp": "2026-04-18T00:00:00Z"},
        }
        body = json.dumps(payload).encode()
        headers = {"X-Gitea-Event": "push", "X-Gitea-Delivery": "del-123"}
        ev = WebhookReceiver.parse_event("gitea", headers, body)
        assert ev is not None and ev.delivery_id == "del-123"


def _minimal_github_push_payload() -> dict:
    return {
        "ref": "refs/heads/main",
        "before": "1111111111111111111111111111111111111111",
        "after": "2222222222222222222222222222222222222222222",
        "repository": {"full_name": "o/r"},
        "sender": {"login": "u"},
        "commits": [],
        "head_commit": {"timestamp": "2026-04-18T00:00:00Z"},
    }


class TestParseEventDictPayload:
    def test_accepts_preparsed_dict(self) -> None:
        payload = _minimal_github_push_payload()
        headers = {"X-GitHub-Event": "push", "X-GitHub-Delivery": "dict-case"}
        ev = WebhookReceiver.parse_event("github", headers, payload)
        assert ev is not None
        assert ev.delivery_id == "dict-case"


class TestWebhookEventModel:
    def test_changed_file_optional_old_path(self) -> None:
        cf = ChangedFile(path="b", status="renamed", old_path="a")
        assert cf.old_path == "a"


class TestUnknownProvider:
    def test_verify_unknown_provider_returns_false(self) -> None:
        assert WebhookReceiver.verify_signature("bitbucket", "s", b"{}", "x") is False

    def test_parse_unknown_provider_returns_none(self) -> None:
        assert WebhookReceiver.parse_event("bitbucket", {}, b"{}") is None
