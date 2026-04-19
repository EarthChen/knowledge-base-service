"""Tests for document text formatting used in embedding generation."""

from indexer.embedding_generator import _format_doc_text


class TestFormatDocText:
    def test_includes_title_section_and_content(self) -> None:
        out = _format_doc_text("My Guide", "Installation", "Run `uv sync`.")
        assert out == "Document: My Guide\nSection: Installation\nRun `uv sync`."

    def test_empty_section_omitted(self) -> None:
        out = _format_doc_text("API", "", "POST /items creates a row.")
        assert "Section:" not in out
        assert out == "Document: API\nPOST /items creates a row."

    def test_long_content_preserved_not_truncated(self) -> None:
        long_body = "x" * 50_000
        out = _format_doc_text("Doc", "Body", long_body)
        assert "Document: Doc" in out
        assert "Section: Body" in out
        assert long_body in out
        assert len(out) > 50_000
