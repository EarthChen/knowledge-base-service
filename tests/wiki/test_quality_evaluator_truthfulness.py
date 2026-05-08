from unittest.mock import MagicMock

from wiki.quality_evaluator import WikiQualityEvaluator


def _make_page(content: str):
    page = MagicMock()
    page.path = "wiki/test-page"
    page.content = content
    page.title = "Test Page"
    page.diagrams = []
    page.source_locations = []
    return page


def test_truthfulness_drops_on_thinking_leak():
    evaluator = WikiQualityEvaluator()
    page = _make_page("我需要查询两个缺失信息。\n\n## 概述\n\n内容。")
    score = evaluator.structural_check(page)
    assert score.truthfulness < 1.0


def test_truthfulness_drops_on_fake_source():
    evaluator = WikiQualityEvaluator()
    page = _make_page("## 代码引用\n\n- `source://src/main/java/com/xxx/ranking/Foo.java`")
    score = evaluator.structural_check(page)
    assert score.truthfulness < 1.0


def test_truthfulness_stays_high_for_clean_page():
    evaluator = WikiQualityEvaluator()
    page = _make_page("## 业务概述\n\n正常内容。\n\n## 核心服务详解\n\n详细说明。")
    score = evaluator.structural_check(page)
    assert score.truthfulness == 1.0
