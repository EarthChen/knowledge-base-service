"""Verify and parse Git provider webhook payloads into WebhookEvent."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from wiki.webhook.event_model import WebhookEvent
from wiki.webhook.providers.gitea import GiteaWebhookParser
from wiki.webhook.providers.github import GitHubWebhookParser
from wiki.webhook.providers.gitlab import GitLabWebhookParser


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
            return GitHubWebhookParser.parse_push(hd, data)
        if provider == "gitlab":
            return GitLabWebhookParser.parse_push(hd, data)
        if provider == "gitea":
            return GiteaWebhookParser.parse_push(hd, data)
        return None
