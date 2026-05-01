import pytest

from wiki.mermaid_validator import validate_mermaid_block


def test_valid_flowchart():
    result = validate_mermaid_block("graph TD\n    A-->B\n    B-->C")
    assert result.is_valid is True
    assert result.error_message is None


def test_valid_sequence_diagram():
    result = validate_mermaid_block("sequenceDiagram\n    Alice->>Bob: Hello")
    assert result.is_valid is True


def test_invalid_syntax():
    result = validate_mermaid_block("graph TD\n    A->B")
    assert result.is_valid is False


def test_empty_input():
    result = validate_mermaid_block("")
    assert result.is_valid is False
    assert result.error_message is not None


def test_nonsense_input():
    result = validate_mermaid_block("this is not mermaid at all")
    assert result.is_valid is False


def test_diagram_quality_check_validates_syntax():
    from wiki.models import PageType, WikiPage, WikiPageMetadata
    from wiki.quality_evaluator import WikiQualityEvaluator

    evaluator = WikiQualityEvaluator()
    page = WikiPage(
        path="wiki/test",
        title="Test",
        page_type=PageType.TOPIC,
        content="# Test\n\n```mermaid\ngraph TD\n    A->B\n```\n",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )
    score = evaluator.diagram_quality_check(page)
    assert score.valid_syntax is False


def test_diagram_quality_check_valid_syntax():
    from wiki.models import PageType, WikiPage, WikiPageMetadata
    from wiki.quality_evaluator import WikiQualityEvaluator

    evaluator = WikiQualityEvaluator()
    page = WikiPage(
        path="wiki/test",
        title="Test",
        page_type=PageType.TOPIC,
        content="# Test\n\n```mermaid\ngraph TD\n    A-->B\n    B-->C\n```\n",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )
    score = evaluator.diagram_quality_check(page)
    assert score.valid_syntax is True
