"""Test graph-based pre-grouping using Union-Find connected components."""
import asyncio
from unittest.mock import AsyncMock
from dataclasses import dataclass

import pytest


@dataclass
class _FakeResult:
    data: list


@pytest.fixture
def mock_graph():
    graph = AsyncMock()
    return graph


def test_connected_components_basic(mock_graph):
    """Modules connected by CALLS should be in the same group."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[
        {"source": "ModuleA", "target": "ModuleB", "weight": 5},
        {"source": "ModuleB", "target": "ModuleC", "weight": 2},
        {"source": "ModuleD", "target": "ModuleE", "weight": 1},
    ]))

    module_paths = {
        "ModuleA": "com/example/meeting/ModuleA.java",
        "ModuleB": "com/example/meeting/ModuleB.java",
        "ModuleC": "com/example/meeting/sub/ModuleC.java",
        "ModuleD": "com/example/user/ModuleD.java",
        "ModuleE": "com/example/user/ModuleE.java",
    }

    groups = asyncio.run(
        compute_pre_groups(mock_graph, ["repo1"], module_paths)
    )

    assert len(groups) == 2
    group_sizes = sorted([len(g.module_names) for g in groups])
    assert group_sizes == [2, 3]


def test_singleton_modules_excluded(mock_graph):
    """Modules with no CALLS edges should not appear in any group."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[
        {"source": "ModuleA", "target": "ModuleB", "weight": 1},
    ]))

    module_paths = {
        "ModuleA": "a/ModuleA.java",
        "ModuleB": "a/ModuleB.java",
        "ModuleC": "b/ModuleC.java",  # isolated
    }

    groups = asyncio.run(
        compute_pre_groups(mock_graph, ["repo1"], module_paths)
    )

    assert len(groups) == 1
    assert "ModuleC" not in groups[0].module_names


def test_directory_prefix_computed(mock_graph):
    """Each group should have the longest common directory prefix."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[
        {"source": "ModA", "target": "ModB", "weight": 1},
    ]))

    module_paths = {
        "ModA": "com/example/meeting/service/ModA.java",
        "ModB": "com/example/meeting/dao/ModB.java",
    }

    groups = asyncio.run(
        compute_pre_groups(mock_graph, ["repo1"], module_paths)
    )

    assert len(groups) == 1
    assert "com/example/meeting" in groups[0].directory_prefix


def test_empty_graph_returns_no_groups(mock_graph):
    """No CALLS edges should yield empty groups."""
    from wiki.graph_pre_grouper import compute_pre_groups

    mock_graph.execute_query = AsyncMock(return_value=_FakeResult(data=[]))

    groups = asyncio.run(
        compute_pre_groups(mock_graph, ["repo1"], {"ModA": "a/ModA.java"})
    )

    assert groups == []
