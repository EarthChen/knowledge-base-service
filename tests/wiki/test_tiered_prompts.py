import pytest
from wiki.tiered_prompts import TieredPromptBuilder

def test_build_enrichment_prompt_en():
    builder = TieredPromptBuilder()
    prompt = builder.build_enrichment_prompt(
        page_content="# UserService\n\n## Overview\nHandles user operations.",
        entity_name="UserService",
        entity_label="Class",
        language="en",
    )
    assert "UserService" in prompt
    assert "business flow" in prompt.lower() or "design pattern" in prompt.lower()
    assert len(prompt) > 100

def test_build_enrichment_prompt_zh():
    builder = TieredPromptBuilder()
    prompt = builder.build_enrichment_prompt(
        page_content="# UserService\n\n## 概述\n处理用户操作。",
        entity_name="UserService",
        entity_label="Class",
        language="zh",
    )
    assert "UserService" in prompt
    assert "业务" in prompt or "设计" in prompt

def test_build_encyclopedia_prompt_en():
    builder = TieredPromptBuilder()
    prompt = builder.build_encyclopedia_prompt(
        page_content="# UserService\n\n## Overview\nHandles user operations.\n\n## Business Flow\n...",
        entity_name="UserService",
        entity_label="Class",
        language="en",
    )
    assert "UserService" in prompt
    assert "example" in prompt.lower() or "faq" in prompt.lower()
    assert len(prompt) > 100

def test_build_encyclopedia_prompt_zh():
    builder = TieredPromptBuilder()
    prompt = builder.build_encyclopedia_prompt(
        page_content="# UserService\n\n## 概述\n处理用户操作。",
        entity_name="UserService",
        entity_label="Class",
        language="zh",
    )
    assert "UserService" in prompt
    assert "示例" in prompt or "FAQ" in prompt

def test_unknown_language_defaults_to_en():
    builder = TieredPromptBuilder()
    prompt = builder.build_enrichment_prompt(
        page_content="# Test",
        entity_name="Test",
        entity_label="Class",
        language="fr",
    )
    assert "business flow" in prompt.lower() or "design pattern" in prompt.lower()

def test_enrichment_system_prompt_en():
    builder = TieredPromptBuilder()
    system = builder.enrichment_system_prompt("en")
    assert "architect" in system.lower() or "documentation" in system.lower()

def test_enrichment_system_prompt_zh():
    builder = TieredPromptBuilder()
    system = builder.enrichment_system_prompt("zh")
    assert "架构" in system or "文档" in system

def test_encyclopedia_system_prompt_en():
    builder = TieredPromptBuilder()
    system = builder.encyclopedia_system_prompt("en")
    assert "encyclopedia" in system.lower() or "documentation" in system.lower()

def test_encyclopedia_system_prompt_zh():
    builder = TieredPromptBuilder()
    system = builder.encyclopedia_system_prompt("zh")
    assert "百科" in system or "文档" in system
