from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def persist_classification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Save domain classification results to the database immediately.

    This node runs right after classify_domains_node to persist
    intermediate results, preventing data loss if later pipeline
    stages fail.
    """
    business_id = state.get("business_id", "")
    domain_mapping = state.get("domain_mapping", {})
    persistence = state.get("persistence")

    if not persistence:
        logger.warning("persist_classification: no persistence available, skipping")
        return {"classification_persisted": False}

    if not domain_mapping:
        logger.info("persist_classification: empty domain_mapping, nothing to persist")
        return {"classification_persisted": False}

    try:
        await persistence.save_domain_classification(business_id, domain_mapping)
        logger.info(
            "persist_classification: saved %d domains for %s",
            len(domain_mapping),
            business_id,
        )
        return {"classification_persisted": True}
    except Exception:
        logger.exception("persist_classification: failed to save classification")
        return {"classification_persisted": False}
