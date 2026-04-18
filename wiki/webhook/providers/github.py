"""GitHub push webhook payload parser."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from wiki.webhook.event_model import ChangedFile, WebhookEvent
from wiki.webhook.providers.commits import merge_changed_files_from_commits
from wiki.webhook.providers.timeutil import parse_iso_timestamp


class GitHubWebhookParser:
    @staticmethod
    def parse_push(headers: dict[str, str], payload: dict[str, Any]) -> WebhookEvent | None:
        """Parse GitHub push webhook payload into WebhookEvent."""
        event_name = headers.get("x-github-event", "").lower()
        if event_name != "push":
            return None

        repo_obj = payload.get("repository")
        if not isinstance(repo_obj, dict):
            return None
        full_name = repo_obj.get("full_name")
        if not isinstance(full_name, str) or not full_name:
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

        sender_obj = payload.get("sender")
        sender = ""
        if isinstance(sender_obj, dict):
            login = sender_obj.get("login")
            if isinstance(login, str):
                sender = login

        delivery_id = GitHubWebhookParser.extract_delivery_id(headers)
        changed = GitHubWebhookParser.extract_changed_files(commit_dicts)
        ts = GitHubWebhookParser._push_timestamp(payload)

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
    def extract_delivery_id(headers: dict[str, str]) -> str:
        """Extract delivery ID from headers."""
        val = headers.get("x-github-delivery")
        return val if isinstance(val, str) else ""

    @staticmethod
    def extract_changed_files(commits: list[dict[str, Any]]) -> list[ChangedFile]:
        """Extract changed files from commit list, dedup by path."""
        return merge_changed_files_from_commits(commits)

    @staticmethod
    def _push_timestamp(data: dict[str, Any]) -> datetime:
        head = data.get("head_commit")
        if isinstance(head, dict):
            ts = head.get("timestamp")
            if isinstance(ts, str):
                parsed = parse_iso_timestamp(ts)
                if parsed is not None:
                    return parsed
        return datetime.now(UTC)
