"""Tests for V9 Batch C quality gate heal hints (F11)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.nodes.quality_gate import quality_gate_node


def _mock_wiki_settings(**overrides: object) -> MagicMock:
    wiki_cfg = MagicMock()
    wiki_cfg.heal_l2_threshold = 0.0
    wiki_cfg.heal_on_l3_failure = False
    wiki_cfg.heal_l3_threshold = 0.5
    wiki_cfg.overview_min_content_chars = 2000
    wiki_cfg.topic_min_content_chars = 500
    wiki_cfg.language_guardrail_cn_ratio = 0.15
    for key, value in overrides.items():
        setattr(wiki_cfg, key, value)
    return wiki_cfg


def _quality_gate_patches(mock_eval: MagicMock, wiki_cfg: MagicMock):
    return (
        patch("wiki.nodes.quality_gate.get_settings", return_value=MagicMock(wiki=wiki_cfg)),
        patch("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval),
        patch(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        ),
    )


@pytest.mark.asyncio
async def test_quality_gate_shell_domain():
    """214-char shell domain overview with a single H2 should produce heal_hint."""
    content = (
        "## 子域概览\n\n"
        "本域是多个子域的父级容器，负责协调各子域之间的协作关系。"
        "子域 A 负责用户管理，子域 B 负责订单处理，子域 C 负责支付流程。"
        "更多导航链接见下方表格。"
    )
    assert len(content) < 500

    page = {
        "path": "/__domains__/family/_overview",
        "title": "Family Overview",
        "page_type": "domain_overview",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "shell_domain_overview: content too thin, only 1 section" in hint
    assert page["path"] in result["pages_to_heal"]


@pytest.mark.asyncio
async def test_quality_gate_topic_no_code():
    """Topic without fenced code blocks should produce heal_hint."""
    content = (
        "## 概述\n\n"
        "该模块负责处理用户认证与授权流程，并与下游服务协同完成业务处理。"
        "核心职责包括会话管理、权限校验和令牌刷新。"
        "详细设计见架构图与关联模块说明。"
        "\n\n## 关键组件\n\n"
        "AuthService 协调认证流程，TokenValidator 校验访问令牌。"
        "\n\n## 关联关系\n\n"
        "- [[user-service]]\n"
    )
    page = {
        "path": "/__domains__/auth/token-flow",
        "title": "Token Flow",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "topic_no_code: topic has no code examples" in hint
    assert page["path"] in result["pages_to_heal"]


@pytest.mark.asyncio
async def test_quality_gate_normal_overview_no_hint():
    """Normal overview with multiple sections should not produce shell heal_hint."""
    content = (
        "## 概述\n\n"
        + "本域负责用户与权限相关的核心业务能力，涵盖认证、授权与会话管理。" * 40
        + "\n\n## 核心模块\n\n"
        + "AuthService 与 PermissionService 协同工作。" * 20
        + "\n\n## 数据流\n\n"
        + "请求经网关进入认证模块后分发至下游服务。" * 20
    )
    page = {
        "path": "/__domains__/auth/_overview",
        "title": "Auth Overview",
        "page_type": "domain_overview",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "shell_domain_overview" not in hint


@pytest.mark.asyncio
async def test_quality_gate_topic_with_code_no_hint():
    """Topic with a fenced code block should not produce no_code heal_hint."""
    content = (
        "## 概述\n\n"
        "该模块负责令牌校验逻辑。\n\n"
        "## 实现细节\n\n"
        "```java\n"
        "public boolean validateToken(String token) {\n"
        "    return token != null && !token.isBlank();\n"
        "}\n"
        "```\n"
    )
    page = {
        "path": "/__domains__/auth/token-validator",
        "title": "Token Validator",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "topic_no_code" not in hint


@pytest.mark.asyncio
async def test_quality_gate_topic_mermaid_only_triggers_no_code():
    """Topic with only mermaid diagram blocks should produce topic_no_code heal_hint."""
    content = (
        "## 概述\n\n"
        "该模块负责订单状态流转，核心流程如下。\n\n"
        "## 流程图\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "    A[创建订单] --> B[支付]\n"
        "    B --> C[发货]\n"
        "```\n"
    )
    page = {
        "path": "/__domains__/order/status-flow",
        "title": "Order Status Flow",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "topic_no_code: topic has no code examples" in hint
    assert page["path"] in result["pages_to_heal"]


@pytest.mark.asyncio
async def test_quality_gate_topic_with_java_and_mermaid_no_hint():
    """Topic with both java and mermaid blocks should not produce topic_no_code heal_hint."""
    content = (
        "## 概述\n\n"
        "该模块负责订单状态流转。\n\n"
        "## 实现\n\n"
        "```java\n"
        "public void updateStatus(Order order) {\n"
        "    order.setStatus(Status.SHIPPED);\n"
        "}\n"
        "```\n\n"
        "## 流程图\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "    A --> B\n"
        "```\n"
    )
    page = {
        "path": "/__domains__/order/status-update",
        "title": "Order Status Update",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "topic_no_code" not in hint


@pytest.mark.asyncio
async def test_content_issues_blocked_when_heal_cycles_exhausted():
    """Pages with content_issues should not heal when heal_cycles >= max_retries."""
    content = (
        "## 概述\n\n"
        "该模块负责处理用户认证与授权流程，并与下游服务协同完成业务处理。"
        "核心职责包括会话管理、权限校验和令牌刷新。"
        "\n\n## 关键组件\n\n"
        "AuthService 协调认证流程，TokenValidator 校验访问令牌。"
    )
    page = {
        "path": "/__domains__/auth/token-flow",
        "title": "Token Flow",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {page["path"]: 2},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "topic_no_code" in hint
    assert page["path"] not in result["pages_to_heal"]


@pytest.mark.asyncio
async def test_content_issues_healed_when_cycles_available():
    """Pages with content_issues should heal when heal_cycles < max_retries."""
    content = (
        "## 概述\n\n"
        "该模块负责处理用户认证与授权流程，并与下游服务协同完成业务处理。"
        "核心职责包括会话管理、权限校验和令牌刷新。"
        "\n\n## 关键组件\n\n"
        "AuthService 协调认证流程，TokenValidator 校验访问令牌。"
    )
    page = {
        "path": "/__domains__/auth/token-flow",
        "title": "Token Flow",
        "page_type": "topic",
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {},
    }
    state = {
        "pages": [page],
        "heal_attempts": {},
        "heal_cycles": {page["path"]: 0},
        "config": {"importance_tiers": {}, "quality_levels": ["L1", "L2"]},
        "_structural_check_cache": {},
    }

    mock_eval = MagicMock()
    mock_eval.structural_check.return_value = MagicMock(overall=0.9, issues=[])
    mock_eval.bench_score.return_value = MagicMock(overall=0.85)
    wiki_cfg = _mock_wiki_settings()

    patches = _quality_gate_patches(mock_eval, wiki_cfg)
    with patches[0], patches[1], patches[2]:
        result = await quality_gate_node(state, {"configurable": {}})

    hint = result["heal_hints"].get(page["path"], "")
    assert "topic_no_code" in hint
    assert page["path"] in result["pages_to_heal"]
