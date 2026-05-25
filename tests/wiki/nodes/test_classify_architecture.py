"""Tests for classify_architecture_layers_node pipeline node."""

from __future__ import annotations

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

    async def _classify_batch(modules: list[tuple[str, str]]) -> dict[str, LayerResult]:
        results: dict[str, LayerResult] = {}
        for name, _path in modules:
            layer = "api" if "Controller" in name else "service"
            results[name] = LayerResult(layer=layer, confidence=0.85, votes=[])
        return results

    mock_classifier = MagicMock()
    mock_classifier.classify_modules_batch = AsyncMock(side_effect=_classify_batch)

    with patch(
        "wiki.architecture_classifier.ArchitectureLayerClassifier",
        return_value=mock_classifier,
    ):
        result = await classify_architecture_layers_node(_modules_state(), config)

    assert "architecture_layers" in result
    layers = result["architecture_layers"]
    assert layers["repo1|UserController"] == {"layer": "api", "confidence": 0.85}
    assert layers["repo1|UserService"] == {"layer": "service", "confidence": 0.85}
    mock_classifier.classify_modules_batch.assert_awaited_once()
    call_args = mock_classifier.classify_modules_batch.await_args[0][0]
    assert ("UserController", "src/api/UserController.java") in call_args
    assert ("UserService", "src/service/UserService.java") in call_args


@pytest.mark.asyncio
async def test_classify_arch_layers_node_no_store() -> None:
    """graph_store is None → returns empty dict."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    result = await classify_architecture_layers_node(_modules_state(), {"configurable": {}})
    assert result == {"architecture_layers": {}}


@pytest.mark.asyncio
async def test_classify_arch_layers_node_error_handling() -> None:
    """Batch failure → returns empty architecture_layers."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    mock_store = MagicMock()
    config = {"configurable": {"graph_store": mock_store}}

    mock_classifier = MagicMock()
    mock_classifier.classify_modules_batch = AsyncMock(side_effect=RuntimeError("classifier boom"))

    with patch(
        "wiki.architecture_classifier.ArchitectureLayerClassifier",
        return_value=mock_classifier,
    ):
        result = await classify_architecture_layers_node(_modules_state(), config)

    assert result == {"architecture_layers": {}}


@pytest.mark.asyncio
async def test_classify_arch_layers_node_batch_single_call() -> None:
    """All modules should be classified in a single batch call."""
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    mock_store = MagicMock()
    config = {"configurable": {"graph_store": mock_store}}

    async def _classify_batch(modules: list[tuple[str, str]]) -> dict[str, LayerResult]:
        return {
            name: LayerResult(layer="service", confidence=0.85, votes=[])
            for name, _path in modules
        }

    mock_classifier = MagicMock()
    mock_classifier.classify_modules_batch = AsyncMock(side_effect=_classify_batch)

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
    mock_classifier.classify_modules_batch.assert_awaited_once()
    assert len(mock_classifier.classify_modules_batch.await_args[0][0]) == n_modules
