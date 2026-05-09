import pytest
from unittest.mock import AsyncMock
from wiki.parent_synthesizer import ParentSynthesizer
from wiki.models.module_tree import ModuleNode


@pytest.mark.asyncio
async def test_synthesize_produces_markdown_with_child_links():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = "# Auth Module\n\nThis module handles authentication.\n\n## Sub-modules\n- Login\n- Register"

    synth = ParentSynthesizer(llm=mock_llm)
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=["u1", "u2"],
        file_paths=["src/auth/login.py", "src/auth/register.py"],
        title="认证模块",
        children=[
            ModuleNode(
                canonical_key="src-auth-login",
                entity_uids=["u1"],
                file_paths=["src/auth/login.py"],
                title="登录",
            ),
            ModuleNode(
                canonical_key="src-auth-register",
                entity_uids=["u2"],
                file_paths=["src/auth/register.py"],
                title="注册",
            ),
        ],
    )
    child_contents = ["# Login\nHandles user login.", "# Register\nHandles user registration."]
    result = await synth.synthesize(parent, child_contents)
    assert result  # non-empty
    assert mock_llm.agenerate.called


@pytest.mark.asyncio
async def test_synthesize_includes_child_info_in_prompt():
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = "# Overview"

    synth = ParentSynthesizer(llm=mock_llm)
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=[],
        file_paths=[],
        title="认证模块",
        children=[],
    )
    await synth.synthesize(parent, ["child doc 1"])
    call_args = mock_llm.agenerate.call_args
    prompt = str(call_args)
    assert "child doc 1" in prompt or "认证模块" in prompt


@pytest.mark.asyncio
async def test_synthesize_fallback_on_llm_error():
    mock_llm = AsyncMock()
    mock_llm.agenerate.side_effect = Exception("LLM error")

    synth = ParentSynthesizer(llm=mock_llm)
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=[],
        file_paths=[],
        title="认证模块",
        children=[
            ModuleNode(
                canonical_key="src-auth-login",
                entity_uids=["u1"],
                file_paths=["src/auth/login.py"],
                title="登录",
            ),
        ],
    )
    result = await synth.synthesize(parent, ["child doc"])
    assert "认证模块" in result
    assert "src-auth-login" in result
