"""Tests for mechanical Part N topic naming elimination (T2-8)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiki.domain_doc_agent import (
    DomainTopicOutline,
    OutlineTopicItem,
    _is_mechanical_topic_name,
    _rename_mechanical_topic_title,
    _validate_topic_plan_outline,
)


def test_is_mechanical_topic_name_part_n() -> None:
    assert _is_mechanical_topic_name("Part 1")
    assert _is_mechanical_topic_name("part 2")
    assert _is_mechanical_topic_name("PART 3")


def test_is_mechanical_topic_name_chinese() -> None:
    assert _is_mechanical_topic_name("第1部分")
    assert _is_mechanical_topic_name("第 2 部分")


def test_is_mechanical_topic_name_descriptive_not_mechanical() -> None:
    assert not _is_mechanical_topic_name("Authentication Architecture")
    assert not _is_mechanical_topic_name("Part 2: Payment Flow")


def test_mechanical_topic_name_replaced() -> None:
    renamed = _rename_mechanical_topic_title(
        "Part 1",
        ["PaymentService", "RefundHandler"],
    )
    assert renamed != "Part 1"
    assert "PaymentService" in renamed


def test_descriptive_topic_name_preserved() -> None:
    title = "Payment Gateway Integration"
    assert _rename_mechanical_topic_title(title, ["PaymentService"]) == title


def test_chinese_part_naming_detected_and_renamed() -> None:
    renamed = _rename_mechanical_topic_title("第1部分", ["AuthModule"])
    assert renamed == "AuthModule"


def test_validate_topic_plan_renames_pure_part_n_from_modules() -> None:
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            OutlineTopicItem(
                title="Part 1",
                modules=["UserService", "SessionManager"],
                description="",
                slug="user-service",
            ),
        ],
    )
    result = _validate_topic_plan_outline(outline)
    assert result.topics[0].title != "Part 1"
    assert "UserService" in result.topics[0].title


def test_validate_topic_plan_skipped_when_flag_disabled() -> None:
    outline = DomainTopicOutline(
        should_split=True,
        topics=[OutlineTopicItem(title="Part 1", modules=["ModA"], description="", slug="mod-a")],
    )
    mock_wiki = MagicMock()
    mock_wiki.reject_mechanical_topic_names = False

    with patch("wiki.domain_doc_agent.get_settings", return_value=MagicMock(wiki=mock_wiki)):
        result = _validate_topic_plan_outline(outline)

    assert result.topics[0].title == "Part 1"
