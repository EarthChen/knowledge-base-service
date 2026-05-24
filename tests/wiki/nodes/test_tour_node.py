from __future__ import annotations

import pytest
from unittest.mock import patch

from wiki.nodes.tour import generate_tour_node


class TestGenerateTourNode:
    @pytest.mark.asyncio
    async def test_produces_guided_tour(self):
        state = {
            "pages": [
                {"path": "api/controller.md", "title": "Controller", "covered_entity_uids": ["e1"]},
                {"path": "svc/service.md", "title": "Service", "covered_entity_uids": ["e2"]},
            ],
            "architecture_layers": {
                "ControllerMod": {"layer": "api", "confidence": 0.9, "entity_uids": ["e1"]},
                "ServiceMod": {"layer": "service", "confidence": 0.8, "entity_uids": ["e2"]},
            },
            "domain_tree": [],
        }
        result = await generate_tour_node(state)
        assert "guided_tour" in result
        tour = result["guided_tour"]
        assert tour["total_pages"] == 2

    @pytest.mark.asyncio
    async def test_empty_pages(self):
        state = {"pages": [], "architecture_layers": {}, "domain_tree": []}
        result = await generate_tour_node(state)
        assert result["guided_tour"]["total_pages"] == 0

    @pytest.mark.asyncio
    async def test_disabled_by_config(self):
        state = {"pages": [{"path": "a.md", "title": "A", "covered_entity_uids": []}]}
        with patch("wiki.nodes.tour._is_tour_enabled", return_value=False):
            result = await generate_tour_node(state)
        assert result["guided_tour"]["total_pages"] == 0
