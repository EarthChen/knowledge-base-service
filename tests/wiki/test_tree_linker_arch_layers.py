"""Tests for architecture_layers enrichment in WikiTreeLinker.get_domain_tree."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.tree_linker import WikiTreeLinker


@pytest.mark.asyncio
async def test_domain_tree_includes_architecture_layers() -> None:
    mock_store = MagicMock()
    snapshot = {
        "tree": [
            {
                "name": "user-management",
                "display_name": "User Management",
                "children": [],
                "modules": [],
            },
            {
                "name": "billing",
                "display_name": "Billing",
                "children": [],
                "modules": [],
            },
        ],
        "review_status": {"ok": True},
    }
    arch_layers = {
        "user-management": {"service": 3, "controller": 1},
        "billing": {"repository": 2},
    }
    with patch("wiki.tree_linker.WikiStore") as WS:
        WS.return_value.get_pipeline_domain_tree_snapshot = AsyncMock(return_value=snapshot)
        WS.return_value.get_domain_architecture_layers = AsyncMock(return_value=arch_layers)
        linker = WikiTreeLinker(mock_store, None, MagicMock(), MagicMock())
        out = await linker.get_domain_tree("b1")

    assert out["tree"][0]["architecture_layers"] == {"service": 3, "controller": 1}
    assert out["tree"][1]["architecture_layers"] == {"repository": 2}
    WS.return_value.get_domain_architecture_layers.assert_awaited_once_with("b1")


@pytest.mark.asyncio
async def test_domain_tree_aggregates_parent_layers() -> None:
    mock_store = MagicMock()
    snapshot = {
        "tree": [
            {
                "name": "platform",
                "display_name": "Platform",
                "children": [
                    {
                        "name": "auth",
                        "display_name": "Auth",
                        "children": [],
                        "modules": [],
                    },
                    {
                        "name": "users",
                        "display_name": "Users",
                        "children": [],
                        "modules": [],
                    },
                ],
                "modules": [],
            },
        ],
        "review_status": {},
    }
    arch_layers = {
        "auth": {"service": 2, "controller": 1},
        "users": {"service": 1, "repository": 3},
    }
    with patch("wiki.tree_linker.WikiStore") as WS:
        WS.return_value.get_pipeline_domain_tree_snapshot = AsyncMock(return_value=snapshot)
        WS.return_value.get_domain_architecture_layers = AsyncMock(return_value=arch_layers)
        linker = WikiTreeLinker(mock_store, None, MagicMock(), MagicMock())
        out = await linker.get_domain_tree("b1")

    parent = out["tree"][0]
    assert parent["children"][0]["architecture_layers"] == {"service": 2, "controller": 1}
    assert parent["children"][1]["architecture_layers"] == {"service": 1, "repository": 3}
    assert parent["architecture_layers"] == {"service": 3, "controller": 1, "repository": 3}


@pytest.mark.asyncio
async def test_domain_tree_graceful_on_arch_layers_error() -> None:
    mock_store = MagicMock()
    snapshot = {
        "tree": [{"name": "domain-a", "children": [], "modules": []}],
        "review_status": {"ok": True},
    }
    with patch("wiki.tree_linker.WikiStore") as WS:
        WS.return_value.get_pipeline_domain_tree_snapshot = AsyncMock(return_value=snapshot)
        WS.return_value.get_domain_architecture_layers = AsyncMock(side_effect=RuntimeError("db down"))
        linker = WikiTreeLinker(mock_store, None, MagicMock(), MagicMock())
        out = await linker.get_domain_tree("b1")

    assert out is snapshot
    assert "architecture_layers" not in out["tree"][0]


@pytest.mark.asyncio
async def test_domain_tree_no_store_returns_empty() -> None:
    linker = WikiTreeLinker(None, MagicMock(), MagicMock(), MagicMock())
    assert await linker.get_domain_tree("biz") == {"tree": [], "review_status": {}}
