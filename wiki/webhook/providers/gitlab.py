"""GitLab push webhook payload parser."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from wiki.webhook.event_model import ChangedFile, WebhookEvent
from wiki.webhook.providers.commits import merge_changed_files_from_commits
from wiki.webhook.providers.timeutil import parse_iso_timestamp


class GitLabWebhookParser:
    @staticmethod
    def parse_push(headers: dict[str, str], payload: dict[str, Any]) -> WebhookEvent | None:
        """Parse GitLab push webhook payload into WebhookEvent."""
        kind = payload.get("object_kind")
        if kind != "push":
            return None

        project = payload.get("project")
        if not isinstance(project, dict):
            return None
        path = project.get("path_with_namespace")
        if not isinstance(path, str) or not path:
            return None

        ref = payload.get("ref")
        before = payload.get("before")
        after = payload.get("after")
        if not isinstance(ref, str) or not isinstance(before, str) or not isinstance(after, str):
            return None

        commits = payload.get("commits")
        if not isinstance(commits, list):
            commits = []
        commit_dicts = [c for c in commits if isinstance(c, dict)]

        sender = ""
        for key in ("user_username", "user_name", "user_email"):
            val = payload.get(key)
            if isinstance(val, str) and val:
                sender = val
                break

        delivery_id = GitLabWebhookParser.extract_delivery_id(headers)
        ts = GitLabWebhookParser._push_timestamp(commit_dicts)
        changed = GitLabWebhookParser.extract_changed_files(commit_dicts)

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
    def extract_delivery_id(headers: dict[str, str]) -> str:
        """Extract delivery ID from headers."""
        val = headers.get("x-gitlab-event-uuid")
        return val if isinstance(val, str) else ""

    @staticmethod
    def extract_changed_files(commits: list[dict[str, Any]]) -> list[ChangedFile]:
        """Extract changed files from commit list, dedup by path."""
        return merge_changed_files_from_commits(commits)

    @staticmethod
    def _push_timestamp(commits: list[dict[str, Any]]) -> datetime:
        for commit in reversed(commits):
            ts = commit.get("timestamp")
            if isinstance(ts, str):
                parsed = parse_iso_timestamp(ts)
                if parsed is not None:
                    return parsed
        return datetime.now(UTC)
