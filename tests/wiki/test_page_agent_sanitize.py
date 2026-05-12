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


def test_strip_tool_invocation_descriptions():
    """Lines describing tool invocations (e.g. '调用 read_code 查看...') must be stripped."""
    content = (
        "# 支付处理\n\n"
        "## 概述\n\n"
        "支付处理域负责核心支付逻辑。\n\n"
        "我使用 read_code 查看了 PaymentService 的源码：\n\n"
        "接下来调用 query_call_chain 获取调用链：\n\n"
        "## 关键实现\n\n"
        "PaymentService 的核心逻辑如下。"
    )
    result = strip_agent_artifacts(content)
    assert "使用 read_code" not in result
    assert "调用 query_call_chain" not in result
    assert "## 关键实现" in result
    assert "PaymentService" in result


def test_strip_tool_call_inline_traces():
    """Lines with tool call syntax like 'read_code(entity="X")' must be removed."""
    content = (
        "# Domain\n\n"
        "## 概述\n\n正文内容。\n\n"
        "调用 read_code(entity=\"PayService.pay\") 获取代码...\n"
        "使用 search_entities(keywords=\"payment\") 搜索实体...\n"
        "## 关键实现\n\n实际内容。"
    )
    result = strip_agent_artifacts(content)
    assert 'read_code(entity=' not in result
    assert 'search_entities(keywords=' not in result
    assert "实际内容" in result
