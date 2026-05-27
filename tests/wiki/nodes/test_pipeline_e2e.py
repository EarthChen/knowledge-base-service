"""End-to-end integration tests for wiki pipeline node sequences."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent
from wiki.nodes.finalize import finalize_node
from wiki.nodes.quality_gate import quality_gate_node
from wiki.output_guardrail import SensitiveContentCheck

_SKELETON_BANNER_ZH = "> ⚠️ 本域文档待完善，内容可能不完整。"


def _topic_page(
    *,
    path: str = "/wiki/low-cn-topic",
    content: str,
    content_language: str = "简体中文",
) -> dict:
    return {
        "path": path,
        "title": "Low CN Topic",
        "page_type": "topic",
        "content_language": content_language,
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {"node_count": 0, "edge_count": 0},
    }


def _passing_structure_content(*, english_body: str) -> str:
    return (
        "## Overview\n"
        f"{english_body}\n"
        "## Key components\n"
        "Core module handles requests.\n"
        "## Relationships\n"
        "- [[peer-module]]\n"
    )


@pytest.fixture
def mock_wiki_settings(monkeypatch):
    """Shared wiki thresholds for quality_gate and finalize nodes."""
    mock_cfg = MagicMock()
    mock_cfg.wiki.overview_min_content_chars = 2000
    mock_cfg.wiki.topic_min_content_chars = 1000
    mock_cfg.wiki.topic_min_publish_chars = 0
    mock_cfg.wiki.cn_ratio_hard_min = 0.4
    mock_cfg.wiki.language_guardrail_cn_ratio = 0.15
    mock_cfg.wiki.heal_l2_threshold = 0.0
    mock_cfg.wiki.heal_on_l3_failure = False
    mock_cfg.wiki.heal_l3_threshold = 0.5
    monkeypatch.setattr("wiki.nodes.quality_gate.get_settings", lambda: mock_cfg)
    monkeypatch.setattr("core.config.get_settings", lambda: mock_cfg)
    return mock_cfg


@pytest.mark.asyncio
async def test_e2e_topic_page_cn_ratio_triggers_heal(mock_wiki_settings):
    """English-dominant topic with Chinese content_language enters heal with cn_ratio reason."""
    english_body = (
        "This service layer coordinates authentication and authorization across modules. "
        * 30
    )
    page = _topic_page(content=_passing_structure_content(english_body=english_body))
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

    with (
        patch("wiki.nodes.quality_gate.WikiQualityEvaluator", lambda: mock_eval),
        patch(
            "wiki.nodes.quality_gate.verify_citations",
            lambda content, names: MagicMock(invalid_count=0),
        ),
    ):
        result = await quality_gate_node(state, {"configurable": {}})

    assert page["path"] in result.get("pages_to_heal", [])
    heal_reason = (page.get("metadata") or {}).get("heal_reason", "")
    assert "cn_ratio" in heal_reason


@pytest.mark.asyncio
async def test_e2e_finalize_redacts_sensitive_content(mock_wiki_settings):
    """Finalize sanitizes internal URLs and credential patterns from published content."""
    sensitive = (
        "# Deploy\n\n"
        "Health check at http://10.0.0.5:3000/health before release.\n"
        "Configure password: supersecret and secret=mytoken here.\n"
    )
    state = {
        "pages": [
            {
                "title": "Deploy Guide",
                "path": "/__domains__/ops/topics/deploy",
                "page_type": "topic",
                "content": sensitive,
            }
        ]
    }
    result = await finalize_node(state)
    content = result["pages"][0]["content"]
    assert "[INTERNAL_URL]" in content
    assert "10.0.0.5" not in content
    assert "supersecret" not in content
    assert "mytoken" not in content
    assert "[REDACTED]" in content


@pytest.mark.asyncio
async def test_e2e_finalize_preserves_case_insensitive_wikilinks(mock_wiki_settings):
    """Valid wikilinks survive finalize when target title casing differs."""
    pages = [
        {
            "title": "Invoicing",
            "path": "/__domains__/billing/topics/Invoicing.md",
            "business_domain": "billing",
            "page_type": "topic",
            "content": "# Invoicing\n\nCore billing flow.",
        },
        {
            "title": "Payments",
            "path": "/__domains__/billing/topics/Payments.md",
            "business_domain": "billing",
            "page_type": "topic",
            "content": "See [[invoicing]] and [[billing/INVOICING]] for details.",
        },
    ]
    result = await finalize_node({"pages": pages})
    payments_content = result["pages"][1]["content"]
    assert "[[invoicing]]" in payments_content
    assert "[[billing/INVOICING]]" in payments_content


@pytest.mark.asyncio
async def test_e2e_quality_gate_skeleton_banner_by_page_type(mock_wiki_settings):
    """Short topic and overview pages get skeleton banners at type-specific thresholds."""
    topic_content = "# Short Topic\n\n" + ("Brief English topic body. " * 25)
    overview_content = "# Short Overview\n\n" + ("Overview section text. " * 60)

    state = {
        "pages": [
            {
                "title": "Short Topic",
                "path": "/__domains__/test/topics/short-topic",
                "page_type": "topic",
                "content": topic_content,
            },
            {
                "title": "Short Overview",
                "path": "/__domains__/test/_overview",
                "page_type": "domain_overview",
                "content": overview_content,
            },
        ]
    }

    assert len(topic_content) < mock_wiki_settings.wiki.topic_min_content_chars
    assert len(overview_content) < mock_wiki_settings.wiki.overview_min_content_chars

    result = await finalize_node(state)
    topic_page = next(p for p in result["pages"] if p["page_type"] == "topic")
    overview_page = next(p for p in result["pages"] if p["page_type"] == "domain_overview")

    assert topic_page["content"].startswith(_SKELETON_BANNER_ZH)
    assert overview_page["content"].startswith(_SKELETON_BANNER_ZH)


@pytest.mark.asyncio
async def test_e2e_guardrail_chain_includes_sensitive_check():
    """Domain doc agent guardrail chain includes SensitiveContentCheck and flags credentials."""
    agent = DomainDocAgent(
        domain_name="test-domain",
        llm=MagicMock(),
        graph_store=MagicMock(),
    )
    chain = agent._output_guardrail
    assert any(isinstance(c, SensitiveContentCheck) for c in chain._checks)

    content = (
        "# Config\n\n"
        "Set api_key=sk-live-abc123 in production.\n\n"
        + "Supporting detail paragraph. " * 80
    )
    result = await chain.evaluate(content, {})
    assert not result.passed
    assert "sensitive_content" in result.details
    assert not result.details["sensitive_content"].passed
    assert "Sensitive patterns" in result.details["sensitive_content"].issues[0]
