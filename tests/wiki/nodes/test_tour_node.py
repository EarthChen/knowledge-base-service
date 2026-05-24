from __future__ import annotations

import pytest
from unittest.mock import patch

from wiki.nodes.tour import _build_page_dependency_graph, generate_tour_node


class TestBuildPageDependencyGraph:
    def test_prerequisite_before_dependent(self):
        pages = [
            {"path": "owner.md", "covered_entity_uids": ["e1"]},
            {"path": "dependent.md", "covered_entity_uids": ["e1", "e2"]},
        ]
        edges = _build_page_dependency_graph(pages)
        assert edges["owner.md"] == ["dependent.md"]
        assert edges["dependent.md"] == []

    def test_first_wins_entity_owner(self):
        pages = [
            {"path": "first.md", "covered_entity_uids": ["shared"]},
            {"path": "second.md", "covered_entity_uids": ["shared"]},
        ]
        edges = _build_page_dependency_graph(pages)
        assert edges["first.md"] == ["second.md"]
        assert edges["second.md"] == []


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

    @pytest.mark.asyncio
    async def test_populates_reading_order_in_page_navigation(self):
        state = {
            "pages": [
                {
                    "path": "owner.md",
                    "title": "Owner",
                    "covered_entity_uids": ["e1"],
                    "navigation": {"parent_path": None, "sibling_paths": []},
                },
                {
                    "path": "dependent.md",
                    "title": "Dependent",
                    "covered_entity_uids": ["e1", "e2"],
                    "navigation": {"parent_path": None, "sibling_paths": []},
                },
            ],
            "architecture_layers": {
                "OwnerMod": {"layer": "api", "confidence": 0.9, "entity_uids": ["e1"]},
                "DepMod": {"layer": "service", "confidence": 0.8, "entity_uids": ["e2"]},
            },
            "domain_tree": [],
        }
        result = await generate_tour_node(state)

        pages_by_path = {p["path"]: p for p in result["pages"]}
        assert pages_by_path["owner.md"]["navigation"]["reading_order"] == 1
        assert pages_by_path["dependent.md"]["navigation"]["reading_order"] == 2
        assert pages_by_path["owner.md"]["navigation"]["sibling_paths"] == []
