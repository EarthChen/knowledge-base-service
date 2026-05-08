from wiki.page_agent import strip_agent_artifacts


def test_strip_agent_artifacts_removes_thinking_prefix():
    raw = (
        "我需要补充 `CONTEXT_GAP` 中提到的缺失信息，包括：\n"
        "1. 订单回调请求体字段定义\n\n"
        "```json\n{\"tools\": [{\"name\": \"search_code\"}]}\n```\n\n"
        "---\n\n"
        "## Components\n\n| Component | Description |\n"
        "|-----------|-------------|\n| Foo | Bar |\n"
    )
    result = strip_agent_artifacts(raw)
    assert "我需要" not in result
    assert "tools" not in result
    assert "## Components" in result


def test_strip_agent_artifacts_preserves_clean_content():
    clean = "## 业务概述\n\n这是正常内容。\n\n## 核心服务详解\n\n详细说明。"
    result = strip_agent_artifacts(clean)
    assert result == clean


def test_strip_agent_artifacts_returns_empty_on_all_thinking():
    raw = "我需要查询两个缺失信息。\n让我先尝试搜索。"
    result = strip_agent_artifacts(raw)
    assert result == ""


def test_strip_agent_artifacts_handles_english_thinking():
    raw = "I need to search for more context.\n\n```json\n{\"tools\": []}\n```\n\n## Overview\n\nReal content."
    result = strip_agent_artifacts(raw)
    assert "I need to" not in result
    assert "## Overview" in result
