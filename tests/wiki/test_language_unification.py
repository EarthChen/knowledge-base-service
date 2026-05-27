from __future__ import annotations

from unittest.mock import MagicMock


class TestContentLanguage:
    def test_from_any_zh_cn(self):
        from core.config import ContentLanguage

        assert ContentLanguage.from_any("zh-CN") == ContentLanguage.ZH_CN

    def test_from_any_chinese_label(self):
        from core.config import ContentLanguage

        assert ContentLanguage.from_any("简体中文") == ContentLanguage.ZH_CN

    def test_from_any_zh(self):
        from core.config import ContentLanguage

        assert ContentLanguage.from_any("zh") == ContentLanguage.ZH_CN

    def test_from_any_en(self):
        from core.config import ContentLanguage

        assert ContentLanguage.from_any("en") == ContentLanguage.EN

    def test_from_any_empty_defaults_en(self):
        from core.config import ContentLanguage

        assert ContentLanguage.from_any("") == ContentLanguage.EN

    def test_display_label_chinese(self):
        from core.config import ContentLanguage

        assert ContentLanguage.ZH_CN.display_label == "简体中文"

    def test_display_label_english(self):
        from core.config import ContentLanguage

        assert ContentLanguage.EN.display_label == "English"

    def test_is_chinese(self):
        from core.config import ContentLanguage

        assert ContentLanguage.ZH_CN.is_chinese is True
        assert ContentLanguage.EN.is_chinese is False


class TestPipelineLanguageInjection:
    def test_build_initial_state_language_zh_cn(self):
        from core.config import ContentLanguage
        from wiki.pipeline_orchestrator import _build_initial_state_language

        cl = _build_initial_state_language({"language": "zh-CN"})
        assert cl == ContentLanguage.ZH_CN

    def test_build_initial_state_language_default(self):
        from core.config import ContentLanguage
        from wiki.pipeline_orchestrator import _build_initial_state_language

        cl = _build_initial_state_language({})
        assert cl == ContentLanguage.ZH_CN

    def test_build_initial_state_language_en(self):
        from core.config import ContentLanguage
        from wiki.pipeline_orchestrator import _build_initial_state_language

        cl = _build_initial_state_language({"language": "en"})
        assert cl == ContentLanguage.EN


class TestComposeLanguageResolution:
    def test_reads_content_language_from_state(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _resolve_content_language_for_compose

        state = {"content_language": ContentLanguage.ZH_CN}
        result = _resolve_content_language_for_compose(state, None)
        assert isinstance(result, ContentLanguage)
        assert result == ContentLanguage.ZH_CN

    def test_falls_back_to_state_language(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _resolve_content_language_for_compose

        state = {"language": "zh-CN"}
        result = _resolve_content_language_for_compose(state, None)
        assert isinstance(result, ContentLanguage)
        assert result == ContentLanguage.ZH_CN

    def test_falls_back_to_en(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _resolve_content_language_for_compose

        state = {"language": "en"}
        result = _resolve_content_language_for_compose(state, None)
        assert result == ContentLanguage.EN


class TestLanguageUnification:
    def test_domain_doc_agent_accepts_content_language(self):
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent(
            domain_name="test-domain",
            domain_display_name="测试域",
            llm=MagicMock(),
            graph_store=MagicMock(),
            content_language="简体中文",
        )
        assert agent.content_language == "简体中文"

    def test_domain_doc_agent_defaults_to_chinese(self):
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent(
            domain_name="test-domain",
            domain_display_name="测试域",
            llm=MagicMock(),
            graph_store=MagicMock(),
        )
        assert agent.content_language == "简体中文"

    def test_topic_planner_prompt_includes_language(self):
        from wiki.agent_prompts import get_topic_planner_prompt

        prompt = get_topic_planner_prompt(language="简体中文")
        assert "中文" in prompt
        assert "topic titles" in prompt.lower() or "标题" in prompt

    def test_topic_planner_prompt_no_family_biased_example(self):
        """Topic planner examples must not bias toward 家族 terminology."""
        from wiki.agent_prompts import SYSTEM_TOPIC_PLANNER, get_topic_planner_prompt

        assert "家族任务系统" not in SYSTEM_TOPIC_PLANNER
        prompt = get_topic_planner_prompt(language="简体中文")
        assert "家族任务系统" not in prompt
        assert "用户等级体系" in prompt or "送礼订单处理" in prompt

    def test_write_system_prompt_includes_chinese_sections(self):
        from wiki.agent_prompts import get_write_system_prompt

        prompt = get_write_system_prompt(language="简体中文")
        assert "概述" in prompt
        assert "核心业务流程" in prompt


class TestDiagramLanguage:
    def test_chinese_heading(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _inject_dependency_diagram

        content = "# Title\n\nSome text."
        result = _inject_dependency_diagram(content, ["A", "B"], language=ContentLanguage.ZH_CN)
        assert "## 架构" in result
        assert "## Architecture" not in result

    def test_english_heading(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _inject_dependency_diagram

        content = "# Title\n\nSome text."
        result = _inject_dependency_diagram(content, ["A", "B"], language=ContentLanguage.EN)
        assert "## Architecture" in result

    def test_no_language_defaults_english(self):
        from wiki.nodes.domain_compose import _inject_dependency_diagram

        content = "# Title\n\nSome text."
        result = _inject_dependency_diagram(content, ["A", "B"])
        assert "## Architecture" in result


class TestLayerSummaryLanguage:
    def test_chinese_prefix(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _build_layer_summary

        layers = {"ModA": {"layer": "api"}}
        result = _build_layer_summary(["ModA"], layers, language=ContentLanguage.ZH_CN)
        assert "本域架构层" in result

    def test_english_prefix(self):
        from core.config import ContentLanguage
        from wiki.nodes.domain_compose import _build_layer_summary

        layers = {"ModA": {"layer": "api"}}
        result = _build_layer_summary(["ModA"], layers, language=ContentLanguage.EN)
        assert "Architecture layers" in result


class TestMaybeSplitLanguage:
    def test_chinese_nav_heading(self):
        from core.config import ContentLanguage
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n" + "\n".join(f"## Section {i}\n\n{'x' * 6000}" for i in range(5))
        pages = _maybe_split(long_content, "test-domain", "Test", language=ContentLanguage.ZH_CN)
        overview = pages[0]["content"]
        assert "章节导航" in overview

    def test_english_nav_heading(self):
        from core.config import ContentLanguage
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n" + "\n".join(f"## Section {i}\n\n{'x' * 6000}" for i in range(5))
        pages = _maybe_split(long_content, "test-domain", "Test", language=ContentLanguage.EN)
        overview = pages[0]["content"]
        assert "Section Navigation" in overview

    def test_english_fallback_title(self):
        from core.config import ContentLanguage
        from wiki.domain_doc_agent import _maybe_split

        long_content = "# Title\n\n## \n\n" + "x" * 25000
        pages = _maybe_split(long_content, "test-domain", "Test", language=ContentLanguage.EN)
        topic_pages = [p for p in pages if p.get("page_type") == "topic"]
        if topic_pages:
            assert any("Untitled" in p.get("title", "") for p in topic_pages)
