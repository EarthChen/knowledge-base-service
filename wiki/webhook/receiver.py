"""Verify and parse Git provider webhook payloads into WebhookEvent."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from wiki.webhook.event_model import ChangedFile, WebhookEvent


def _lower_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(k).lower(): v for k, v in headers.items()}


def _parse_json_payload(payload: bytes | str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        try:
            raw = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        raw = payload
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _parse_iso_timestamp(value: str) -> datetime | None:
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (OSError, TypeError, ValueError):
        return None


def _merge_commit_files(commits: list[dict[str, Any]]) -> list[ChangedFile]:
    """Last mention of a path wins (simulates stacked commits)."""
    by_path: dict[str, ChangedFile] = {}
    for commit in commits:
        for path in commit.get("added") or []:
            if isinstance(path, str):
                by_path[path] = ChangedFile(path=path, status="added")
        for path in commit.get("modified") or []:
            if isinstance(path, str):
                by_path[path] = ChangedFile(path=path, status="modified")
        for path in commit.get("removed") or []:
            if isinstance(path, str):
                by_path[path] = ChangedFile(path=path, status="removed")
        # GitLab rename: optional "renamed_file" style per commit (when present)
        renamed = commit.get("renamed_file")
        if isinstance(renamed, dict):
            new_p = renamed.get("new_path")
            old_p = renamed.get("old_path")
            if isinstance(new_p, str) and isinstance(old_p, str):
                by_path[new_p] = ChangedFile(path=new_p, status="renamed", old_path=old_p)
    return list(by_path.values())


def _github_timestamp(data: dict[str, Any]) -> datetime:
    head = data.get("head_commit")
    if isinstance(head, dict):
        ts = head.get("timestamp")
        if isinstance(ts, str):
            parsed = _parse_iso_timestamp(ts)
            if parsed is not None:
                return parsed
    return datetime.now(UTC)


def _gitlab_timestamp(commits: list[dict[str, Any]]) -> datetime:
    for commit in reversed(commits):
        ts = commit.get("timestamp")
        if isinstance(ts, str):
            parsed = _parse_iso_timestamp(ts)
            if parsed is not None:
                return parsed
    return datetime.now(UTC)


class WebhookReceiver:
    """Verify webhook authenticity and parse push payloads."""

    @staticmethod
    def verify_signature(
        provider: str,
        secret: str,
        payload_bytes: bytes,
        signature_header: str | None,
    ) -> bool:
        if provider == "github":
            if not signature_header or not signature_header.startswith("sha256="):
                return False
            digest_hex = signature_header.removeprefix("sha256=")
            try:
                expected = bytes.fromhex(digest_hex)
            except ValueError:
                return False
            mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
            return hmac.compare_digest(mac, expected)

        if provider == "gitlab":
            if signature_header is None:
                return False
            if len(signature_header) != len(secret):
                return False
            return hmac.compare_digest(signature_header.encode("utf-8"), secret.encode("utf-8"))

        if provider == "gitea":
            if not signature_header:
                return False
            sig_clean = signature_header.strip().lower()
            if not sig_clean:
                return False
            expected_hex = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
            if len(sig_clean) != len(expected_hex):
                return False
            return hmac.compare_digest(expected_hex, sig_clean)

        return False

    @staticmethod
    def parse_event(
        provider: str,
        headers: Mapping[str, str],
        payload: bytes | str | dict[str, Any],
    ) -> WebhookEvent | None:
        hd = _lower_headers(headers)
        data = _parse_json_payload(payload)
        if data is None:
            return None

        if provider == "github":
            return WebhookReceiver._parse_github(data, hd)
        if provider == "gitlab":
            return WebhookReceiver._parse_gitlab(data, hd)
        if provider == "gitea":
            return WebhookReceiver._parse_gitea(data, hd)
        return None

    @staticmethod
    def _parse_github(data: dict[str, Any], hd: dict[str, str]) -> WebhookEvent | None:
        event_name = hd.get("x-github-event", "").lower()
        if event_name != "push":
            return None

        repo_obj = data.get("repository")
        if not isinstance(repo_obj, dict):
            return None
        full_name = repo_obj.get("full_name")
        if not isinstance(full_name, str) or not full_name:
            return None

        ref = data.get("ref")
        before = data.get("before")
        after = data.get("after")
        if not isinstance(ref, str) or not isinstance(before, str) or not isinstance(after, str):
            return None

        commits = data.get("commits")
        if not isinstance(commits, list):
            commits = []
        commit_dicts = [c for c in commits if isinstance(c, dict)]

        sender_obj = data.get("sender")
        sender = ""
        if isinstance(sender_obj, dict):
            login = sender_obj.get("login")
            if isinstance(login, str):
                sender = login

        delivery_id = hd.get("x-github-delivery") or ""
        changed = _merge_commit_files(commit_dicts)
        ts = _github_timestamp(data)

        return WebhookEvent(
            provider="github",
            event_type="push",
            delivery_id=delivery_id,
            repository=full_name,
            ref=ref,
            before=before,
            after=after,
            changed_files=changed,
            sender=sender,
            timestamp=ts,
        )

    @staticmethod
    def _parse_gitlab(data: dict[str, Any], hd: dict[str, str]) -> WebhookEvent | None:
        kind = data.get("object_kind")
        if kind != "push":
            return None

        project = data.get("project")
        if not isinstance(project, dict):
            return None
        path = project.get("path_with_namespace")
        if not isinstance(path, str) or not path:
            return None

        ref = data.get("ref")
        before = data.get("before")
        after = data.get("after")
        if not isinstance(ref, str) or not isinstance(before, str) or not isinstance(after, str):
            return None

        commits = data.get("commits")
        if not isinstance(commits, list):
            commits = []
        commit_dicts = [c for c in commits if isinstance(c, dict)]

        sender = ""
        for key in ("user_username", "user_name", "user_email"):
            val = data.get(key)
            if isinstance(val, str) and val:
                sender = val
                break

        delivery_id = hd.get("x-gitlab-event-uuid") or ""

        ts = _gitlab_timestamp(commit_dicts)
        changed = _merge_commit_files(commit_dicts)

        return WebhookEvent(
            provider="gitlab",
            event_type="push",
            delivery_id=delivery_id,
            repository=path,
            ref=ref,
            before=before,
            after=after,
            changed_files=changed,
            sender=sender,
            timestamp=ts,
        )

    @staticmethod
    def _parse_gitea(data: dict[str, Any], hd: dict[str, str]) -> WebhookEvent | None:
        event_name = hd.get("x-gitea-event", "").lower()
        if event_name != "push":
            return None

        repo_obj = data.get("repository")
        if not isinstance(repo_obj, dict):
            return None
        full_name = repo_obj.get("full_name")
        if not isinstance(full_name, str) or not full_name:
            return None

        ref = data.get("ref")
        before = data.get("before")
        after = data.get("after")
        if not isinstance(ref, str) or not isinstance(before, str) or not isinstance(after, str):
            return None

        commits = data.get("commits")
        if not isinstance(commits, list):
            commits = []
        commit_dicts = [c for c in commits if isinstance(c, dict)]

        sender = ""
        sender_obj = data.get("sender")
        if isinstance(sender_obj, dict):
            login = sender_obj.get("login")
            if isinstance(login, str):
                sender = login
        if not sender:
            pusher = data.get("pusher")
            if isinstance(pusher, dict):
                plogin = pusher.get("login")
                if isinstance(plogin, str):
                    sender = plogin

        delivery_id = hd.get("x-gitea-delivery") or ""

        ts = _github_timestamp(data)
        changed = _merge_commit_files(commit_dicts)

        return WebhookEvent(
            provider="gitea",
            event_type="push",
            delivery_id=delivery_id,
            repository=full_name,
            ref=ref,
            before=before,
            after=after,
            changed_files=changed,
            sender=sender,
            timestamp=ts,
        )
