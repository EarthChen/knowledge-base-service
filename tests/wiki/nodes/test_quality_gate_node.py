import pytest


@pytest.mark.asyncio
async def test_l3_evaluations_run_in_parallel(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from wiki.nodes.quality_gate import quality_gate_node

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.85, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.7)
    monkeypatch.setattr("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval)

    l3_call_count = 0

    async def mock_evaluate_l3(content, modules, llm):
        nonlocal l3_call_count
        l3_call_count += 1
        result = MagicMock()
        result.dimensions = {"completeness": 4, "accuracy": 4, "readability": 4, "structure": 4}
        return result

    mock_l3_eval = MagicMock()
    mock_l3_eval.evaluate_l3 = mock_evaluate_l3
    monkeypatch.setattr("wiki.nodes.quality_gate.WikiPageEvaluator", lambda: mock_l3_eval)
    monkeypatch.setattr("wiki.nodes.quality_gate.verify_citations", lambda content, names: MagicMock(invalid_count=0))

    pages = []
    for i in range(3):
        pages.append({
            "path": f"wiki/page_{i}",
            "title": f"Page {i}",
            "content": f"## Overview\nContent for page {i}.\n\n```java\npublic class Page{i} {{}}\n```\n\n## Details\nMore content here.\n" + "x" * 200,
            "page_type": "topic",
            "diagrams": [{"type": "flowchart", "content": "graph TD\nA-->B"}],
            "source_locations": [],
            "metadata": {},
        })

    state = {
        "pages": pages,
        "config": {
            "quality_levels": ["L1", "L3"],
            "importance_tiers": {f"wiki/page_{i}": "core" for i in range(3)},
        },
        "heal_attempts": {},
        "_structural_check_cache": {},
        "modules": {},
    }
    config = {"configurable": {"llm": MagicMock()}}

    result = await quality_gate_node(state, config)
    assert l3_call_count == 3, f"Expected 3 L3 evaluations, got {l3_call_count}"
    for i in range(3):
        score = result["quality_scores"][f"wiki/page_{i}"]
        assert score.get("l3_llm_judge") is not None


@pytest.mark.asyncio
async def test_pages_to_heal_sorted_by_l1_when_no_l2(monkeypatch):
    """When L2 is not in levels, pages_to_heal should be sorted by L1 (worst-first)."""
    from unittest.mock import MagicMock

    from wiki.nodes.quality_gate import quality_gate_node

    mock_eval = MagicMock()

    def fake_structural(page):
        scores = {"wiki/page_a": 0.3, "wiki/page_b": 0.4}
        return MagicMock(overall=scores.get(page.path, 0.5), issues=[])

    mock_eval.structural_check = fake_structural
    monkeypatch.setattr("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval)
    monkeypatch.setattr("wiki.nodes.quality_gate.verify_citations", lambda c, n: MagicMock(invalid_count=0))

    pages = [
        {"path": "wiki/page_b", "title": "B", "content": "short", "page_type": "topic", "diagrams": [], "source_locations": [], "metadata": {}},
        {"path": "wiki/page_a", "title": "A", "content": "short", "page_type": "topic", "diagrams": [], "source_locations": [], "metadata": {}},
    ]
    state = {
        "pages": pages,
        "config": {"quality_levels": ["L1"]},
        "heal_attempts": {},
        "_structural_check_cache": {},
        "modules": {},
    }
    result = await quality_gate_node(state)
    heal_list = result["pages_to_heal"]
    assert len(heal_list) == 2
    assert heal_list[0] == "wiki/page_a"
    assert heal_list[1] == "wiki/page_b"
