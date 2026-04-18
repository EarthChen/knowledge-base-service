"""Normalized webhook payload types for Git provider push events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChangedFile:
    path: str
    status: str  # 'added' | 'modified' | 'removed' | 'renamed'
    old_path: str | None = None


@dataclass
class WebhookEvent:
    provider: str  # 'github' | 'gitlab' | 'gitea'
    event_type: str  # 'push' | 'pull_request' | 'merge_request' | 'tag_push'
    delivery_id: str  # platform-provided idempotency key
    repository: str
    ref: str  # e.g. refs/heads/main
    before: str  # commit SHA (before)
    after: str  # commit SHA (after)
    changed_files: list[ChangedFile]
    sender: str
    timestamp: datetime
