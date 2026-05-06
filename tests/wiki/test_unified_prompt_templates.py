from __future__ import annotations

from wiki.content_context_builder import (
    CallChainStep,
    EntityDetail,
    EnrichedDomainContext,
    MethodDetail,
)
from wiki.unified_prompt_templates import (
    UNIFIED_WIKI_SYSTEM_PROMPT,
    build_call_chain_section,
    build_data_model_section,
    build_domain_overview_prompt,
    build_entity_section,
    build_enum_constants_section,
    build_topic_detail_prompt,
)


def test_build_entity_section_includes_methods_and_repo():
    ent = EntityDetail(
        uid="u1",
        name="OrderSvc",
        repository="acme/order",
        file_path="svc/order.py",
        entity_type="Module",
        business_summary="处理下单。",
        methods=[
            MethodDetail(
                name="create_order",
                signature="def create_order(self, req: OrderReq) -> Order",
                file_path="svc/order.py",
                start_line=42,
                repository="acme/order",
                docstring="创建订单",
                module_name="OrderSvc",
            ),
        ],
    )
    text = build_entity_section([ent])
    assert "OrderSvc" in text
    assert "create_order" in text
    assert "acme/order" in text
    assert "source://" in text
    assert "svc/order.py:42" in text


def test_build_call_chain_section():
    intra = [
        CallChainStep(
            caller="A",
            callee="B",
            caller_method="a_m",
            callee_method="b_m",
            relationship="CALLS",
        ),
    ]
    cross = [
        CallChainStep(
            caller="B",
            callee="Ext",
            caller_method="",
            callee_method="ext_hook",
            relationship="CALLS",
        ),
    ]
    text = build_call_chain_section(intra, cross)
    assert "域内调用链" in text
    assert "跨域调用链" in text
    assert "`A`" in text and "`B`" in text
    assert "`Ext`" in text


def test_build_domain_overview_prompt_has_required_sections():
    ctx = EnrichedDomainContext(
        domain_name="支付域",
        parent_domain="交易",
        sub_topics=[{"name": "清结算", "description": "对账与清算", "entity_count": 3}],
    )
    p = build_domain_overview_prompt(ctx)
    for needle in (
        "## 你必须在 JSON 的 content 中输出",
        "## 业务概述",
        "## 架构全景图",
        "## 子主题导航",
        "## 关键入口",
        "## 跨域依赖与交互",
        "支付域",
        "清结算",
    ):
        assert needle in p


def test_build_topic_detail_prompt_has_required_sections():
    ctx = EnrichedDomainContext(domain_name="库存", parent_domain="供应链")
    p = build_topic_detail_prompt(ctx)
    for needle in (
        "## 业务概述",
        "## 核心业务流程",
        "sequenceDiagram",
        "## 核心服务详解",
        "## 数据模型",
        "## 设计要点与注意事项",
    ):
        assert needle in p


def test_unified_system_prompt_contains_constraints():
    s = UNIFIED_WIKI_SYSTEM_PROMPT
    assert "source://" in s
    assert "Mermaid" in s
    assert "JSON" in s
    assert "executive_summary" in s
    assert "框架" in s or "科普" in s
    assert "禁止" in s


def test_topic_detail_prompt_includes_existing_wiki_context():
    ctx = EnrichedDomainContext(
        domain_name="库存",
        parent_domain="供应链",
        existing_wiki_context="- **旧页**: 既有摘要内容。",
    )
    p = build_topic_detail_prompt(ctx)
    assert "已有 Wiki 摘要" in p
    assert "既有摘要内容" in p


def test_build_data_model_section():
    text = build_data_model_section([
        {"uid": "x", "name": "UserDTO", "type": "DTO", "fields": ["id: str", "name: str"]},
    ])
    assert "UserDTO" in text
    assert "id: str" in text


def test_build_enum_constants_section():
    text = build_enum_constants_section([
        {"name": "PayStatus", "file": "enums.py", "labels": ["Enum"]},
    ])
    assert "PayStatus" in text
    assert "enums.py" in text
