import pytest

from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.quality_evaluator import (
    BenchScore,
    DepthScore,
    DiagramScore,
    LinkScore,
    WikiQualityEvaluator,
)


@pytest.fixture
def evaluator():
    return WikiQualityEvaluator()


@pytest.fixture
def rich_page():
    """高质量页面：丰富内容、图表、链接。"""
    return WikiPage(
        title="User Management",
        path="wiki/user-management",
        content=(
            "## 业务概述\n"
            "用户管理模块负责处理用户注册、认证和授权。该模块是系统的核心组件。\n\n"
            "## 核心业务流程\n"
            "```mermaid\nsequenceDiagram\n    participant U as User\n    participant S as Service\n    U->>S: register()\n    S-->>U: token\n```\n\n"
            "## 核心服务详情\n"
            "### UserService\n"
            "处理用户CRUD操作，包括 `createUser()`、`updateUser()` 等方法。\n"
            "调用 [[authentication]] 进行身份验证。\n\n"
            "### AuthService\n"
            "管理JWT令牌生成和验证。提供 `generateToken()` 和 `validateToken()` 接口。\n"
            "参见 [源码](source://UserService.java:45)\n\n"
            "## 数据模型\n"
            "| 类名 | 类型 | 字段 |\n|---|---|---|\n| UserDTO | DTO | id, name, email |\n\n"
            "## 关联主题\n"
            "相关模块: [[authentication]], [[permission-management]]\n"
        ),
        page_type=PageType.TOPIC,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.fixture
def poor_page():
    """低质量页面：简单内容。"""
    return WikiPage(
        title="Utils",
        path="wiki/utils",
        content="## Overview\nUtility functions.\n",
        page_type=PageType.TOPIC,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


class TestContentDepthCheck:
    def test_rich_content_high_depth(self, evaluator, rich_page):
        score = evaluator.content_depth_check(rich_page)
        assert isinstance(score, DepthScore)
        assert score.avg_section_length > 50
        assert score.technical_density > 0.0
        assert score.overall > 0.6

    def test_poor_content_low_depth(self, evaluator, poor_page):
        score = evaluator.content_depth_check(poor_page)
        assert score.overall < 0.4


class TestDiagramQualityCheck:
    def test_page_with_valid_mermaid(self, evaluator, rich_page):
        score = evaluator.diagram_quality_check(rich_page)
        assert isinstance(score, DiagramScore)
        assert score.mermaid_block_count >= 1
        assert score.overall > 0.5

    def test_page_without_diagrams(self, evaluator, poor_page):
        score = evaluator.diagram_quality_check(poor_page)
        assert score.mermaid_block_count == 0
        assert score.overall < 0.3


class TestLinkQualityCheck:
    def test_page_with_links(self, evaluator, rich_page):
        score = evaluator.link_quality_check(rich_page)
        assert isinstance(score, LinkScore)
        assert score.wikilink_count >= 2
        assert score.source_ref_count >= 1
        assert score.overall > 0.5

    def test_page_without_links(self, evaluator, poor_page):
        score = evaluator.link_quality_check(poor_page)
        assert score.wikilink_count == 0
        assert score.overall < 0.3


class TestBenchScore:
    def test_overall_bench_score(self, evaluator, rich_page):
        bench = evaluator.bench_score(rich_page)
        assert isinstance(bench, BenchScore)
        assert 0.0 <= bench.overall <= 1.0
        assert bench.structure is not None
        assert bench.depth is not None
        assert bench.diagrams is not None
        assert bench.links is not None

    def test_bench_score_weights(self, evaluator, rich_page):
        bench = evaluator.bench_score(rich_page)
        expected = (
            bench.structure.overall * 0.25
            + bench.depth.overall * 0.35
            + bench.diagrams.overall * 0.2
            + bench.links.overall * 0.2
        )
        assert abs(bench.overall - expected) < 0.01


class TestBuildHealHint:
    def test_heal_hint_includes_all_dimensions(self, evaluator, poor_page):
        bench = evaluator.bench_score(poor_page)
        hint = evaluator.build_heal_prompt_hint_v2(bench)
        assert isinstance(hint, str)
        assert len(hint) > 20
