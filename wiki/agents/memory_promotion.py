from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.log import get_logger

log = get_logger(__name__)


@dataclass
class PromotionConfig:
    """Configuration for memory tier promotion thresholds."""

    tier1_threshold: int = 3
    tier2_threshold: int = 10
    max_tier: int = 2
    require_confirmation_for_tier2: bool = True


class TierPromoter:
    """Real-time memory tier promotion based on access count."""

    def __init__(self, config: PromotionConfig | None = None):
        self._config = config or PromotionConfig()

    async def check_and_promote(self, entry: Any, store: Any) -> dict:
        """Check if entry qualifies for tier promotion and promote if so."""
        current_tier = getattr(entry, "tier", 0)
        access_count = getattr(entry, "access_count", 0)
        uid = getattr(entry, "uid", None)

        if current_tier >= self._config.max_tier:
            return {"promoted": False, "reason": "max_tier_reached", "current_tier": current_tier}

        new_tier = current_tier

        if current_tier == 0 and access_count >= self._config.tier1_threshold:
            new_tier = 1
        elif current_tier == 1 and access_count >= self._config.tier2_threshold:
            if self._config.require_confirmation_for_tier2:
                if not getattr(entry, "confirmed", False):
                    return {"promoted": False, "reason": "confirmation_required", "current_tier": current_tier}
            new_tier = 2

        if new_tier > current_tier and uid and store:
            try:
                await store.update_memory_tier(uid=uid, tier=new_tier)
                log.info(
                    "memory_tier_promoted",
                    uid=uid,
                    old_tier=current_tier,
                    new_tier=new_tier,
                    access_count=access_count,
                )
                return {"promoted": True, "new_tier": new_tier, "old_tier": current_tier}
            except Exception as e:
                log.warning("memory_promotion_failed", uid=uid, error=str(e))
                return {"promoted": False, "reason": "store_error", "error": str(e)}

        return {
            "promoted": False,
            "reason": "threshold_not_met",
            "current_tier": current_tier,
            "access_count": access_count,
        }
