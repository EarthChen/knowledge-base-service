from wiki.overview_synthesizer import synthesize_overview_from_children


class TestSynthesizeOverview:
    def test_combines_child_summaries(self):
        children = [
            {"title": "UserAuth", "content": "## 概述\nHandles user login and registration.\n## 核心业务流程\nLogin flow."},
            {"title": "UserProfile", "content": "## 概述\nManages user profiles.\n## 核心业务流程\nProfile CRUD."},
        ]
        result = synthesize_overview_from_children("用户管理", children)
        assert "UserAuth" in result
        assert "UserProfile" in result
        assert "用户管理" in result

    def test_empty_children(self):
        result = synthesize_overview_from_children("空域", [])
        assert "空域" in result
        assert "CONTEXT_GAP" in result

    def test_single_child(self):
        children = [
            {"title": "OnlyChild", "content": "## 概述\nDoes everything.\n## Details\nMore."},
        ]
        result = synthesize_overview_from_children("单子域", children)
        assert "OnlyChild" in result

    def test_extracts_overview_section(self):
        children = [
            {"title": "Module", "content": "## 概述\nThis is the overview.\n## 其他\nIgnored."},
        ]
        result = synthesize_overview_from_children("测试域", children)
        assert "This is the overview" in result
