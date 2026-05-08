# tests/wiki/test_citation_verifier.py
from wiki.citation_verifier import verify_citations, extract_code_references


class TestExtractCodeReferences:
    def test_backtick_references(self):
        content = "The `UserService` class calls `OrderService.createOrder()` method."
        refs = extract_code_references(content)
        assert "UserService" in refs
        assert "OrderService" in refs

    def test_source_protocol_refs(self):
        content = "See source://com.example.UserService for details."
        refs = extract_code_references(content)
        assert "UserService" in refs

    def test_no_refs(self):
        content = "This is plain text without code references."
        refs = extract_code_references(content)
        assert len(refs) == 0

    def test_dedup(self):
        content = "`UserService` is used by `UserService` and `OrderService`."
        refs = extract_code_references(content)
        assert refs.count("UserService") == 1


class TestVerifyCitations:
    def test_all_valid(self):
        content = "The `UserService` class handles auth."
        known_entities = {"UserService", "OrderService"}
        result = verify_citations(content, known_entities)
        assert result.valid_count == 1
        assert result.invalid_count == 0

    def test_some_invalid(self):
        content = "The `FakeService` calls `UserService`."
        known_entities = {"UserService"}
        result = verify_citations(content, known_entities)
        assert result.valid_count == 1
        assert result.invalid_count == 1
        assert "FakeService" in result.invalid_refs

    def test_empty_content(self):
        result = verify_citations("", set())
        assert result.valid_count == 0
        assert result.invalid_count == 0
