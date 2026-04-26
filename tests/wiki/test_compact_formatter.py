from wiki.compact_formatter import CompactFormatter


def test_format_found_entity():
    formatter = CompactFormatter(max_tokens=4000)
    data = {
        "found": True,
        "entity": {
            "name": "AuthService",
            "type": "class",
            "file": "auth.py",
            "signature": "class AuthService(BaseService)",
            "docstring": "Handles authentication and authorization.",
        },
        "relationships": [
            {"rel_type": "CALLS", "other_name": "TokenValidator"},
        ],
        "wiki_page": {"content": "# AuthService\nAuth module documentation."},
    }
    result = formatter.format_entity(data)
    assert result["name"] == "AuthService"
    assert result["type"] == "class"
    assert "sig" in result
    assert "rels" in result
    assert len(result["rels"]) == 1


def test_format_not_found_entity():
    formatter = CompactFormatter()
    result = formatter.format_entity({"found": False})
    assert result["status"] == "not_found"


def test_format_search_results_respects_budget():
    formatter = CompactFormatter(max_tokens=100)
    results = [
        {"title": f"Entity{i}", "page_path": f"/e{i}", "score": 0.9 - i * 0.1, "snippet": "x" * 200}
        for i in range(20)
    ]
    compact = formatter.format_search_results(results)
    assert len(compact) < 20


def test_format_impact():
    formatter = CompactFormatter()
    data = {
        "page_uids": ["p1", "p2", "p3"],
        "affected_entities": ["e1", "e2"],
        "trigger": "git_push",
    }
    result = formatter.format_impact(data)
    assert result["pages_affected"] == 3
    assert result["entities_affected"] == 2
