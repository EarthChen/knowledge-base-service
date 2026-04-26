import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.source_code_reader import SourceCodeReader
from wiki.models import CodeSnippet
from store.schema import GraphNode, NodeLabel

@pytest.fixture
def mock_wiki_store():
    store = MagicMock()
    store.find_chunks_by_parent_uid = AsyncMock()
    return store

def _make_node(label: str = "Class", uid: str = "Class:f.py:Foo:1",
               name: str = "Foo", file: str = "src/foo.py",
               start_line: int = 1, end_line: int = 50,
               signature: str = "class Foo:", docstring: str = "A foo class.") -> GraphNode:
    return GraphNode(
        label=NodeLabel(label),
        uid=uid,
        properties={
            "name": name, "file": file,
            "start_line": start_line, "end_line": end_line,
            "signature": signature, "docstring": docstring,
        },
    )

@pytest.mark.asyncio
async def test_read_from_chunks(mock_wiki_store):
    """When Chunk data is available, code comes from chunks."""
    result = MagicMock()
    result.result_set = [
        ["def hello():\n    pass", "src/foo.py", 1, 5, 0],
        ["def world():\n    pass", "src/foo.py", 6, 10, 1],
    ]
    mock_wiki_store.find_chunks_by_parent_uid.return_value = result

    reader = SourceCodeReader(mock_wiki_store)
    node = _make_node()
    snippets = await reader.read(node, budget_tokens=8000)

    assert len(snippets) >= 1
    assert snippets[0].origin == "chunk"
    assert "def hello" in snippets[0].source

@pytest.mark.asyncio
async def test_fallback_to_signature(mock_wiki_store):
    """When no chunks and no repo_path, fall back to signature+docstring."""
    result = MagicMock()
    result.result_set = []
    mock_wiki_store.find_chunks_by_parent_uid.return_value = result

    reader = SourceCodeReader(mock_wiki_store)
    node = _make_node(signature="class Foo:", docstring="A foo class.")
    snippets = await reader.read(node, budget_tokens=8000)

    assert len(snippets) == 1
    assert snippets[0].origin == "signature"
    assert "class Foo:" in snippets[0].source

@pytest.mark.asyncio
async def test_token_budget_truncation(mock_wiki_store):
    """Code exceeding budget is truncated."""
    long_code = "x = 1\n" * 5000  # ~30000 chars ~7500 tokens
    result = MagicMock()
    result.result_set = [[long_code, "src/foo.py", 1, 5000, 0]]
    mock_wiki_store.find_chunks_by_parent_uid.return_value = result

    reader = SourceCodeReader(mock_wiki_store)
    node = _make_node()
    snippets = await reader.read(node, budget_tokens=1000)

    total_chars = sum(len(s.source) for s in snippets)
    assert total_chars < 1000 * 4 + 200  # budget * 4 chars/token + margin

def test_estimate_tokens():
    reader = SourceCodeReader(MagicMock())
    assert reader.estimate_tokens("hello world") == 2  # 11 chars / 4 ≈ 2

def test_truncate_code():
    reader = SourceCodeReader(MagicMock())
    code = "\n".join(f"line {i}" for i in range(100))
    truncated = reader.truncate_code(code, max_tokens=50)
    assert "[truncated" in truncated
    assert len(truncated) < len(code)


def test_truncate_code_very_small_budget():
    reader = SourceCodeReader(MagicMock())
    code = "\n".join(f"line {i}" for i in range(100))
    truncated = reader.truncate_code(code, max_tokens=5)
    assert len(truncated) < 100
    assert "truncated" in truncated
