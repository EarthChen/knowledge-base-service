from wiki.models import ChunkSnippet


def test_chunk_snippet_creation():
    snippet = ChunkSnippet(
        text="def hello(): pass",
        file_path="src/main.py",
        score=0.85,
        parent_name="MainService",
        parent_uid="Class:src/main.py:MainService:1",
        start_line=10,
        end_line=15,
    )
    assert snippet.score == 0.85
    assert snippet.parent_name == "MainService"


def test_chunk_snippet_defaults():
    snippet = ChunkSnippet(
        text="code",
        file_path="f.py",
        score=0.5,
        parent_name="Foo",
    )
    assert snippet.parent_uid == ""
    assert snippet.start_line == 0
    assert snippet.end_line == 0
