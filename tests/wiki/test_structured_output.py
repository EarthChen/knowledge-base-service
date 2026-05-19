"""Tests for structured output model and rendering."""

import pytest

from wiki.structured_output import WikiPageOutput, WikiSection, render_wiki_page


class TestWikiPageOutput:
    def test_valid_output_parsing(self):
        data = {
            "title": "User Service",
            "summary": "Handles user operations.",
            "sections": [
                {"heading": "Overview", "content": "The user service...", "code_refs": []},
                {"heading": "API", "content": "REST endpoints...", "code_refs": ["UserController"]},
            ],
            "modules_covered": ["UserService", "UserController"],
            "dependencies_mentioned": ["DatabaseService"],
        }
        output = WikiPageOutput.model_validate(data)
        assert output.title == "User Service"
        assert len(output.sections) == 2
        assert output.modules_covered == ["UserService", "UserController"]

    def test_minimal_output(self):
        data = {
            "title": "Test",
            "summary": "A test page.",
            "sections": [{"heading": "Overview", "content": "Content"}],
            "modules_covered": [],
        }
        output = WikiPageOutput.model_validate(data)
        assert output.title == "Test"
        assert output.dependencies_mentioned == []

    def test_render_produces_valid_markdown(self):
        output = WikiPageOutput(
            title="Order Service",
            summary="Manages orders.",
            sections=[
                WikiSection(heading="Overview", content="The order service manages...", code_refs=["OrderService"]),
                WikiSection(heading="Flow", content="1. Create order\n2. Process payment", code_refs=[]),
            ],
            modules_covered=["OrderService", "PaymentGateway"],
            dependencies_mentioned=["PaymentGateway"],
        )
        md = render_wiki_page(output)
        assert "# Order Service" in md
        assert "## Overview" in md
        assert "## Flow" in md
        assert "OrderService" in md

    def test_render_includes_code_refs_as_source_links(self):
        output = WikiPageOutput(
            title="Test",
            summary="Test.",
            sections=[
                WikiSection(heading="Impl", content="Details.", code_refs=["FooClass", "BarMethod"]),
            ],
            modules_covered=["FooClass"],
        )
        md = render_wiki_page(output)
        assert "FooClass" in md
        assert "BarMethod" in md

    def test_json_schema_generation(self):
        schema = WikiPageOutput.model_json_schema()
        assert "title" in schema["properties"]
        assert "sections" in schema["properties"]
        assert schema["properties"]["sections"]["type"] == "array"
