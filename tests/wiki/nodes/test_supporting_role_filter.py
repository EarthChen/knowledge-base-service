"""Test SUPPORTING role exclusion from domain classification."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from wiki.entity_role_classifier import WikiEntityRole


def test_supporting_excluded_when_config_disabled():
    from wiki.nodes.graph_domain_decompose import _filter_biz_modules

    entity_roles = {
        "uid1": WikiEntityRole.HAS_BUSINESS_LOGIC,
        "uid2": WikiEntityRole.SUPPORTING,
        "uid3": WikiEntityRole.DATA_MODEL,
    }
    modules = {
        "repo1": [
            {"uid": "uid1", "properties": {"name": "OrderService", "path": "order/service.py"}},
            {"uid": "uid2", "properties": {"name": "StringHelper", "path": "util/string.py"}},
            {"uid": "uid3", "properties": {"name": "OrderModel", "path": "order/model.py"}},
        ]
    }

    with patch("wiki.nodes.graph_domain_decompose.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.classify_include_supporting = False
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        biz, excluded, paths, docs = _filter_biz_modules(entity_roles, modules)

    biz_names = [name for _, name in biz]
    assert "OrderService" in biz_names
    assert "StringHelper" not in biz_names
    assert "OrderModel" not in biz_names
    assert "StringHelper" in [name for _, name in excluded]


def test_supporting_included_when_config_enabled():
    from wiki.nodes.graph_domain_decompose import _filter_biz_modules

    entity_roles = {
        "uid1": WikiEntityRole.HAS_BUSINESS_LOGIC,
        "uid2": WikiEntityRole.SUPPORTING,
    }
    modules = {
        "repo1": [
            {"uid": "uid1", "properties": {"name": "OrderService", "path": "order/service.py"}},
            {"uid": "uid2", "properties": {"name": "StringHelper", "path": "util/string.py"}},
        ]
    }

    with patch("wiki.nodes.graph_domain_decompose.get_settings") as mock_settings:
        wiki_cfg = MagicMock()
        wiki_cfg.classify_include_supporting = True
        mock_settings.return_value = MagicMock(wiki=wiki_cfg)

        biz, excluded, paths, docs = _filter_biz_modules(entity_roles, modules)

    biz_names = [name for _, name in biz]
    assert "OrderService" in biz_names
    assert "StringHelper" in biz_names
    assert len(excluded) == 0
