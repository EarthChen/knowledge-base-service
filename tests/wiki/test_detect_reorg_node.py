from __future__ import annotations

import pytest
from wiki.pipeline_nodes import detect_reorg_node


@pytest.mark.asyncio
async def test_first_run_when_no_domain_tree():
    state = {
        "domain_tree": None,
        "is_incremental": False,
        "entity_roles": {"a": "has_business_logic"},
        "role_stats": {"has_business_logic": 1},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "first_run"


@pytest.mark.asyncio
async def test_none_when_incremental_no_change():
    state = {
        "domain_tree": [{"name": "payment", "modules": ["PaymentService"]}],
        "is_incremental": True,
        "entity_roles": {"PaymentService": "has_business_logic"},
        "role_stats": {"has_business_logic": 1},
        "affected_domains": [],
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "none"


@pytest.mark.asyncio
async def test_light_when_incremental_with_affected_domains():
    state = {
        "domain_tree": [
            {"name": "payment", "modules": ["PaymentService", "NewService"]},
        ],
        "is_incremental": True,
        "entity_roles": {"PaymentService": "has_business_logic", "NewService": "has_business_logic"},
        "role_stats": {"has_business_logic": 2},
        "affected_domains": ["payment"],
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "light"
