"""Tests for language concept injection in WikiPageAgent explore prompts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.page_agent import WikiPageAgent


@pytest.mark.asyncio
async def test_explore_prompt_includes_language_concepts() -> None:
    """_build_explore_user_prompt should include language concepts when detectable."""
    mock_llm = MagicMock()
    mock_graph = MagicMock()
    agent = WikiPageAgent(mock_llm, mock_graph)

    java_concepts = [
        "annotations",
        "generics",
        "streams API",
        "Spring dependency injection",
        "lambda expressions",
    ]
    with patch.object(
        agent,
        "_detect_module_languages",
        new=AsyncMock(
            return_value={"java": java_concepts},
        ),
    ):
        prompt = await agent._build_explore_user_prompt(
            module_names=["UserService"],
            domain_name="user-management",
            baseline_context="",
        )

    assert "语言特定概念" in prompt
    assert "annotations" in prompt
    assert "Spring dependency injection" in prompt


@pytest.mark.asyncio
async def test_explore_prompt_omits_concepts_without_graph() -> None:
    """When graph store is unavailable, concepts section should not appear."""
    mock_llm = MagicMock()
    agent = WikiPageAgent(mock_llm, None)

    prompt = await agent._build_explore_user_prompt(
        module_names=["UserService"],
        domain_name="user-management",
        baseline_context="",
    )

    assert "语言特定概念" not in prompt


@pytest.mark.asyncio
async def test_detect_module_languages_uses_batch_query() -> None:
    """_detect_module_languages should query all modules in a single Cypher call."""
    mock_llm = MagicMock()
    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"name": "UserService", "path": "src/UserService.java"},
                {"name": "OrderRepo", "path": "src/OrderRepo.java"},
                {"name": "PayHandler", "path": "src/PayHandler.py"},
            ],
        ),
    )
    agent = WikiPageAgent(mock_llm, mock_graph)
    languages = await agent._detect_module_languages(["UserService", "OrderRepo", "PayHandler"])

    assert mock_graph.execute_query.await_count == 1
    assert "java" in languages
    assert "python" in languages


@pytest.mark.asyncio
async def test_detect_module_languages_from_module_paths() -> None:
    """_detect_module_languages maps module file paths to plugin concepts."""
    mock_llm = MagicMock()
    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"name": "UserService", "path": "src/main/UserService.java"},
                {"name": "OrderRepo", "path": "src/main/OrderRepo.java"},
            ],
        ),
    )
    agent = WikiPageAgent(mock_llm, mock_graph)

    languages = await agent._detect_module_languages(["UserService", "OrderRepo"])

    assert "java" in languages
    assert len(languages["java"]) >= 5
    assert mock_graph.execute_query.await_count == 1
