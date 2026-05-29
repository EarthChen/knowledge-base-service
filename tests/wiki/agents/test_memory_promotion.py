from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.agents.memory_promotion import PromotionConfig, TierPromoter


class TestTierPromoter:
    @pytest.mark.asyncio
    async def test_promote_when_access_count_exceeds_threshold(self):
        """Entry with access_count >= threshold should be promoted."""
        promoter = TierPromoter(config=PromotionConfig(tier1_threshold=3, tier2_threshold=10))

        entry = MagicMock()
        entry.uid = "qa-123"
        entry.access_count = 5
        entry.tier = 0
        entry.confirmed = False

        store = AsyncMock()
        store.update_memory_tier = AsyncMock()

        result = await promoter.check_and_promote(entry, store)
        assert result["promoted"] is True
        assert result["new_tier"] == 1
        store.update_memory_tier.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_promotion_below_threshold(self):
        """Entry below threshold should not be promoted."""
        promoter = TierPromoter(config=PromotionConfig(tier1_threshold=3))

        entry = MagicMock()
        entry.uid = "qa-456"
        entry.access_count = 1
        entry.tier = 0

        store = AsyncMock()
        store.update_memory_tier = AsyncMock()

        result = await promoter.check_and_promote(entry, store)
        assert result["promoted"] is False
        store.update_memory_tier.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier2_promotion(self):
        """Entry with high access should promote to tier 2."""
        promoter = TierPromoter(config=PromotionConfig(tier1_threshold=3, tier2_threshold=10))

        entry = MagicMock()
        entry.uid = "qa-789"
        entry.access_count = 12
        entry.tier = 1
        entry.confirmed = True

        store = AsyncMock()
        store.update_memory_tier = AsyncMock()

        result = await promoter.check_and_promote(entry, store)
        assert result["promoted"] is True
        assert result["new_tier"] == 2

    @pytest.mark.asyncio
    async def test_already_max_tier_no_promotion(self):
        """Entry already at max tier should not be promoted."""
        promoter = TierPromoter(config=PromotionConfig(tier1_threshold=3, tier2_threshold=10))

        entry = MagicMock()
        entry.uid = "qa-max"
        entry.access_count = 100
        entry.tier = 2

        store = AsyncMock()
        store.update_memory_tier = AsyncMock()

        result = await promoter.check_and_promote(entry, store)
        assert result["promoted"] is False

    def test_promotion_config_defaults(self):
        config = PromotionConfig()
        assert config.tier1_threshold == 3
        assert config.tier2_threshold == 10
        assert config.max_tier == 2
