"""Tests for ASCII-only domain topic paths."""

from __future__ import annotations

import hashlib
import re

from wiki.path_conventions import domain_topic_path


def _topic_hash(section: str) -> str:
    return f"topic-{hashlib.md5(section.encode()).hexdigest()[:8]}"


class TestDomainTopicPathAscii:
    def test_ascii_section_passes_through(self):
        assert domain_topic_path("user-auth", "login-flow") == "/__domains__/user-auth/login-flow/_topic"

    def test_cjk_section_produces_english_slug(self):
        section = "挚友任务系统"
        path = domain_topic_path("closed-friend-system", section)
        assert re.fullmatch(r"/__domains__/closed-friend-system/[a-z0-9-]+/_topic", path)
        assert "zhi-you" not in path  # should NOT be pinyin anymore

    def test_cjk_section_is_deterministic(self):
        section = "挚友任务系统"
        assert domain_topic_path("closed-friend-system", section) == domain_topic_path(
            "closed-friend-system", section
        )

    def test_mixed_section_extracts_ascii(self):
        assert domain_topic_path("family", "family_任务_system") == "/__domains__/family/family-system/_topic"

    def test_empty_section_fallback(self):
        path = domain_topic_path("test", "")
        assert path == f"/__domains__/test/{_topic_hash('')}/_topic"

    def test_slash_in_section_replaced(self):
        path = domain_topic_path("test", "a/b/c")
        assert "/" not in path.split("/__domains__/test/")[1].split("/_topic")[0]
        assert path == "/__domains__/test/abc/_topic"
