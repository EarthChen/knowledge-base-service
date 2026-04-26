from wiki.models import CodeSnippet, ImportanceTier


def test_code_snippet_creation():
    snippet = CodeSnippet(
        source="def hello():\n    print('hello')",
        file_path="src/main.py",
        start_line=1,
        end_line=2,
        origin="chunk",
    )
    assert snippet.origin == "chunk"
    assert snippet.start_line == 1


def test_code_snippet_origin_values():
    for origin in ("chunk", "file", "signature"):
        snippet = CodeSnippet(
            source="code",
            file_path="f.py",
            start_line=1,
            end_line=1,
            origin=origin,
        )
        assert snippet.origin == origin


def test_importance_tier_values():
    assert ImportanceTier.CORE == "core"
    assert ImportanceTier.STANDARD == "standard"
    assert ImportanceTier.SKELETON == "skeleton"


def test_importance_tier_ordering():
    tiers = [ImportanceTier.SKELETON, ImportanceTier.CORE, ImportanceTier.STANDARD]
    assert ImportanceTier.CORE in tiers
