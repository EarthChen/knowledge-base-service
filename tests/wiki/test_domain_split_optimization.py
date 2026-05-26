from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.config import AppWikiFlags, Settings, get_settings


class TestDomainSplitOptimization:
    def test_wiki_flags_has_split_threshold(self) -> None:
        s = Settings(_env_file=None)
        assert hasattr(s.wiki, "domain_split_threshold")
        assert s.wiki.domain_split_threshold == 20

    def test_wiki_flags_has_split_max_depth(self) -> None:
        s = Settings(_env_file=None)
        assert hasattr(s.wiki, "domain_split_max_depth")
        assert s.wiki.domain_split_max_depth == 2

    def test_split_threshold_configurable_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WIKI__DOMAIN_SPLIT_THRESHOLD", "25")
        get_settings.cache_clear()
        s = Settings(_env_file=None)
        assert s.wiki.domain_split_threshold == 25

    def test_maybe_split_skipped_after_topic_split(self) -> None:
        from wiki.domain_doc_agent import DomainDocAgent, MAX_PAGE_TOKENS

        agent = DomainDocAgent(
            domain_name="test",
            domain_display_name="测试",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )
        agent._topic_split_done = True
        # Large enough to normally trigger ## split, but below 30000 char safety valve
        section_body = "x" * 10000
        content = f"# Title\n## Section 1\n{section_body}\n## Section 2\n{section_body}"
        assert len(content) < 30000
        assert len(content) // 4 > MAX_PAGE_TOKENS

        pages = agent._maybe_split(content)
        assert len(pages) == 1
        assert pages[0]["page_type"] == "domain_overview"

    def test_maybe_split_still_works_for_huge_content(self) -> None:
        from wiki.domain_doc_agent import DomainDocAgent, MAX_PAGE_TOKENS

        agent = DomainDocAgent(
            domain_name="test",
            domain_display_name="测试",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )
        agent._topic_split_done = True
        section_body = "x" * (MAX_PAGE_TOKENS * 4 + 100)
        content = f"# Title\n## Section 1\n{section_body}\n## Section 2\n{section_body}"
        # Pad to exceed 30000 char safety valve
        content += "y" * (30000 - len(content) + 1)
        assert len(content) >= 30000

        pages = agent._maybe_split(content)
        assert len(pages) > 1
