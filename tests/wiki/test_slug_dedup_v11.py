"""Tests for V11 slug dedup fixes."""

from __future__ import annotations

import pytest

from wiki.nodes.graph_domain_decompose import (
    _dedup_parallel_naming_results,
    _dedupe_slug_segments,
)


class TestDedupeSlugSegments:
    """_dedupe_slug_segments removes consecutive repeated multi-word segments."""

    @pytest.mark.parametrize(
        ("slug", "expected"),
        [
            ("a-b-b", "a-b"),
            ("x-y-z-y-z", "x-y-z"),
            ("closed-friend-closed-friend", "closed-friend"),
            ("ultronult-ultronult", "ultronult"),
            ("payment-service", "payment-service"),
            ("user-auth-profile", "user-auth-profile"),
            ("a", "a"),
        ],
    )
    def test_removes_repeated_segments(self, slug: str, expected: str) -> None:
        assert _dedupe_slug_segments(slug) == expected

    def test_non_repeating_slugs_unchanged(self) -> None:
        for slug in ("order-management", "api-gateway-v2", "core-platform"):
            assert _dedupe_slug_segments(slug) == slug


class TestDedupParallelNamingSemanticSuffix:
    """Semantic suffix branch must resolve collisions and repeated segments."""

    def test_semantic_suffix_collision_adds_numeric_suffix(self) -> None:
        """When semantic new_slug already exists in seen, append counter."""
        results = [
            {
                "slug": "user-service",
                "display_name": "用户服务",
                "modules": ["com.user.AuthService"],
            },
            {
                "slug": "user-service",
                "display_name": "用户服务2",
                "modules": ["com.user.AuthService"],
            },
        ]
        deduped = _dedup_parallel_naming_results(results, existing_slugs=["user-service-auth"])
        slugs = [r["slug"] for r in deduped]
        assert "user-service" in slugs
        assert len(set(slugs)) == len(slugs)

    def test_closed_friend_repeated_segment_fixed(self) -> None:
        """Real-world: closed-friend + closed-friend suffix must not stay doubled."""
        results = [
            {
                "slug": "closed-friend",
                "display_name": "密友",
                "modules": ["com.app.ClosedFriendService"],
            },
        ]
        deduped = _dedup_parallel_naming_results(
            results,
            existing_slugs=["closed-friend"],
        )
        assert deduped[0]["slug"] != "closed-friend-closed-friend"

    def test_ultronult_repeated_segment_fixed(self) -> None:
        """Real-world: ultronult slug with ultronult module suffix."""
        results = [
            {
                "slug": "ultronult",
                "display_name": "Ultronult",
                "modules": ["com.app.Ultronult"],
            },
        ]
        deduped = _dedup_parallel_naming_results(
            results,
            existing_slugs=["ultronult"],
        )
        assert deduped[0]["slug"] == "ultronult"
