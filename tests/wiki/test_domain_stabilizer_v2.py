import pytest
from wiki.domain_stabilizer import DomainStabilizer


class TestDualFieldStabilize:
    @pytest.fixture
    def stabilizer(self):
        return DomainStabilizer(graph_store=None)

    def test_exact_slug_match(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [{"slug": "gift-system", "display_name": "Gift System"}]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert "gift-system" in result
        assert result["gift-system"]["slug"] == "gift-system"
        assert result["gift-system"]["display_name"] == "礼物系统"

    def test_display_name_similarity_match(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [{"slug": "gift-new", "display_name": "礼物管理系统"}]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        # Should match to existing gift-system due to display_name similarity
        assert "gift-system" in result

    def test_new_domain_passthrough(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [{"slug": "im-messaging", "display_name": "IM消息"}]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert "im-messaging" in result
        assert result["im-messaging"]["display_name"] == "IM消息"

    def test_empty_existing(self, stabilizer):
        proposed = [{"slug": "gift-system", "display_name": "礼物系统"}]
        result = stabilizer.stabilize_dual_sync(proposed, [])
        assert "gift-system" in result

    def test_multiple_proposed_no_collision(self, stabilizer):
        existing = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "im-messaging", "display_name": "IM消息"},
        ]
        proposed = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "im-messaging", "display_name": "IM消息"},
        ]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert len(result) == 2
        assert "gift-system" in result
        assert "im-messaging" in result

    def test_existing_not_reused_twice(self, stabilizer):
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "gift-v2", "display_name": "礼物系统v2"},
        ]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert len(result) == 2
        slugs = set(result.keys())
        assert "gift-system" in slugs
