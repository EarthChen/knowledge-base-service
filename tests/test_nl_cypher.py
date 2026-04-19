"""Tests for NL→Cypher query translator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from query.nl_cypher import (
    GRAPH_SCHEMA_PROMPT,
    CypherValidationError,
    NLCypherService,
)


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock()
    return store


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.complete = AsyncMock()
    return llm


@pytest.mark.asyncio
async def test_nl_cypher_basic_query(mock_store, mock_llm):
    mock_llm.complete.return_value = (
        "MATCH (f:Function) WHERE f.name = 'login' RETURN f.name, f.file LIMIT 10"
    )
    mock_store.execute_query.return_value = MagicMock(
        data=[{"f.name": "login", "f.file": "auth/service.py"}]
    )

    svc = NLCypherService(mock_store, mock_llm)
    result = await svc.query("Find the login function")

    assert result["question"] == "Find the login function"
    assert "MATCH" in result["cypher"]
    assert len(result["results"]) == 1
    assert result["total"] == 1
    assert "error" not in result


@pytest.mark.asyncio
async def test_nl_cypher_extracts_from_markdown_fences(mock_store, mock_llm):
    mock_llm.complete.return_value = "```cypher\nMATCH (c:Class) RETURN c.name LIMIT 5\n```"
    mock_store.execute_query.return_value = MagicMock(data=[{"c.name": "UserService"}])

    svc = NLCypherService(mock_store, mock_llm)
    result = await svc.query("List all classes")

    assert result["cypher"] == "MATCH (c:Class) RETURN c.name LIMIT 5"
    assert "```" not in result["cypher"]


@pytest.mark.asyncio
async def test_nl_cypher_retry_on_error(mock_store, mock_llm):
    mock_llm.complete.side_effect = [
        "MATCH (f:Function RETURN f.name",
        "MATCH (f:Function) RETURN f.name LIMIT 10",
    ]
    mock_store.execute_query.side_effect = [
        Exception("Syntax error"),
        MagicMock(data=[{"f.name": "test"}]),
    ]

    svc = NLCypherService(mock_store, mock_llm, max_retries=2)
    result = await svc.query("Find functions")

    assert result["total"] == 1
    assert result["attempt"] == 2
    assert "error" not in result


@pytest.mark.asyncio
async def test_nl_cypher_max_retries_exceeded(mock_store, mock_llm):
    mock_llm.complete.return_value = "INVALID CYPHER"
    mock_store.execute_query.side_effect = Exception("always fails")

    svc = NLCypherService(mock_store, mock_llm, max_retries=2)
    result = await svc.query("bad query")

    assert "error" in result
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_nl_cypher_repository_hint(mock_store, mock_llm):
    mock_llm.complete.return_value = (
        "MATCH (f:Function) WHERE f.repository = $repo RETURN f LIMIT 10"
    )
    mock_store.execute_query.return_value = MagicMock(data=[])

    svc = NLCypherService(mock_store, mock_llm)
    await svc.query("Find functions", repository="my-repo")

    call_args = mock_llm.complete.call_args
    system_msg = call_args[0][0][0]["content"]
    assert "$repo" in system_msg


@pytest.mark.asyncio
async def test_nl_cypher_schema_prompt_contains_all_node_types():
    for label in ["Function", "Class", "Module", "Document", "BusinessFlow", "WikiPage", "Chunk"]:
        assert label in GRAPH_SCHEMA_PROMPT
    for edge in ["CALLS", "INHERITS", "IMPORTS", "CONTAINS", "CROSS_REPO_CALLS", "DEPENDS_ON", "ACCESSES_TABLE"]:
        assert edge in GRAPH_SCHEMA_PROMPT


@pytest.mark.asyncio
async def test_nl_cypher_blocks_write_operations(mock_store, mock_llm):
    """Mutating Cypher (CREATE, DELETE, SET, MERGE) must be rejected."""
    for bad_cypher in [
        "CREATE (n:Function {name: 'evil'})",
        "MATCH (n) DELETE n",
        "MATCH (n) DETACH DELETE n",
        "MATCH (n) SET n.name = 'hacked'",
        "MERGE (n:Function {name: 'x'})",
    ]:
        mock_llm.complete.return_value = bad_cypher
        svc = NLCypherService(mock_store, mock_llm)
        result = await svc.query("anything")
        assert "error" in result, f"Should block: {bad_cypher}"
        assert result["total"] == 0


@pytest.mark.asyncio
async def test_nl_cypher_handles_llm_exception(mock_store, mock_llm):
    """LLM provider exception returns structured error."""
    mock_llm.complete.side_effect = Exception("LLM timeout")
    svc = NLCypherService(mock_store, mock_llm)
    result = await svc.query("anything")
    assert "error" in result
    assert "Failed to generate" in result["error"]


@pytest.mark.asyncio
async def test_nl_cypher_question_truncated(mock_store, mock_llm):
    """Very long questions should be truncated in the prompt."""
    mock_llm.complete.return_value = "MATCH (f:Function) RETURN f.name LIMIT 5"
    mock_store.execute_query.return_value = MagicMock(data=[])

    long_question = "x" * 5000
    svc = NLCypherService(mock_store, mock_llm)
    await svc.query(long_question)

    user_msg = mock_llm.complete.call_args[0][0][1]["content"]
    assert len(user_msg) < 3000


def test_extract_cypher_with_sql_fence():
    """Handle ```sql fence (common LLM output)."""
    raw = "Here's the query:\n```sql\nMATCH (n) RETURN n LIMIT 5\n```\nDone."
    assert NLCypherService._extract_cypher(raw) == "MATCH (n) RETURN n LIMIT 5"


def test_extract_cypher_plain_match():
    """Extract MATCH from unfenced prose."""
    raw = "Sure, here is the query: MATCH (f:Function) RETURN f.name LIMIT 10"
    result = NLCypherService._extract_cypher(raw)
    assert result.startswith("MATCH")
