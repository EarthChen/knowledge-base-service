"""Tests for collision slug cleanup in domain decomposition."""
from __future__ import annotations

import pytest


class TestCleanupCollisionSlugs:
    def test_hash_suffix_merged(self):
        """Slugs with -xxxx hash suffix should merge into base slug."""
        from wiki.nodes.graph_domain_decompose import _cleanup_collision_slugs

        domain_mapping = {
            "closed-friend-relations": [("repo1", "ModA")],
            "closed-friend-relations-024d": [("repo1", "ModB")],
            "closed-friend-relations-4a30": [("repo1", "ModC")],
        }
        display_names = {
            "closed-friend-relations": "挚友关系",
            "closed-friend-relations-024d": "挚友关系",
            "closed-friend-relations-4a30": "挚友关系",
        }
        new_mapping, new_display = _cleanup_collision_slugs(domain_mapping, display_names)

        assert "closed-friend-relations-024d" not in new_mapping
        assert "closed-friend-relations-4a30" not in new_mapping
        assert "closed-friend-relations" in new_mapping
        assert len(new_mapping["closed-friend-relations"]) == 3

    def test_numeric_suffix_merged(self):
        """Slugs with -N numeric suffix should merge into base slug."""
        from wiki.nodes.graph_domain_decompose import _cleanup_collision_slugs

        domain_mapping = {
            "family-system": [("repo1", "ModA")],
            "family-system-1": [("repo1", "ModB")],
            "family-system-2": [("repo1", "ModC")],
            "family-system-9": [("repo1", "ModD")],
        }
        display_names = {
            "family-system": "家族系统",
            "family-system-1": "家族系统",
            "family-system-2": "家族系统",
            "family-system-9": "家族系统",
        }
        new_mapping, new_display = _cleanup_collision_slugs(domain_mapping, display_names)

        assert len(new_mapping) == 1
        assert "family-system" in new_mapping
        assert len(new_mapping["family-system"]) == 4

    def test_no_base_slug_creates_one(self):
        """When base slug doesn't exist, first variant becomes canonical."""
        from wiki.nodes.graph_domain_decompose import _cleanup_collision_slugs

        domain_mapping = {
            "im-1": [("repo1", "ModA")],
            "im-3": [("repo1", "ModB")],
            "im-8": [("repo1", "ModC")],
        }
        display_names = {
            "im-1": "即时消息",
            "im-3": "即时消息",
            "im-8": "即时消息",
        }
        new_mapping, new_display = _cleanup_collision_slugs(domain_mapping, display_names)

        assert len(new_mapping) == 1
        canonical = list(new_mapping.keys())[0]
        assert canonical == "im"
        assert len(new_mapping[canonical]) == 3

    def test_legitimate_suffixes_preserved(self):
        """Slugs where -N is part of the real name should be preserved."""
        from wiki.nodes.graph_domain_decompose import _cleanup_collision_slugs

        domain_mapping = {
            "user-vip": [("repo1", "ModA")],
            "user-level": [("repo1", "ModB")],
        }
        display_names = {
            "user-vip": "用户VIP",
            "user-level": "用户等级",
        }
        new_mapping, new_display = _cleanup_collision_slugs(domain_mapping, display_names)

        assert len(new_mapping) == 2
        assert "user-vip" in new_mapping
        assert "user-level" in new_mapping
