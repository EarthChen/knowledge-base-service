"""Tests for DomainSummaryCard extraction."""
import pytest


class TestDomainSummaryCache:
    def test_extract_card_basic(self):
        from wiki.domain_summary_cache import extract_summary_card
        content = """## 概述
UserService 负责用户注册和登录认证，是系统的核心入口。

## 核心业务流程
用户通过 API 调用 UserService 进行注册。
"""
        card = extract_summary_card("UserAuth", ["UserService", "AuthHelper"], content)
        assert card.domain_name == "UserAuth"
        assert card.module_names == ["UserService", "AuthHelper"]
        assert "用户注册" in card.responsibilities
        assert card.content_hash != ""

    def test_extract_card_no_overview(self):
        from wiki.domain_summary_cache import extract_summary_card
        content = "Some content without overview section."
        card = extract_summary_card("Domain1", ["Mod1"], content)
        assert card.responsibilities == ""

    def test_extract_card_entry_points(self):
        from wiki.domain_summary_cache import extract_summary_card
        card_modules = ["EntryMod", "HelperMod", "UtilMod", "ExtraMod"]
        content = "## 概述\nSome overview."
        card = extract_summary_card("Dom", card_modules, content)
        assert len(card.entry_points) <= 3

    def test_card_content_hash_changes_with_content(self):
        from wiki.domain_summary_cache import extract_summary_card
        card1 = extract_summary_card("D", ["M"], "## 概述\nVersion 1")
        card2 = extract_summary_card("D", ["M"], "## 概述\nVersion 2")
        assert card1.content_hash != card2.content_hash
