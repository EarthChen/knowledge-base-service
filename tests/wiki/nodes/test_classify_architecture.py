"""Tests for classify_architecture_layers_node pipeline node."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.architecture_classifier import LayerResult


def _modules_state() -> dict:
    return {
        "modules": {
            "repo1": [
                {"properties": {"name": "UserController", "path": "src/api/UserController.java"}},
                {"properties": {"name": "UserService", "path": "src/service/UserService.java"}},
            ],
        },
    }


@pytest.mark.asyncio
async def test_classify_arch_layers_node_basic() -> None:
    """Mock graph_store + modules in state → returns architecture_layers."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    mock_store = MagicMock()
    config = {"configurable": {"graph_store": mock_store, "llm": MagicMock()}}

    async def _classify(name: str, path: str) -> LayerResult:
        layer = "api" if "Controller" in name else "service"
        return LayerResult(layer=layer, confidence=0.85, votes=[])

    mock_classifier = MagicMock()
    mock_classifier.classify_module = AsyncMock(side_effect=_classify)

    with patch(
        "wiki.architecture_classifier.ArchitectureLayerClassifier",
        return_value=mock_classifier,
    ):
        result = await classify_architecture_layers_node(_modules_state(), config)

    assert "architecture_layers" in result
    layers = result["architecture_layers"]
    assert layers["UserController"] == {"layer": "api", "confidence": 0.85}
    assert layers["UserService"] == {"layer": "service", "confidence": 0.85}
    assert mock_classifier.classify_module.await_count == 2


@pytest.mark.asyncio
async def test_classify_arch_layers_node_no_store() -> None:
    """graph_store is None → returns empty dict."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    result = await classify_architecture_layers_node(_modules_state(), {"configurable": {}})
    assert result == {"architecture_layers": {}}


@pytest.mark.asyncio
async def test_classify_arch_layers_node_error_handling() -> None:
    """One module throws → others still classified."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    mock_store = MagicMock()
    config = {"configurable": {"graph_store": mock_store}}

    async def _classify(name: str, path: str) -> LayerResult:
        if name == "UserController":
            raise RuntimeError("classifier boom")
        return LayerResult(layer="service", confidence=0.7, votes=[])

    mock_classifier = MagicMock()
    mock_classifier.classify_module = AsyncMock(side_effect=_classify)

    with patch(
        "wiki.architecture_classifier.ArchitectureLayerClassifier",
        return_value=mock_classifier,
    ):
        result = await classify_architecture_layers_node(_modules_state(), config)

    layers = result["architecture_layers"]
    assert "UserController" not in layers
    assert layers["UserService"] == {"layer": "service", "confidence": 0.7}


@pytest.mark.asyncio
async def test_classify_arch_layers_node_concurrent() -> None:
    """Multiple modules should be classified concurrently (not strictly one-at-a-time)."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    concurrent = [0]
    max_concurrent = [0]
    lock = asyncio.Lock()

    mock_store = MagicMock()
    config = {"configurable": {"graph_store": mock_store}}

    async def _classify(name: str, path: str) -> LayerResult:
        async with lock:
            concurrent[0] += 1
            max_concurrent[0] = max(max_concurrent[0], concurrent[0])
        try:
            await asyncio.sleep(0.05)
        finally:
            async with lock:
                concurrent[0] -= 1
        layer = "api" if "Controller" in name else "service"
        return LayerResult(layer=layer, confidence=0.85, votes=[])

    mock_classifier = MagicMock()
    mock_classifier.classify_module = AsyncMock(side_effect=_classify)

    n_modules = 8
    modules_state = {
        "modules": {
            "repo1": [
                {
                    "properties": {
                        "name": f"Module{i}",
                        "path": f"src/service/Module{i}.java",
                    }
                }
                for i in range(n_modules)
            ],
        },
    }

    with patch(
        "wiki.architecture_classifier.ArchitectureLayerClassifier",
        return_value=mock_classifier,
    ):
        result = await classify_architecture_layers_node(modules_state, config)

    assert len(result["architecture_layers"]) == n_modules
    assert mock_classifier.classify_module.await_count == n_modules
    assert max_concurrent[0] >= 2, (
        "classify_module should overlap for independent modules "
        f"(expected >= 2 concurrent, got max {max_concurrent[0]})"
    )
