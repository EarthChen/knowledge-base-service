from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.graph_domain_namer import GraphDomainNamer, validate_slug_display_consistency


class TestValidateSlugDisplayConsistency:
    def test_consistent_slug_display(self):
        assert validate_slug_display_consistency(
            "closed-friend",
            "挚友关系",
            ["ClosedFriendService", "ClosedFriendHandler"],
        )

    def test_inconsistent_slug_display(self):
        assert not validate_slug_display_consistency(
            "quick-message",
            "在线状态",
            ["QuickMessageService", "QuickMessageHandler"],
        )

    def test_known_mapping_override(self):
        assert validate_slug_display_consistency(
            "quick-message",
            "快捷消息",
            ["QuickMessageService"],
        )


class TestFallbackWhenInconsistent:
    @pytest.mark.asyncio
    async def test_fallback_when_inconsistent(self):
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(
            return_value='{"slug": "quick-message", "display_name": "在线状态", "description": "desc"}'
        )
        namer = GraphDomainNamer(mock_llm)
        result = await namer.name_community(
            ["QuickMessageService", "QuickMessageHandler", "QuickMessageDao"],
        )
        assert result["slug"] == "quick-message"
        assert result["display_name"] == "快捷消息"
