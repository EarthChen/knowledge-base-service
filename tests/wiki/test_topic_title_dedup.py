from __future__ import annotations

import pytest

from wiki.domain_doc_agent import TopicPlan, _dedup_topic_titles, _extract_cjk_bigrams


class TestExtractCjkBigrams:
    def test_chinese_title(self):
        result = _extract_cjk_bigrams("核心模块管理")
        assert "核心" in result
        assert "心模" in result
        assert "模块" in result

    def test_english_title_empty(self):
        result = _extract_cjk_bigrams("Authentication Service")
        assert result == set()

    def test_single_char(self):
        result = _extract_cjk_bigrams("域")
        assert result == {"域"}


class TestSemanticDedup:
    def test_exact_match_dedup(self):
        topics = [
            TopicPlan(title="核心模块", modules=["A"]),
            TopicPlan(title="核心模块", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 1
        assert set(result[0].modules) == {"A", "B"}

    def test_cjk_bigram_overlap_dedup(self):
        topics = [
            TopicPlan(title="核心模块管理", modules=["A"]),
            TopicPlan(title="核心模块配置", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 1
        assert set(result[0].modules) == {"A", "B"}

    def test_no_false_positive(self):
        topics = [
            TopicPlan(title="用户认证服务", modules=["A"]),
            TopicPlan(title="数据存储层", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 2

    def test_english_titles_no_bigram_dedup(self):
        topics = [
            TopicPlan(title="Authentication", modules=["A"]),
            TopicPlan(title="Authorization", modules=["B"]),
        ]
        result = _dedup_topic_titles(topics)
        assert len(result) == 2

    def test_preserves_first_title(self):
        topics = [
            TopicPlan(title="核心模块管理", modules=["A"], description="desc1"),
            TopicPlan(title="核心模块配置", modules=["B"], description="desc2"),
        ]
        result = _dedup_topic_titles(topics)
        assert result[0].title == "核心模块管理"
        assert result[0].description == "desc1"


class TestMaybeSplitTopicCap:
    def test_max_8_topics(self):
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n" + "\n".join(f"## Section {i}\n\n{'x' * 6000}" for i in range(12))
        pages = _maybe_split(long_content, "test-domain", "Test")
        topic_pages = [p for p in pages if p.get("page_type") == "topic"]
        assert len(topic_pages) <= 8

    def test_small_content_no_cap(self):
        from wiki.domain_doc_agent import _maybe_split

        content = "# Title\n\n## A\n\nshort content\n\n## B\n\nshort content"
        pages = _maybe_split(content, "test-domain", "Test")
        # Short content, no split needed
        assert len(pages) == 1


class TestTopicCanonicalKey:
    @pytest.mark.asyncio
    async def test_topic_page_has_canonical_key(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from wiki.domain_doc_agent import DomainDocAgent, DomainTopicOutline, TopicPlan
        from wiki.page_agent import WorkingMemory

        mock_llm = MagicMock()
        mock_graph = MagicMock()
        with patch("core.config.get_settings") as mock_settings:
            wiki_cfg = MagicMock()
            wiki_cfg.domain_agent_explore_max_rounds = 2
            wiki_cfg.domain_agent_explore_max_tool_calls = 5
            mock_settings.return_value.wiki = wiki_cfg
            agent = DomainDocAgent("test-domain", mock_llm, mock_graph, domain_display_name="Test Domain")

        agent._page_agent = MagicMock()
        agent._page_agent.write = AsyncMock(return_value="# Topic\n\nContent here.")
        agent._verify_code_blocks = AsyncMock(side_effect=lambda c, m: c)

        memory = WorkingMemory()
        outline = DomainTopicOutline(
            should_split=True,
            topics=[
                TopicPlan(title="TopicA", modules=["mod1"], description="desc"),
                TopicPlan(title="TopicB", modules=["mod2"], description="desc"),
            ],
        )
        pages = await agent._write_with_outline(outline, "baseline", memory, ["mod1", "mod2"])
        topic_pages = [p for p in pages if p.get("page_type") == "topic"]
        assert len(topic_pages) == 2
        assert all(p.get("canonical_key") == "test-domain" for p in topic_pages)
