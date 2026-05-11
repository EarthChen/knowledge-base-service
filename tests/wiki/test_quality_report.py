"""Tests for wiki.quality_report — programmatic wiki quality evaluation."""
import pytest

from wiki.quality_report import QualityReport, evaluate_quality


class TestEvaluateQuality:
    def test_full_coverage(self):
        content = "## 概述\nUserController 负责用户管理。UserService 处理业务逻辑。UserRepository 访问数据。"
        modules = ["UserController", "UserService", "UserRepository"]
        report = evaluate_quality(content, modules)
        assert report.coverage == 1.0

    def test_partial_coverage(self):
        content = "## 概述\nUserController 负责用户管理。"
        modules = ["UserController", "UserService", "UserRepository"]
        report = evaluate_quality(content, modules)
        assert abs(report.coverage - 1 / 3) < 0.01

    def test_citation_density_with_source_links(self):
        content = (
            "## 关键实现\n"
            "```java\npublic void save() {}\n```\n"
            "参见 source://repo/src/User.java:10\n"
            "另一个 source://repo/src/Service.java:20\n"
        )
        modules = ["UserService"]
        report = evaluate_quality(content, modules)
        # 2 source links + 1 code block = 3 citations / 1 module = 3.0
        assert report.citation_density >= 2.0

    def test_context_gap_count(self):
        content = (
            "## 概述\n正常内容\n"
            "<!-- CONTEXT_GAP: 缺少调用链 -->\n"
            "## 流程\n"
            "<!-- CONTEXT_GAP: 缺少实现细节 -->\n"
        )
        report = evaluate_quality(content, ["Mod1"])
        assert report.context_gap_count == 2

    def test_uncovered_modules(self):
        content = "## 概述\nUserController 是入口。"
        modules = ["UserController", "UserService", "UserRepository"]
        report = evaluate_quality(content, modules)
        assert set(report.uncovered_modules) == {"UserService", "UserRepository"}

    def test_visual_aids_count(self):
        content = (
            "## 架构\n"
            "```mermaid\nflowchart TD\nA-->B\n```\n"
            "## 流程\n"
            "```mermaid\nsequenceDiagram\nA->>B: call\n```\n"
        )
        report = evaluate_quality(content, ["A"])
        assert report.visual_aids_count == 2

    def test_empty_content(self):
        report = evaluate_quality("", ["Mod1", "Mod2"])
        assert report.coverage == 0.0
        assert report.citation_density == 0.0

    def test_is_acceptable(self):
        content = "UserService 处理用户。source://r/f:1\n```java\ncode\n```\n"
        report = evaluate_quality(content, ["UserService"])
        assert report.is_acceptable is True

    def test_not_acceptable_low_coverage(self):
        content = "只提到了 A。"
        report = evaluate_quality(content, ["A", "B", "C", "D", "E"])
        assert report.is_acceptable is False
