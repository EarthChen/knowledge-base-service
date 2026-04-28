import pytest
from wiki.delegation import evaluate_delegation, group_children_by_graph
from wiki.models import WikiStructureNode, PageType


def _make_children(count: int) -> list[WikiStructureNode]:
    return [
        WikiStructureNode(path=f"classes/C{i}.md", title=f"C{i}", page_type=PageType.CLASS_DETAIL)
        for i in range(count)
    ]


def test_no_delegation_under_threshold():
    children = _make_children(10)
    decision = evaluate_delegation(
        children_count=len(children), total_code_lines=1000,
        max_children=30, max_code_lines=5000,
    )
    assert not decision.should_delegate


def test_delegation_triggered_by_children_count():
    children = _make_children(50)
    decision = evaluate_delegation(
        children_count=len(children), total_code_lines=1000,
        max_children=30, max_code_lines=5000,
    )
    assert decision.should_delegate
    assert decision.reason == "too_many_children"


def test_delegation_triggered_by_code_lines():
    decision = evaluate_delegation(
        children_count=10, total_code_lines=8000,
        max_children=30, max_code_lines=5000,
    )
    assert decision.should_delegate
    assert decision.reason == "too_much_code"


def test_group_children_by_graph_connected_components():
    children = _make_children(6)
    edges = [
        (children[0].path, children[1].path),
        (children[1].path, children[2].path),
        (children[3].path, children[4].path),
    ]
    groups = group_children_by_graph(children, edges)
    assert len(groups) == 3
    group_sizes = sorted(len(g) for g in groups)
    assert group_sizes == [1, 2, 3]


def test_group_children_chunk_fallback():
    children = _make_children(10)
    groups = group_children_by_graph(children, edges=[], max_group_size=4)
    assert len(groups) == 3
    assert all(len(g) <= 4 for g in groups)


def test_group_children_single_node():
    children = _make_children(1)
    groups = group_children_by_graph(children, edges=[])
    assert len(groups) == 1
    assert len(groups[0]) == 1


def test_group_children_empty():
    groups = group_children_by_graph([], edges=[])
    assert groups == []
