"""Unit tests for wiki.context — T1.4 Composer context layer."""

from __future__ import annotations

import json

from wiki.context import WikiContext, WikiContextBuilder


class TestGlossary:
    async def test_glossary_generation_with_llm(self) -> None:
        captured: dict[str, str] = {}

        class MockLLM:
            async def generate(self, prompt: str, system: str = "") -> str:
                captured["prompt"] = prompt
                captured["system"] = system
                return json.dumps({"KBS": "Knowledge-Base-Service", "API": "Application Programming Interface"})

        builder = WikiContextBuilder(llm=MockLLM())
        glossary = await builder.build_glossary(
            module_names=["service/", "api/"],
            entry_points=["com.example.Main"],
        )
        assert glossary == {"KBS": "Knowledge-Base-Service", "API": "Application Programming Interface"}
        assert "service/" in captured["prompt"] or "service" in captured["prompt"]

    async def test_glossary_generation_structural(self) -> None:
        builder = WikiContextBuilder(llm=None)
        glossary = await builder.build_glossary(
            module_names=["billing", "notifications"],
            entry_points=["cmd/main.go"],
        )
        assert "billing" in glossary
        assert "notifications" in glossary
        assert glossary["billing"].startswith("Module") or "billing" in glossary["billing"].lower()


class TestBudgetAndTokens:
    def test_estimate_tokens(self) -> None:
        b = WikiContextBuilder()
        assert b.estimate_tokens("") == 0
        assert b.estimate_tokens("abcd") == 1
        assert b.estimate_tokens("a" * 400) == 100

    def test_context_budget_within_limit(self) -> None:
        b = WikiContextBuilder()
        text = "short"
        assert b.truncate_to_budget(text, budget=100) == "short"

    def test_context_budget_exceeds_limit(self) -> None:
        b = WikiContextBuilder()
        long_text = "word " * 500
        out = b.truncate_to_budget(long_text, budget=10)
        assert out.endswith("... and more")
        assert len(out) < len(long_text)


class TestStyleAndHierarchy:
    def test_style_sheet_template(self) -> None:
        sheet = WikiContextBuilder().build_style_sheet()
        tone_idx = sheet.lower().find("tone")
        structure_idx = sheet.lower().find("structure")
        assert tone_idx != -1 and structure_idx != -1
        assert tone_idx < structure_idx

    def test_hierarchical_context_injection(self) -> None:
        b = WikiContextBuilder()
        style = b.build_style_sheet()
        glossary = {"Foo": "Bar term"}
        combined = b.build_page_context(
            parent_summary="Parent chapter covers auth.",
            glossary=glossary,
            style_sheet=style,
        )
        assert "Parent chapter covers auth." in combined
        assert "Foo" in combined and "Bar term" in combined
        assert style in combined


class TestWikiContextDataclass:
    def test_wiki_context_fields(self) -> None:
        ctx = WikiContext(
            repository_context="repo",
            module_contexts={"a/": "m"},
            page_contexts={"p.md": "x"},
            glossary={"k": "v"},
        )
        assert ctx.repository_context == "repo"
        assert ctx.module_contexts["a/"] == "m"
        assert ctx.page_contexts["p.md"] == "x"
        assert ctx.glossary["k"] == "v"


class TestRepositoryContext:
    async def test_build_repository_context_without_llm(self) -> None:
        b = WikiContextBuilder(llm=None)
        text = await b.build_repository_context(
            modules=["svc", "api"],
            arch_summary="Three-layer Spring layout.",
        )
        assert "svc" in text and "api" in text
        assert "Three-layer" in text
